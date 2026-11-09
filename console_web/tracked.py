"""
Tracked Projects page — Sextant's own list of the projects it follows (Vijay, 2026-11-09).

Replaces the "Worksheet" tab of the PMs' Executive Dashboard workbook. PMs (pm role and up) add,
remove and reorder; everyone else sees it read-only. Customer and project name are read live from
ETO (tblProjects -> tblCompany.CName), never typed. Adding a project also brings in its ETO budget
(pm.add_project), so a tracked project always has a budget behind it.

Store logic: console/domain/tracked.py. Routes: app.py /projects, /api/tracked*.
"""
from __future__ import annotations

import datetime as _dt


def _iso(v):
    if isinstance(v, (_dt.datetime, _dt.date)):
        return v.isoformat(sep=" ") if isinstance(v, _dt.datetime) else v.isoformat()
    return v


class LiveTrackedService:
    def __init__(self):
        self._c = self._e = None

    def _cc(self):
        if self._c is None:
            from console.infra.connections import console_connection
            self._c = console_connection()
        return self._c

    def _ec(self):
        if self._e is None:
            from console.infra.connections import eto_connection
            self._e = eto_connection()
        return self._e

    def _dao(self):
        from console.domain.tracked import TrackedProjectDAO
        return TrackedProjectDAO(self._cc())

    def _eto_projects(self):
        """{ProjectID: (DisplayName, Customer)} for every ETO project (best effort)."""
        try:
            cur = self._ec().cursor()
            cur.execute("SELECT p.ProjectID, p.DisplayName, c.CName FROM dbo.tblProjects p "
                        "LEFT JOIN dbo.tblCompany c ON c.CompanyID = p.CompanyID")
            return {int(r[0]): ((r[1] or "").strip(), (r[2] or "").strip()) for r in cur.fetchall()}
        except Exception:
            return {}

    def _banked(self):
        try:
            cur = self._cc().cursor()
            cur.execute("SELECT DISTINCT ProjectID FROM Reporting.vw_Console_BudgetCurrent")
            return {int(r[0]) for r in cur.fetchall()}
        except Exception:
            return set()

    def list(self):
        dao = self._dao()
        eto, banked = self._eto_projects(), self._banked()
        rows = []
        for r in dao.rows():
            name, cust = eto.get(r["id"], ("", ""))
            rows.append({"id": r["id"], "priority": r["priority"], "name": name, "customer": cust,
                         "banked": r["id"] in banked, "added_by": r["added_by"],
                         "added_at": _iso(r["added_at"]), "changed_by": r["changed_by"],
                         "changed_at": _iso(r["changed_at"])})
        tracked = {r["id"] for r in rows}
        candidates = [{"id": pid, "name": nm, "customer": cu}
                      for pid, (nm, cu) in sorted(eto.items(), reverse=True) if pid not in tracked]
        hist = [dict(h, at=_iso(h["at"])) for h in dao.history(50)]
        return {"rows": rows, "candidates": candidates, "history": hist,
                "editable": dao.has_switch()}

    def reorder(self, order, user=None):
        return {"ok": True, "order": self._dao().reorder(order, user)}

    def close(self):
        for c in (self._c, self._e):
            try:
                if c is not None:
                    c.close()
            except Exception:
                pass


class DemoTrackedService:
    """In-memory, shares its state with DemoPMService so Add/Remove on either page agree."""

    def list(self):
        from console_web.pm import DemoPMService, _DEMO_NAMES
        order = DemoPMService.tracked_order()
        rows = [{"id": pid, "priority": i, "name": _DEMO_NAMES.get(pid, str(pid)),
                 "customer": _DEMO_CUSTOMERS.get(pid, ""), "banked": pid in DemoPMService._store,
                 "added_by": "demo", "added_at": "2026-11-09 09:00:00", "changed_by": None,
                 "changed_at": None} for i, pid in enumerate(order, 1)]
        candidates = [{"id": pid, "name": nm, "customer": _DEMO_CUSTOMERS.get(pid, "")}
                      for pid, nm in sorted(_DEMO_NAMES.items()) if pid not in order]
        return {"rows": rows, "candidates": candidates, "history": list(DemoPMService._history),
                "editable": True}

    def reorder(self, order, user=None):
        from console_web.pm import DemoPMService
        order = [int(p) for p in order]
        if sorted(order) != sorted(DemoPMService.tracked_order()) or len(set(order)) != len(order):
            raise ValueError("The new order must list every tracked project exactly once "
                             "(the list may have changed — reload the page).")
        DemoPMService._order = order
        DemoPMService._history.insert(0, {"id": None, "action": "reorder", "detail": "demo reorder",
                                          "by": user or "demo", "at": "now"})
        return {"ok": True, "order": order}

    def close(self):
        pass


_DEMO_CUSTOMERS = {230219: "Apple", 230312: "Demo Customer", 240087: "Demo Customer",
                   250005: "15 Forge", 240044: "Spitz"}


def make_tracked_service(demo=False):
    return DemoTrackedService() if demo else LiveTrackedService()
