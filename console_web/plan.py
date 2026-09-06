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

# SpecID >= this is overhead/contingency (not a real machine) — same rule as pm.py / the
# Machine Asset Re-Code report. Machines below it get a per-machine % complete input.
_OVERHEAD_SPEC_MIN = 700


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
                "discipline_progress": {d: None for d in DISCIPLINES},
                "machines": []}
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
        # MACHINE × DISCIPLINE grid — every budgeted cell (machine + overhead group) with its
        # budget & actual hours from ETO and the latest week's entered % complete. This is the
        # superset of the budget-vs-actual breakdown; the PM declares progress at the cell.
        agg = self._md_agg(pid)
        prog = self._md_progress(pid)          # {(SpecID, discipline): form %}
        base["machines"] = self._grid(agg, prog)
        if any(d["pct"] is not None for m in base["machines"] for d in m["disciplines"]):
            base["exists"] = True
        return base

    def _hourtype_map(self):
        """{HourType: discipline} — store table if seeded, else derived from ETO."""
        from console.domain.hourtype_map import HourTypeDisciplineDAO
        dao = HourTypeDisciplineDAO(self._cc())
        return dao.load_map() or HourTypeDisciplineDAO.derive_from_eto(self._ec())

    def _md_agg(self, pid):
        """{SpecID_key: {discipline: [budget_hrs, actual_hrs]}} from ETO — budget =
        SUM(tblSpecHours.Hours), actual = SUM(vwTimecards.HourTime), per SpecID × HourType→
        discipline (SAME tables as the Budgets machine breakdown, so they reconcile). Overhead
        specs (>= 700) are folded into the sentinel key 0 (the Overhead / Contingency group)."""
        agg = {}
        try:
            htmap = self._hourtype_map()
            cur = self._ec().cursor()
            cur.execute("""
                WITH bud AS (SELECT SpecID, ISNULL(HourType,0) AS HourType, SUM(Hours) AS Budget
                             FROM dbo.tblSpecHours WHERE ProjectID = ? GROUP BY SpecID, ISNULL(HourType,0)),
                     act AS (SELECT SpecID, ISNULL(HourType,0) AS HourType, SUM(HourTime) AS Actual
                             FROM dbo.vwTimecards WHERE ProjectID = ? GROUP BY SpecID, ISNULL(HourType,0))
                SELECT COALESCE(b.SpecID, a.SpecID) AS SpecID,
                       COALESCE(b.HourType, a.HourType) AS HourType,
                       CAST(ISNULL(b.Budget,0) AS decimal(20,2)) AS Budget,
                       CAST(ISNULL(a.Actual,0) AS decimal(20,2)) AS Actual
                FROM bud b FULL OUTER JOIN act a ON a.SpecID = b.SpecID AND a.HourType = b.HourType
                WHERE (ISNULL(b.Budget,0) <> 0 OR ISNULL(a.Actual,0) <> 0)
            """, pid, pid)
            for spec, ht, b, a in cur.fetchall():
                b = float(b or 0); a = float(a or 0)
                try:
                    s = int(spec)
                except (TypeError, ValueError):
                    s = None
                key = 0 if (s is None or s >= _OVERHEAD_SPEC_MIN) else s
                try:
                    disc = htmap.get(int(ht), "Other")
                except (TypeError, ValueError):
                    disc = "Other"
                slot = agg.setdefault(key, {}).get(disc, [0.0, 0.0])
                slot[0] += b; slot[1] += a
                agg[key][disc] = slot
        except Exception:
            pass
        return agg

    @staticmethod
    def _grid(agg, prog):
        """Shape the agg + entered % into the ordered machine grid (real machines numeric-sorted,
        overhead group last)."""
        def _mkey(k):
            return (1, 0) if k == 0 else (0, k)
        out = []
        for spec in sorted(agg, key=_mkey):
            dh = agg[spec]
            discs = [{"discipline": d, "budget_hours": round(dh[d][0], 2),
                      "actual_hours": round(dh[d][1], 2), "pct": prog.get((spec, d))}
                     for d in sorted(dh)]
            out.append({
                "spec": spec,
                "machine": ("Overhead / Contingency" if spec == 0 else f"Machine {spec}"),
                "overhead": spec == 0,
                "budget_hours": round(sum(v[0] for v in dh.values()), 2),
                "actual_hours": round(sum(v[1] for v in dh.values()), 2),
                "disciplines": discs,
            })
        return out

    def _md_progress(self, pid):
        """{(SpecID(int), discipline): %complete as a form percentage} — latest week per cell."""
        out = {}
        try:
            cur = self._cc().cursor()
            cur.execute(
                "SELECT SpecID, Discipline, PercentComplete FROM ("
                "  SELECT SpecID, Discipline, PercentComplete,"
                "         ROW_NUMBER() OVER (PARTITION BY SpecID, Discipline ORDER BY YearWeekKey DESC) rn"
                "  FROM Reporting.tblProjectMachineDisciplineProgress"
                "  WHERE ProjectID = ? AND PercentComplete IS NOT NULL) t WHERE rn = 1", pid)
            for s, d, pct in cur.fetchall():
                out[(int(s), str(d))] = _pct_out(pct)
        except Exception:
            pass
        return out

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
        # % complete is captured at the MACHINE × DISCIPLINE cell (the finest budgeted unit).
        cells = payload.get("machine_discipline_progress") or []
        self._save_md_progress(cur, pid, fy, wk, key, by, cells)
        # The per-discipline % the dashboard / scorecard run-out reads is DERIVED (budget-weighted)
        # from those cells and written here, so the PM enters progress once — at the cell.
        self._save_discipline_progress(cur, pid, fy, wk, key, by,
                                       self._derive_discipline_pct(pid, cells))
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

    def _save_md_progress(self, cur, pid, fy, wk, key, by, cells):
        """Upsert per machine×discipline % complete for the current week. cells is a list of
        {spec, discipline, pct}; a blank pct clears that cell (NULL)."""
        for c in cells:
            try:
                spec = int(c.get("spec"))
            except (TypeError, ValueError):
                continue
            disc = str(c.get("discipline") or "").strip()
            if not disc:
                continue
            frac = _frac_pct(c.get("pct"))
            cur.execute("SELECT ProgressID FROM Reporting.tblProjectMachineDisciplineProgress "
                        "WHERE ProjectID = ? AND YearWeekKey = ? AND SpecID = ? AND Discipline = ?",
                        pid, key, spec, disc)
            r = cur.fetchone()
            if r:
                cur.execute("UPDATE Reporting.tblProjectMachineDisciplineProgress "
                            "SET PercentComplete = ?, EnteredBy = ?, CapturedAt = GETDATE() "
                            "WHERE ProgressID = ?", frac, by, int(r[0]))
            else:
                cur.execute("INSERT INTO Reporting.tblProjectMachineDisciplineProgress "
                            "(ProjectID, FiscalYear, WeekNo, YearWeekKey, SpecID, Discipline, "
                            " PercentComplete, EnteredBy, CapturedAt) VALUES (?,?,?,?,?,?,?,?,GETDATE())",
                            pid, fy, wk, key, spec, disc, frac, by)

    def _derive_discipline_pct(self, pid, cells):
        """Roll the cell %s UP to a per-discipline % — COMPLETENESS-weighted (Σ %×weight ÷ Σ weight),
        where a cell's weight is its budget, or its actual hours when the cell is unbudgeted
        (worked but never budgeted) — so off-plan work still counts. Matches the Budgets-page
        roll-up. Written to tblProjectDisciplineProgress (the run-out source) so the PM enters
        progress once, at the cell. Returns {discipline: 0..1 fraction}."""
        agg = self._md_agg(pid)                        # {spec: {disc: [budget, actual]}}
        cell_frac = {}
        for c in cells:
            try:
                spec = int(c.get("spec"))
            except (TypeError, ValueError):
                continue
            disc = str(c.get("discipline") or "").strip()
            f = _frac_pct(c.get("pct"))
            if disc and f is not None:
                cell_frac[(spec, disc)] = f
        num, den = {}, {}
        for spec, dh in agg.items():
            for disc, (b, a) in dh.items():
                f = cell_frac.get((spec, disc))
                w = b if b > 0 else a               # budget, else actual for unbudgeted off-plan work
                if f is None or not w:
                    continue
                num[disc] = num.get(disc, 0.0) + f * w
                den[disc] = den.get(disc, 0.0) + w
        return {disc: round(num[disc] / den[disc], 4) for disc in num if den.get(disc)}

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
    # canned machine × discipline budget/actual per demo project: {spec: {disc: [budget, actual]}}
    # (spec 0 = the Overhead / Contingency group), so the grid + earned/CPI are exercisable.
    _DEMO_GRID = {230219: {
        10: {"Mechanical Engineering": [1800.0, 1700.0], "Manufacturing": [1400.0, 1500.0]},
        20: {"Electrical Engineering": [1200.0, 1100.0], "Manufacturing": [900.0, 950.0]},
        0:  {"Project Management": [300.0, 280.0]},
    }}
    _store = {   # persists across requests within the process; cells: {(spec, disc): 0..1 fraction}
        230219: {"planned_ship": "2026-10-02",
                 "labour_runout": None, "material_runout": None, "rework_threshold": 0.015,
                 "cells": {(10, "Mechanical Engineering"): 0.9, (10, "Manufacturing"): 0.8,
                           (20, "Electrical Engineering"): 0.85, (20, "Manufacturing"): 0.75,
                           (0, "Project Management"): 0.95}},
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
                "machines": []}
        cells = (rec or {}).get("cells", {})
        grid = DemoPlanService._DEMO_GRID.get(pid, {})
        prog = {k: _pct_out(v) for k, v in cells.items()}
        base["machines"] = LivePlanService._grid(grid, prog)
        if rec:
            base.update(planned_ship=rec["planned_ship"],
                        labour_runout=_ratio_out(rec["labour_runout"]),
                        material_runout=_ratio_out(rec["material_runout"]),
                        rework_threshold=_pct_out(rec.get("rework_threshold")))
        return base

    def save_plan(self, payload):
        pid = int(payload["project_id"])
        cells = {}
        for c in (payload.get("machine_discipline_progress") or []):
            try:
                spec = int(c.get("spec"))
            except (TypeError, ValueError):
                continue
            disc = str(c.get("discipline") or "").strip()
            f = _frac_pct(c.get("pct"))
            if disc:
                cells[(spec, disc)] = f
        DemoPlanService._store[pid] = {
            "planned_ship": (payload.get("planned_ship") or None),
            "labour_runout": _ratio_pct(payload.get("labour_runout")),
            "material_runout": _ratio_pct(payload.get("material_runout")),
            "rework_threshold": _thr_in(payload.get("rework_threshold")),
            "cells": cells,
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
