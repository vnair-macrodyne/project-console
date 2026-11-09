"""
Tracked projects — the ONE switch for which projects Sextant follows (Vijay, 2026-11-09).

Sextant keeps the active / tracked project list itself; it replaces the "Worksheet" tab of the PMs'
Executive Dashboard workbook. A tracked project appears in the project selector, the dashboards,
the display screens and the Purchasing Exception Report. Removing one keeps its row and all its
budget / plan history (fully reversible).

Store (Console / Reporting DB):
  Reporting.tblActiveProject     (sql/020 + sql/022)  ProjectID, Priority, IsActive, Added*, Changed*
  Reporting.tblTrackedProjectLog (sql/022)            append-only change history
  Reporting.tblConsoleProjectExclusion (sql/017)      kept in step (remove writes it, add clears it)
                                                      so every older exclusion-based filter agrees.

This module owns every write to those tables. Budget banking (which needs ETO) stays in
pm.LivePMService.add_project, which calls activate() once the budget is in.

Reads are guarded: before sql/022 is applied (no IsActive column) every row counts as tracked and
writes raise a clear "apply sql/022" error. Portable SQL (no T-SQL-only constructs, timestamps
passed as parameters) so the logic is unit-testable on SQLite.
"""
from __future__ import annotations

import datetime as _dt

T_ACTIVE = "Reporting.tblActiveProject"
T_LOG = "Reporting.tblTrackedProjectLog"
T_EXCL = "Reporting.tblConsoleProjectExclusion"


class TrackedSchemaMissing(RuntimeError):
    """sql/022 has not been applied, so the list can't be edited yet."""


def _now():
    return _dt.datetime.now().replace(microsecond=0)


class TrackedProjectDAO:
    """All SQL for the tracked-project list. `conn` = a Console-store DB-API connection."""

    def __init__(self, conn):
        self._conn = conn
        self._switch = None          # does tblActiveProject have IsActive (sql/022)?

    # ── schema probes ────────────────────────────────────────────────────────────────────────
    def has_switch(self) -> bool:
        if self._switch is None:
            try:
                cur = self._conn.cursor()
                cur.execute(f"SELECT IsActive FROM {T_ACTIVE} WHERE 1 = 0")
                cur.fetchall()
                self._switch = True
            except Exception:
                self._rollback()
                self._switch = False
        return self._switch

    def _require_switch(self):
        if not self.has_switch():
            raise TrackedSchemaMissing(
                "The tracked-projects list can't be edited until sql/022_tracked_projects.sql is "
                "applied to the Reporting database (run it once in SSMS, then the GRANT it lists).")

    def _rollback(self):
        try:
            self._conn.rollback()
        except Exception:
            pass

    # ── reads ────────────────────────────────────────────────────────────────────────────────
    def active_ids(self) -> set:
        """Tracked project IDs. Empty set if the table doesn't exist (callers then fall back)."""
        try:
            cur = self._conn.cursor()
            if self.has_switch():
                cur.execute(f"SELECT ProjectID FROM {T_ACTIVE} WHERE IsActive = 1")
            else:
                cur.execute(f"SELECT ProjectID FROM {T_ACTIVE}")
            return {int(r[0]) for r in cur.fetchall()}
        except Exception:
            self._rollback()
            return set()

    def rows(self, include_removed=False) -> list:
        """Tracked rows ordered by priority (unprioritised last, then by project number)."""
        cur = self._conn.cursor()
        if self.has_switch():
            where = "" if include_removed else "WHERE IsActive = 1"
            cur.execute(f"SELECT ProjectID, Priority, IsActive, AddedBy, AddedAt, ChangedBy, ChangedAt "
                        f"FROM {T_ACTIVE} {where}")
            out = [{"id": int(r[0]), "priority": r[1], "active": bool(r[2]),
                    "added_by": r[3], "added_at": r[4], "changed_by": r[5], "changed_at": r[6]}
                   for r in cur.fetchall()]
        else:
            cur.execute(f"SELECT ProjectID, Priority, ImportedAt FROM {T_ACTIVE}")
            out = [{"id": int(r[0]), "priority": r[1], "active": True, "added_by": None,
                    "added_at": r[2], "changed_by": None, "changed_at": None}
                   for r in cur.fetchall()]
        out.sort(key=lambda d: (not d["active"], d["priority"] is None, d["priority"] or 0, d["id"]))
        return out

    def history(self, limit=50) -> list:
        try:
            cur = self._conn.cursor()
            cur.execute(f"SELECT ProjectID, Action, Detail, ChangedBy, ChangedAt FROM {T_LOG} "
                        f"ORDER BY LogID DESC")
            rows = cur.fetchmany(limit) if hasattr(cur, "fetchmany") else cur.fetchall()[:limit]
            return [{"id": (int(r[0]) if r[0] is not None else None), "action": r[1],
                     "detail": r[2], "by": r[3], "at": r[4]} for r in rows]
        except Exception:
            self._rollback()
            return []

    # ── internal write helpers (no commit) ───────────────────────────────────────────────────
    def _get(self, cur, pid):
        cur.execute(f"SELECT IsActive, Priority FROM {T_ACTIVE} WHERE ProjectID = ?", pid)
        return cur.fetchone()

    def _next_priority(self, cur):
        cur.execute(f"SELECT MAX(Priority) FROM {T_ACTIVE} WHERE IsActive = 1")
        r = cur.fetchone()
        return int(r[0] or 0) + 1

    def _log(self, cur, pid, action, detail, user, now):
        cur.execute(f"INSERT INTO {T_LOG} (ProjectID, Action, Detail, ChangedBy, ChangedAt) "
                    f"VALUES (?, ?, ?, ?, ?)", pid, action, detail, user, now)

    def _set_exclusion(self, cur, pid, excluded, user, now):
        try:
            if excluded:
                cur.execute(f"SELECT 1 FROM {T_EXCL} WHERE ProjectID = ?", pid)
                if not cur.fetchone():
                    cur.execute(f"INSERT INTO {T_EXCL} (ProjectID, ExcludedAt, ExcludedBy) VALUES (?, ?, ?)",
                                pid, now, user)
            else:
                cur.execute(f"DELETE FROM {T_EXCL} WHERE ProjectID = ?", pid)
        except Exception:
            # sql/017 absent -> nothing to keep in step; the IsActive switch is authoritative
            pass

    def _compact(self, cur, user, now):
        """Renumber tracked priorities to 1..n, preserving order (after a removal)."""
        cur.execute(f"SELECT ProjectID, Priority FROM {T_ACTIVE} WHERE IsActive = 1")
        rows = sorted(cur.fetchall(), key=lambda r: (r[1] is None, r[1] or 0, int(r[0])))
        for i, r in enumerate(rows, 1):
            if r[1] != i:
                cur.execute(f"UPDATE {T_ACTIVE} SET Priority = ? WHERE ProjectID = ?", i, int(r[0]))

    def _activate(self, cur, pid, user, now, action, priority=None):
        row = self._get(cur, pid)
        if row and row[0]:
            self._set_exclusion(cur, pid, False, user, now)      # keep sql/017 in step anyway
            return False
        prio = priority if priority is not None else self._next_priority(cur)
        if row:
            cur.execute(f"UPDATE {T_ACTIVE} SET IsActive = 1, Priority = ?, ChangedBy = ?, ChangedAt = ? "
                        f"WHERE ProjectID = ?", prio, user, now, pid)
        else:
            cur.execute(f"INSERT INTO {T_ACTIVE} (ProjectID, Priority, Source, ImportedAt, IsActive, "
                        f"AddedBy, AddedAt, ChangedBy, ChangedAt) VALUES (?, ?, ?, ?, 1, ?, ?, ?, ?)",
                        pid, prio, "Sextant", now, user, now, user, now)
        self._set_exclusion(cur, pid, False, user, now)
        self._log(cur, pid, action, f"priority {prio}", user, now)
        return True

    def _deactivate(self, cur, pid, user, now, action):
        row = self._get(cur, pid)
        self._set_exclusion(cur, pid, True, user, now)
        if not row or not row[0]:
            return False
        cur.execute(f"UPDATE {T_ACTIVE} SET IsActive = 0, Priority = NULL, ChangedBy = ?, ChangedAt = ? "
                    f"WHERE ProjectID = ?", user, now, pid)
        self._log(cur, pid, action, f"was priority {row[1]}" if row[1] is not None else None, user, now)
        return True

    def _tx(self, fn):
        self._require_switch()
        cur = self._conn.cursor()
        try:
            out = fn(cur)
            self._conn.commit()
            return out
        except Exception:
            self._rollback()
            raise

    # ── public writes (each is one transaction) ──────────────────────────────────────────────
    def activate(self, project_id, user=None) -> bool:
        """Track a project (appended at the bottom of the priority order). True if it changed."""
        pid, now = int(project_id), _now()
        return self._tx(lambda cur: self._activate(cur, pid, user, now, "add"))

    def deactivate(self, project_id, user=None) -> bool:
        """Stop tracking a project; row + history kept. True if it changed."""
        pid, now = int(project_id), _now()

        def run(cur):
            changed = self._deactivate(cur, pid, user, now, "remove")
            if changed:
                self._compact(cur, user, now)
            return changed
        return self._tx(run)

    def reorder(self, ordered_ids, user=None) -> list:
        """Set priorities 1..n from `ordered_ids`, which must be exactly the tracked set."""
        ids = [int(p) for p in ordered_ids]
        now = _now()

        def run(cur):
            cur.execute(f"SELECT ProjectID, Priority FROM {T_ACTIVE} WHERE IsActive = 1")
            current = {int(r[0]): r[1] for r in cur.fetchall()}
            if len(ids) != len(set(ids)) or set(ids) != set(current):
                raise ValueError("The new order must list every tracked project exactly once "
                                 "(the list may have changed — reload the page).")
            moved = []
            for i, pid in enumerate(ids, 1):
                if current[pid] != i:
                    cur.execute(f"UPDATE {T_ACTIVE} SET Priority = ?, ChangedBy = ?, ChangedAt = ? "
                                f"WHERE ProjectID = ?", i, user, now, pid)
                    moved.append(f"{pid}: {current[pid]}→{i}")
            if moved:
                self._log(cur, None, "reorder", "; ".join(moved)[:1000], user, now)
            return ids
        return self._tx(run)

    def replace_all(self, ordered_ids, user=None, source="seed") -> dict:
        """Make the tracked list exactly `ordered_ids` in that priority order (the one-time seed
        from the workbook). Unlisted tracked projects are removed (kept, reversible)."""
        ids = list(dict.fromkeys(int(p) for p in ordered_ids))
        now = _now()

        def run(cur):
            cur.execute(f"SELECT ProjectID FROM {T_ACTIVE} WHERE IsActive = 1")
            before = {int(r[0]) for r in cur.fetchall()}
            removed = [p for p in sorted(before) if p not in ids]
            for p in removed:
                self._deactivate(cur, p, user, now, f"{source}-remove")
            added = []
            for i, p in enumerate(ids, 1):
                if self._activate(cur, p, user, now, f"{source}-add", priority=i):
                    added.append(p)
                else:
                    cur.execute(f"UPDATE {T_ACTIVE} SET Priority = ? WHERE ProjectID = ?", i, p)
            return {"tracked": ids, "added": added, "removed": removed,
                    "kept": [p for p in ids if p in before]}
        return self._tx(run)
