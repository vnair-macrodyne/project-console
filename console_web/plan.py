"""
plan.py — PM write controls for the Project Console: the PROJECT PLAN / schedule inputs.

Sibling of pm.py (which owns the budget). This is the "simple Carpedia interpretation":
the project-level schedule values PMs enter today — % Done, Planned Ship Date, and the
Labour / Material run-out forecasts — captured per project for the current week. Closing
this closes the last manual gap on the dashboard (its Schedule / % Done / run-out cells).

Writes go to Reporting.tblProjectPMEntry, upserted by (ProjectID, YearWeekKey): the current
week's row is updated in place, or created (carrying forward the previous week's procurement
/ material fields so nothing on the board blanks). The Console store is the only write
target; ETO stays read-only.

NOTE (design, per owner): % Done here is a PM judgement — subjective. The objective version
comes later from the allocation model (sql/006_plan_allocation.sql): actual hours from ETO
against hours ALLOCATED to each activity give a measured % complete. This form ships the
gap-closer now; the allocation table is stood up ready for that next phase.
"""
import datetime as _dt

# The six disciplines the plan captures % complete against (order = the form's order).
# Matches the dashboard crosswalk / earned-value roll-up.
DISCIPLINES = ["Project Management", "Mechanical Engineering", "Electrical Engineering",
               "Hydraulic Engineering", "Manufacturing", "Other"]


# ── week keying (matches the workbook's Year-Week convention, e.g. 202629) ──────
def excel_weeknum(d):
    """Excel WEEKNUM of a date — same algorithm the labour feed uses (keys line up)."""
    jan1 = _dt.date(d.year, 1, 1)
    jan1_offset = (jan1.weekday() + 1) % 7
    return (d.timetuple().tm_yday + jan1_offset - 1) // 7 + 1


def week_key(d):
    """(FiscalYear, WeekNo, YearWeekKey) for a date. YearWeekKey = year*100 + week."""
    wk = excel_weeknum(d)
    return d.year, wk, d.year * 100 + wk


class PlanService:
    def list_projects(self) -> dict:
        raise NotImplementedError

    def get_plan(self, project_id) -> dict:
        raise NotImplementedError

    def save_plan(self, payload) -> dict:
        raise NotImplementedError

    def close(self):
        pass


# ─────────────────────────────────────────────────────────────────────────────
# Live — Console store (write) + ETO (read-only, for the project list/names)
# ─────────────────────────────────────────────────────────────────────────────
class LivePlanService(PlanService):
    # procurement + material columns carried forward on a new week so the board doesn't blank
    _CARRY = ["MaterialActual", "MaterialBudget", "TotalLineItems", "LLTPOrdered",
              "LLTPReleasedLate", "LLTPOrderedLate", "LLTPDeliveredLate",
              "PartsReleasedLate", "PartsOrderedLate", "Rank", "ReRank"]

    def __init__(self):
        self._console = None
        self._eto = None

    def _cc(self):
        if self._console is None:
            from console.infra.connections import console_connection
            self._console = console_connection()
        return self._console

    def _ec(self):
        if self._eto is None:
            from console.infra.connections import eto_connection
            self._eto = eto_connection()
        return self._eto

    def _eto_names(self, pids=None):
        try:
            cur = self._ec().cursor()
            if pids:
                ids = ",".join(str(int(p)) for p in pids)
                cur.execute(f"SELECT ProjectID, DisplayName FROM tblProjects WHERE ProjectID IN ({ids})")
            else:
                cur.execute("SELECT ProjectID, DisplayName FROM tblProjects")
            return {int(r[0]): r[1] for r in cur.fetchall()}
        except Exception:
            return {}

    def _budgeted_ids(self):
        cur = self._cc().cursor()
        cur.execute("SELECT DISTINCT ProjectID FROM Reporting.vw_Console_BudgetCurrent")
        return [int(r[0]) for r in cur.fetchall()]

    def list_projects(self):
        # projects with a budget are the ones a plan is meaningful for; others can be brought in
        budgeted = set(self._budgeted_ids())
        names = self._eto_names()
        planned = self._planned_ids()
        prim = [{"id": pid, "name": names.get(pid, "")} for pid in sorted(budgeted)]
        avail = [{"id": pid, "name": nm} for pid, nm in sorted(names.items()) if pid not in budgeted]
        return {"budgeted": prim, "available": avail, "planned": sorted(planned)}

    def _planned_ids(self):
        try:
            cur = self._cc().cursor()
            cur.execute("SELECT DISTINCT ProjectID FROM Reporting.tblProjectPMEntry")
            return {int(r[0]) for r in cur.fetchall()}
        except Exception:
            return set()

    def get_plan(self, project_id):
        pid = int(project_id)
        name = self._eto_names([pid]).get(pid, "")
        base = {"project_id": pid, "name": name, "exists": False,
                "planned_ship": None, "planned_ship_default": False,
                "labour_runout": None, "material_runout": None,   # optional PM overrides only
                "rework_threshold": None, "week": None,
                "discipline_progress": {d: None for d in DISCIPLINES}}
        try:
            cur = self._cc().cursor()
            cur.execute("SELECT TOP 1 PlannedShipDate, LabourRunout, "
                        "MaterialRunout, ReworkThreshold, YearWeekKey "
                        "FROM Reporting.tblProjectPMEntry "
                        "WHERE ProjectID = ? ORDER BY YearWeekKey DESC", pid)
            r = cur.fetchone()
            if r:
                base.update(exists=True,
                            planned_ship=_iso(r[0]),
                            labour_runout=_ratio_out(r[1]), material_runout=_ratio_out(r[2]),
                            rework_threshold=_pct_out(r[3]),
                            week=int(r[4]) if r[4] is not None else None)
        except Exception:
            pass
        # per-discipline % complete — latest week per discipline (the run-out inputs)
        try:
            cur = self._cc().cursor()
            cur.execute(
                "SELECT Discipline, PercentComplete FROM ("
                "  SELECT Discipline, PercentComplete,"
                "         ROW_NUMBER() OVER (PARTITION BY Discipline ORDER BY YearWeekKey DESC) rn"
                "  FROM Reporting.tblProjectDisciplineProgress"
                "  WHERE ProjectID = ? AND PercentComplete IS NOT NULL) t WHERE rn = 1", pid)
            for disc, pct in cur.fetchall():
                if disc in base["discipline_progress"]:
                    base["discipline_progress"][disc] = _pct_out(pct)
                    base["exists"] = True
        except Exception:
            pass
        # Planned Ship stays a MANUAL Console value — ETO carries no maintained ship date
        # (verified 2026-08-11: tblProjects.PDelivery / vwProjects.SalesDelivery / per-spec
        # BudgetShipRelease all empty). To avoid a blank field, default it from the customer-agreed
        # (else PO) ship date already in the overlay; it's just a starting point the PM can override.
        if not base.get("planned_ship"):
            try:
                cur = self._cc().cursor()
                cur.execute("SELECT TOP 1 CustAgreedShipDate, POShipDate "
                            "FROM Reporting.vw_Console_ManualOverlay WHERE ProjectID = ?", pid)
                r = cur.fetchone()
                if r:
                    d = r[0] if r[0] is not None else r[1]
                    if d is not None:
                        base["planned_ship"] = _iso(d)
                        base["planned_ship_default"] = True
            except Exception:
                pass
        return base

    def save_plan(self, payload):
        pid = int(payload["project_id"])
        # % complete is now captured PER DISCIPLINE (drives the calculated run-out); the single
        # project PercentComplete is retired (dashboard derives it from the roll-up). Labour /
        # Material run-out are optional OVERRIDES — blank means "use the calculated figure".
        lrun = _ratio_pct(payload.get("labour_runout"))    # optional override; 125 → 1.25
        mrun = _ratio_pct(payload.get("material_runout"))  # optional override
        thr = _thr_in(payload.get("rework_threshold"))     # 1.0 (%) → 0.01 fraction
        ship = _as_date(payload.get("planned_ship"))
        by = (payload.get("entered_by") or None)
        fy, wk, key = week_key(_dt.date.today())
        conn = self._cc()
        cur = conn.cursor()
        cur.execute("SELECT PMEntryID FROM Reporting.tblProjectPMEntry "
                    "WHERE ProjectID = ? AND YearWeekKey = ?", pid, key)
        row = cur.fetchone()
        if row:
            cur.execute("UPDATE Reporting.tblProjectPMEntry SET PlannedShipDate = ?, "
                        "LabourRunout = ?, MaterialRunout = ?, "
                        "ReworkThreshold = ?, CapturedAt = GETDATE() WHERE PMEntryID = ?",
                        ship, lrun, mrun, thr, int(row[0]))
        else:
            carry = self._carry_forward(cur, pid)
            cur.execute(
                "INSERT INTO Reporting.tblProjectPMEntry "
                "(ProjectID, FiscalYear, WeekNo, YearWeekKey, PlannedShipDate, "
                " LabourRunout, MaterialRunout, ReworkThreshold, MaterialActual, MaterialBudget, "
                " TotalLineItems, LLTPOrdered, LLTPReleasedLate, LLTPOrderedLate, LLTPDeliveredLate, "
                " PartsReleasedLate, PartsOrderedLate, IncludeFlag, Rank, ReRank, CapturedAt) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,1,?,?,GETDATE())",
                pid, fy, wk, key, ship, lrun, mrun, thr,
                carry.get("MaterialActual"), carry.get("MaterialBudget"),
                carry.get("TotalLineItems"), carry.get("LLTPOrdered"),
                carry.get("LLTPReleasedLate"), carry.get("LLTPOrderedLate"),
                carry.get("LLTPDeliveredLate"), carry.get("PartsReleasedLate"),
                carry.get("PartsOrderedLate"), carry.get("Rank"), carry.get("ReRank"))
        self._save_discipline_progress(cur, pid, fy, wk, key, by,
                                       payload.get("discipline_progress") or {})
        conn.commit()
        return {"ok": True, "project_id": pid, "week": key,
                "planned_ship": _iso(ship)}

    def _save_discipline_progress(self, cur, pid, fy, wk, key, by, prog):
        """Upsert per-discipline % complete for the current week (the run-out inputs)."""
        for disc in DISCIPLINES:
            if disc not in prog:
                continue                                    # not on the form payload → leave as-is
            frac = _frac_pct(prog.get(disc))                # blank clears it (NULL)
            cur.execute("SELECT ProgressID FROM Reporting.tblProjectDisciplineProgress "
                        "WHERE ProjectID = ? AND YearWeekKey = ? AND Discipline = ?", pid, key, disc)
            r = cur.fetchone()
            if r:
                cur.execute("UPDATE Reporting.tblProjectDisciplineProgress "
                            "SET PercentComplete = ?, EnteredBy = ?, CapturedAt = GETDATE() "
                            "WHERE ProgressID = ?", frac, by, int(r[0]))
            else:
                cur.execute("INSERT INTO Reporting.tblProjectDisciplineProgress "
                            "(ProjectID, FiscalYear, WeekNo, YearWeekKey, Discipline, "
                            " PercentComplete, EnteredBy, CapturedAt) VALUES (?,?,?,?,?,?,?,GETDATE())",
                            pid, fy, wk, key, disc, frac, by)

    def _carry_forward(self, cur, pid):
        """Latest prior week's procurement/material values, so a new week doesn't blank them."""
        try:
            cur.execute(f"SELECT TOP 1 {', '.join(self._CARRY)} FROM Reporting.tblProjectPMEntry "
                        "WHERE ProjectID = ? ORDER BY YearWeekKey DESC", pid)
            r = cur.fetchone()
            return dict(zip(self._CARRY, r)) if r else {}
        except Exception:
            return {}

    def close(self):
        for c in (self._console, self._eto):
            try:
                if c:
                    c.close()
            except Exception:
                pass


# ─────────────────────────────────────────────────────────────────────────────
# Demo — in-memory (no DB), so the form is fully exercisable with --demo
# ─────────────────────────────────────────────────────────────────────────────
_DEMO_NAMES = {230219: "230219 - 5500 Ton Forging Press", 230312: "230312 - 2500T Compression Press",
               240087: "240087 - 650 Ton Trim Press", 250005: "250005 - 15,000 Ton Forging Press"}


class DemoPlanService(PlanService):
    _store = {   # persists across requests within the process
        230219: {"planned_ship": "2026-10-02",
                 "labour_runout": None, "material_runout": None, "rework_threshold": 0.015,
                 "discipline_progress": {"Project Management": 0.95, "Mechanical Engineering": 0.88,
                                         "Electrical Engineering": 0.90, "Hydraulic Engineering": 0.92,
                                         "Manufacturing": 0.80, "Other": 0.85}},
    }

    def list_projects(self):
        planned = set(DemoPlanService._store)
        prim = [{"id": pid, "name": _DEMO_NAMES.get(pid, "")} for pid in sorted(_DEMO_NAMES)]
        return {"budgeted": prim, "available": [], "planned": sorted(planned)}

    def get_plan(self, project_id):
        pid = int(project_id)
        rec = DemoPlanService._store.get(pid)
        base = {"project_id": pid, "name": _DEMO_NAMES.get(pid, ""), "exists": rec is not None,
                "planned_ship": None, "planned_ship_default": False,
                "labour_runout": None, "material_runout": None, "rework_threshold": None,
                "week": week_key(_dt.date.today())[2],
                "discipline_progress": {d: None for d in DISCIPLINES}}
        if rec:
            base.update(planned_ship=rec["planned_ship"],
                        labour_runout=_ratio_out(rec["labour_runout"]),
                        material_runout=_ratio_out(rec["material_runout"]),
                        rework_threshold=_pct_out(rec.get("rework_threshold")),
                        discipline_progress={d: _pct_out(rec.get("discipline_progress", {}).get(d))
                                             for d in DISCIPLINES})
        return base

    def save_plan(self, payload):
        pid = int(payload["project_id"])
        prog = payload.get("discipline_progress") or {}
        DemoPlanService._store[pid] = {
            "planned_ship": (payload.get("planned_ship") or None),
            "labour_runout": _ratio_pct(payload.get("labour_runout")),
            "material_runout": _ratio_pct(payload.get("material_runout")),
            "rework_threshold": _thr_in(payload.get("rework_threshold")),
            "discipline_progress": {d: _frac_pct(prog.get(d)) for d in DISCIPLINES},
        }
        return {"ok": True, "project_id": pid, "week": week_key(_dt.date.today())[2],
                "planned_ship": DemoPlanService._store[pid]["planned_ship"]}


# ─────────────────────────────────────────────────────────────────────────────
# helpers — %-done stored as a 0–1 fraction; run-out stored as a ratio (1.25 = 125%)
# ─────────────────────────────────────────────────────────────────────────────
def _num(x):
    if x is None or x == "":
        return None
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def _frac_pct(x):
    """Accept 0–100 (percent) or 0–1 (fraction); store a 0–1 fraction."""
    v = _num(x)
    if v is None:
        return None
    return round(v / 100.0, 4) if v > 1.0 else round(v, 4)


def _ratio_pct(x):
    """Accept 125 (percent-of-budget) or 1.25 (ratio); store a ratio."""
    v = _num(x)
    if v is None:
        return None
    return round(v / 100.0, 4) if v > 5.0 else round(v, 4)


def _thr_in(x):
    """Rework threshold input is always a percent (1.0 = 1%); store a 0–1 fraction (0.01)."""
    v = _num(x)
    return round(v / 100.0, 4) if v is not None else None


def _pct_out(frac):
    """0–1 fraction → a percentage number for the form (0.93 → 93)."""
    v = _num(frac)
    return round(v * 100.0, 2) if v is not None else None


def _ratio_out(r):
    """ratio → percentage for the form (1.25 → 125)."""
    v = _num(r)
    return round(v * 100.0, 1) if v is not None else None


def _as_date(x):
    if not x:
        return None
    try:
        return _dt.date.fromisoformat(str(x)[:10])
    except (TypeError, ValueError):
        return None


def _iso(d):
    try:
        return d.isoformat()[:10]
    except Exception:
        return None


def make_plan_service(demo=False) -> PlanService:
    return DemoPlanService() if demo else LivePlanService()
