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


def machine_label(spec, desc=None):
    """'Machine 10 — Staircase' (the machine's tblSpec.SDescription next to its number), or just
    'Machine 10' when the description is blank. desc is stripped/none-safe by the caller."""
    d = (desc or "").strip()
    return f"Machine {spec}" + (f" — {d}" if d else "")


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

    def _excluded_ids(self):
        """Projects 'removed from console' (sql/017) — reversible soft-hide. Guarded (empty on
        a missing table) so the plan page still works before the migration is applied."""
        try:
            cur = self._cc().cursor()
            cur.execute("SELECT ProjectID FROM Reporting.tblConsoleProjectExclusion")
            return {int(r[0]) for r in cur.fetchall()}
        except Exception:
            return set()

    def _budgeted_ids(self):
        cur = self._cc().cursor()
        cur.execute("SELECT DISTINCT ProjectID FROM Reporting.vw_Console_BudgetCurrent")
        excl = self._excluded_ids()
        return [int(r[0]) for r in cur.fetchall() if int(r[0]) not in excl]

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
        items = self._wi_agg(pid)              # [{spec, ht, disc, wi, bud, act}] — work-item grain
        rem = self._wi_remaining(pid)          # {(SpecID, HourType): hours remaining to completion}
        base["machines"] = self._grid_wi(items, rem, self._spec_desc(pid))
        if any(it["pct"] is not None
               for m in base["machines"] for d in m["disciplines"] for it in d["items"]):
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

    def _spec_desc(self, pid):
        """{SpecID(int): SDescription} for a project's machines — labels 'Machine 10 — Staircase'."""
        out = {}
        try:
            cur = self._ec().cursor()
            cur.execute("SELECT SpecID, SDescription FROM dbo.tblSpec WHERE ProjectID = ?", pid)
            for spec, desc in cur.fetchall():
                try:
                    out[int(spec)] = (desc or "").strip()
                except (TypeError, ValueError):
                    pass
        except Exception:
            pass
        return out

    def _wi_agg(self, pid):
        """WORK-ITEM aggregation: [{spec, ht, disc, wi, bud, act}] — one entry per machine × HourType.
        Budget = SUM(tblSpecHours.Hours), actual = SUM(vwTimecards.HourTime); FULL OUTER JOIN so every
        item with a budget OR logged hours appears (budgeted + worked-but-unbudgeted). The work item is
        the HourType, labelled by tlkpHourTypes.HourDescription (the ETO estimate's own line names).
        Overhead specs (>= 700) fold into spec 0; same-HourType lines there are summed."""
        rows = []
        try:
            htmap = self._hourtype_map()
            cur = self._ec().cursor()
            cur.execute("""
                WITH bud AS (SELECT SpecID, ISNULL(HourType,0) AS HourType, SUM(Hours) AS Budget
                             FROM dbo.tblSpecHours WHERE ProjectID = ? GROUP BY SpecID, ISNULL(HourType,0)),
                     act AS (SELECT SpecID, ISNULL(HourType,0) AS HourType, SUM(HourTime) AS Actual
                             FROM dbo.vwTimecards WHERE ProjectID = ? GROUP BY SpecID, ISNULL(HourType,0))
                SELECT COALESCE(b.SpecID, a.SpecID)   AS SpecID,
                       COALESCE(b.HourType, a.HourType) AS HourType,
                       ht.HourDescription             AS WorkItem,
                       CAST(ISNULL(b.Budget,0) AS decimal(20,2)) AS Budget,
                       CAST(ISNULL(a.Actual,0) AS decimal(20,2)) AS Actual
                FROM bud b FULL OUTER JOIN act a ON a.SpecID = b.SpecID AND a.HourType = b.HourType
                LEFT JOIN dbo.tlkpHourTypes ht ON ht.HourType = COALESCE(b.HourType, a.HourType)
                WHERE (ISNULL(b.Budget,0) <> 0 OR ISNULL(a.Actual,0) <> 0)
            """, pid, pid)
            for spec, ht, wi, b, a in cur.fetchall():
                try:
                    s = int(spec)
                except (TypeError, ValueError):
                    s = None
                key = 0 if (s is None or s >= _OVERHEAD_SPEC_MIN) else s
                try:
                    hti = int(ht)
                except (TypeError, ValueError):
                    hti = 0
                disc = htmap.get(hti, "Other")
                label = (wi or "").strip() or (f"HourType {hti}" if hti else "Unspecified")
                rows.append({"spec": key, "ht": hti, "disc": disc, "wi": label,
                             "bud": float(b or 0), "act": float(a or 0)})
        except Exception:
            pass
        # fold duplicates (e.g. several overhead specs ≥700 collapsing to spec 0 with the same HourType)
        merged = {}
        for it in rows:
            k = (it["spec"], it["ht"])
            if k in merged:
                merged[k]["bud"] += it["bud"]; merged[k]["act"] += it["act"]
            else:
                merged[k] = it
        return list(merged.values())

    def _wi_remaining(self, pid):
        """{(SpecID(int), HourType(int)): hours remaining} — latest week per work item (the PM input
        the % is derived from). Empty before sql/019 is applied (guarded), so the page still renders."""
        out = {}
        try:
            cur = self._cc().cursor()
            cur.execute(
                "SELECT SpecID, HourType, RemainingHours FROM ("
                "  SELECT SpecID, HourType, RemainingHours,"
                "         ROW_NUMBER() OVER (PARTITION BY SpecID, HourType ORDER BY YearWeekKey DESC) rn"
                "  FROM Reporting.tblProjectWorkItemProgress"
                "  WHERE ProjectID = ? AND RemainingHours IS NOT NULL) t WHERE rn = 1", pid)
            for s, ht, hrs in cur.fetchall():
                out[(int(s), int(ht))] = round(float(hrs), 2) if hrs is not None else None
        except Exception:
            pass
        return out

    @staticmethod
    def _grid(agg, prog, rem=None, descmap=None):
        """Shape the agg + entered progress into the ordered machine grid (real machines
        numeric-sorted, overhead group last). `rem` carries hours-remaining per cell (the PM input);
        `prog` the derived % (for display); `descmap` = {spec: SDescription} for the machine label."""
        rem = rem or {}
        descmap = descmap or {}
        def _mkey(k):
            return (1, 0) if k == 0 else (0, k)
        out = []
        for spec in sorted(agg, key=_mkey):
            dh = agg[spec]
            discs = [{"discipline": d, "budget_hours": round(dh[d][0], 2),
                      "actual_hours": round(dh[d][1], 2), "pct": prog.get((spec, d)),
                      "remaining": rem.get((spec, d))}
                     for d in sorted(dh)]
            out.append({
                "spec": spec,
                "machine": ("Overhead / Contingency" if spec == 0 else machine_label(spec, descmap.get(spec))),
                "overhead": spec == 0,
                "budget_hours": round(sum(v[0] for v in dh.values()), 2),
                "actual_hours": round(sum(v[1] for v in dh.values()), 2),
                "disciplines": discs,
            })
        return out

    @staticmethod
    def _grid_wi(items, rem=None, descmap=None):
        """Shape the WORK-ITEM aggregation into the nested grid machine → discipline → work item.
        `items` = [{spec, ht, disc, wi, bud, act}]; `rem` = {(spec, ht): remaining hrs} (the PM input);
        `descmap` = {spec: SDescription}. Each work item carries budget/actual/remaining/%/earned/CPI;
        discipline and machine rows carry the budget-weighted roll-ups (weight = budget, or actual for
        unbudgeted work). Overhead group (spec 0) sorts last."""
        rem = rem or {}
        descmap = descmap or {}
        by_spec = {}
        for it in items:
            by_spec.setdefault(it["spec"], {}).setdefault(it["disc"], []).append(it)

        def _mkey(k):
            return (1, 0) if k == 0 else (0, k)

        out = []
        for spec in sorted(by_spec, key=_mkey):
            discs_out, m_bud, m_act, m_pairs = [], 0.0, 0.0, []
            for disc in sorted(by_spec[spec]):
                items_out, d_bud, d_act, d_pairs = [], 0.0, 0.0, []
                for it in sorted(by_spec[spec][disc], key=lambda x: (x["wi"] or "").lower()):
                    b, a = round(it["bud"], 2), round(it["act"], 2)
                    r = rem.get((spec, it["ht"]))
                    pct, earned, cpi = _wi_metrics(b, a, r)
                    items_out.append({
                        "hourtype": it["ht"], "work_item": it["wi"],
                        "budget_hours": b, "actual_hours": a, "remaining": r,
                        "pct": _pct_out(pct) if pct is not None else None,
                        "earned_hours": earned, "cpi": cpi, "unbudgeted": not (b > 0)})
                    d_bud += b; d_act += a
                    d_pairs.append((pct, b if b > 0 else a))
                d_pct = _budget_weighted(d_pairs)
                d_earn = round(d_pct * d_bud, 2) if (d_pct is not None and d_bud) else None
                d_cpi = round(d_earn / d_act, 3) if (d_earn is not None and d_act) else None
                discs_out.append({
                    "discipline": disc, "budget_hours": round(d_bud, 2), "actual_hours": round(d_act, 2),
                    "pct": _pct_out(d_pct) if d_pct is not None else None,
                    "earned_hours": d_earn, "cpi": d_cpi, "items": items_out})
                m_bud += d_bud; m_act += d_act
                m_pairs.append((d_pct, d_bud if d_bud > 0 else d_act))
            m_pct = _budget_weighted(m_pairs)
            m_earn = round(m_pct * m_bud, 2) if (m_pct is not None and m_bud) else None
            m_cpi = round(m_earn / m_act, 3) if (m_earn is not None and m_act) else None
            out.append({
                "spec": spec,
                "machine": ("Overhead / Contingency" if spec == 0 else machine_label(spec, descmap.get(spec))),
                "overhead": spec == 0,
                "budget_hours": round(m_bud, 2), "actual_hours": round(m_act, 2),
                "pct": _pct_out(m_pct) if m_pct is not None else None,
                "earned_hours": m_earn, "cpi": m_cpi,
                "disciplines": discs_out})
        return out

    @staticmethod
    def _derive_rollups(items, cell_rem):
        """From the ETO work items + the PM's per-item remaining, derive the roll-up rows that keep the
        legacy tables current: `md` = {(spec, disc): (remaining_sum|None, pct_frac|None)} for the
        machine×discipline table; `disc` = {disc: pct_frac} for the discipline table. Both budget-weighted
        (weight = budget, or actual for unbudgeted), the SAME method the discipline roll-up used before —
        just sourced one level down, from the work items."""
        md_pairs, disc_pairs, md_rem = {}, {}, {}
        for it in items:
            spec, disc = it["spec"], it["disc"]
            b, a = it["bud"], it["act"]
            r = cell_rem.get((spec, it["ht"]))
            pct = _pct_from_remaining(a, r)
            w = b if b > 0 else a
            md_pairs.setdefault((spec, disc), []).append((pct, w))
            disc_pairs.setdefault(disc, []).append((pct, w))
            if r is not None:
                acc = md_rem.setdefault((spec, disc), [0.0, False])
                acc[0] += r; acc[1] = True
        md = {}
        for key, pairs in md_pairs.items():
            acc = md_rem.get(key)
            md[key] = (round(acc[0], 2) if (acc and acc[1]) else None, _budget_weighted(pairs))
        disc = {d: v for d, v in ((d, _budget_weighted(p)) for d, p in disc_pairs.items()) if v is not None}
        return md, disc

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

    def _md_remaining(self, pid):
        """{(SpecID(int), discipline): hours remaining to completion} — latest week per cell.
        The PM input the % is derived from (EAC = actual + remaining)."""
        out = {}
        try:
            cur = self._cc().cursor()
            cur.execute(
                "SELECT SpecID, Discipline, RemainingHours FROM ("
                "  SELECT SpecID, Discipline, RemainingHours,"
                "         ROW_NUMBER() OVER (PARTITION BY SpecID, Discipline ORDER BY YearWeekKey DESC) rn"
                "  FROM Reporting.tblProjectMachineDisciplineProgress"
                "  WHERE ProjectID = ? AND RemainingHours IS NOT NULL) t WHERE rn = 1", pid)
            for s, d, hrs in cur.fetchall():
                out[(int(s), str(d))] = round(float(hrs), 2) if hrs is not None else None
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
        # Progress is captured as HOURS REMAINING TO COMPLETION at the WORK ITEM (machine × HourType)
        # cell — the finest unit ETO budgets. % complete is derived = actual / (actual + remaining).
        # The payload posts every work-item cell in the grid; a blank remaining clears that cell.
        cells = payload.get("machine_discipline_progress") or []
        items = self._wi_agg(pid)              # ETO budget/actual per work item — for %-from-remaining + roll-up
        cell_rem = {}
        for c in cells:
            try:
                spec, ht = int(c.get("spec")), int(c.get("hourtype"))
            except (TypeError, ValueError):
                continue
            cell_rem[(spec, ht)] = _remaining_in(c.get("remaining"))
        self._save_wi_progress(cur, pid, fy, wk, key, by, items, cell_rem)
        # Keep the legacy roll-up tables the dashboard / scorecard / Budgets read: DERIVE the machine×
        # discipline and discipline % (budget-weighted) from the work items and write them, so those
        # surfaces are unchanged and the PM still enters progress once — now at the work item.
        md, disc = self._derive_rollups(items, cell_rem)
        self._save_md_derived(cur, pid, fy, wk, key, by, md)
        self._save_discipline_progress(cur, pid, fy, wk, key, by, disc)
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

    def _save_md_progress(self, cur, pid, fy, wk, key, by, cells, actuals):
        """Upsert per machine×discipline HOURS REMAINING for the current week, plus the % complete
        derived from it (% = actual / (actual + remaining)). cells is a list of {spec, discipline,
        remaining}; a blank remaining clears that cell (RemainingHours + PercentComplete → NULL)."""
        for c in cells:
            try:
                spec = int(c.get("spec"))
            except (TypeError, ValueError):
                continue
            disc = str(c.get("discipline") or "").strip()
            if not disc:
                continue
            remaining = _remaining_in(c.get("remaining"))
            a = (actuals.get(spec, {}).get(disc) or [0.0, 0.0])[1]
            frac = _pct_from_remaining(a, remaining)   # None when remaining blank
            cur.execute("SELECT ProgressID FROM Reporting.tblProjectMachineDisciplineProgress "
                        "WHERE ProjectID = ? AND YearWeekKey = ? AND SpecID = ? AND Discipline = ?",
                        pid, key, spec, disc)
            r = cur.fetchone()
            if r:
                cur.execute("UPDATE Reporting.tblProjectMachineDisciplineProgress "
                            "SET RemainingHours = ?, PercentComplete = ?, EnteredBy = ?, "
                            "CapturedAt = GETDATE() WHERE ProgressID = ?", remaining, frac, by, int(r[0]))
            else:
                cur.execute("INSERT INTO Reporting.tblProjectMachineDisciplineProgress "
                            "(ProjectID, FiscalYear, WeekNo, YearWeekKey, SpecID, Discipline, "
                            " RemainingHours, PercentComplete, EnteredBy, CapturedAt) "
                            "VALUES (?,?,?,?,?,?,?,?,?,GETDATE())",
                            pid, fy, wk, key, spec, disc, remaining, frac, by)

    def _save_wi_progress(self, cur, pid, fy, wk, key, by, items, cell_rem):
        """Upsert the PM's per-work-item HOURS REMAINING for the current week into
        Reporting.tblProjectWorkItemProgress (the new source of truth), plus the derived % complete
        (= actual / (actual + remaining)). `cell_rem` = {(spec, ht): remaining}; a blank clears the cell."""
        act_idx = {(it["spec"], it["ht"]): it["act"] for it in items}
        for (spec, ht), remaining in cell_rem.items():
            frac = _pct_from_remaining(act_idx.get((spec, ht), 0.0), remaining)
            cur.execute("SELECT ProgressID FROM Reporting.tblProjectWorkItemProgress "
                        "WHERE ProjectID = ? AND YearWeekKey = ? AND SpecID = ? AND HourType = ?",
                        pid, key, spec, ht)
            r = cur.fetchone()
            if r:
                cur.execute("UPDATE Reporting.tblProjectWorkItemProgress "
                            "SET RemainingHours = ?, PercentComplete = ?, EnteredBy = ?, "
                            "CapturedAt = GETDATE() WHERE ProgressID = ?", remaining, frac, by, int(r[0]))
            else:
                cur.execute("INSERT INTO Reporting.tblProjectWorkItemProgress "
                            "(ProjectID, FiscalYear, WeekNo, YearWeekKey, SpecID, HourType, "
                            " RemainingHours, PercentComplete, EnteredBy, CapturedAt) "
                            "VALUES (?,?,?,?,?,?,?,?,?,GETDATE())",
                            pid, fy, wk, key, spec, ht, remaining, frac, by)

    def _save_md_derived(self, cur, pid, fy, wk, key, by, md):
        """Write the DERIVED machine × discipline roll-up (from the work items) so the existing
        tblProjectMachineDisciplineProgress consumers are unchanged. `md` = {(spec, disc):
        (remaining_sum|None, pct_frac|None)}."""
        for (spec, disc), (rem_sum, frac) in md.items():
            cur.execute("SELECT ProgressID FROM Reporting.tblProjectMachineDisciplineProgress "
                        "WHERE ProjectID = ? AND YearWeekKey = ? AND SpecID = ? AND Discipline = ?",
                        pid, key, spec, disc)
            r = cur.fetchone()
            if r:
                cur.execute("UPDATE Reporting.tblProjectMachineDisciplineProgress "
                            "SET RemainingHours = ?, PercentComplete = ?, EnteredBy = ?, "
                            "CapturedAt = GETDATE() WHERE ProgressID = ?", rem_sum, frac, by, int(r[0]))
            else:
                cur.execute("INSERT INTO Reporting.tblProjectMachineDisciplineProgress "
                            "(ProjectID, FiscalYear, WeekNo, YearWeekKey, SpecID, Discipline, "
                            " RemainingHours, PercentComplete, EnteredBy, CapturedAt) "
                            "VALUES (?,?,?,?,?,?,?,?,?,GETDATE())",
                            pid, fy, wk, key, spec, disc, rem_sum, frac, by)

    def _derive_discipline_pct(self, cells, actuals):
        """Roll the cells UP to a per-discipline % for the dashboard/scorecard run-out. Each cell's %
        is derived from hours remaining (% = actual / (actual + remaining)); the roll-up is then
        COMPLETENESS-weighted (Σ %×weight ÷ Σ weight, weight = budget, or actual for unbudgeted
        off-plan work) — the SAME method as before, so the run-out shape is unchanged. Returns
        {discipline: 0..1 fraction}."""
        cell_frac = {}
        for c in cells:
            try:
                spec = int(c.get("spec"))
            except (TypeError, ValueError):
                continue
            disc = str(c.get("discipline") or "").strip()
            remaining = _remaining_in(c.get("remaining"))
            if not disc or remaining is None:
                continue
            a = (actuals.get(spec, {}).get(disc) or [0.0, 0.0])[1]
            f = _pct_from_remaining(a, remaining)
            if f is not None:
                cell_frac[(spec, disc)] = f
        num, den = {}, {}
        for spec, dh in actuals.items():
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
    # canned WORK ITEMS per demo project: [{spec, ht, disc, wi, bud, act}] (spec 0 = Overhead group),
    # so the nested machine → discipline → work-item grid + earned/CPI are exercisable without a DB.
    _DEMO_ITEMS = {230219: [
        {"spec": 10, "ht": 11, "disc": "Mechanical Engineering", "wi": "Mechanical Engineering",      "bud": 1080.0, "act": 1005.0},
        {"spec": 10, "ht": 31, "disc": "Manufacturing",          "wi": "Mechanical Assembly",         "bud": 1400.0, "act": 1500.0},
        {"spec": 10, "ht": 32, "disc": "Manufacturing",          "wi": "Fabrication/Welding (IW)",    "bud": 720.0,  "act": 695.0},
        {"spec": 20, "ht": 21, "disc": "Electrical Engineering", "wi": "Electrical Programming",      "bud": 600.0,  "act": 560.0},
        {"spec": 20, "ht": 22, "disc": "Electrical Engineering", "wi": "Electrical Shop Start-Up",    "bud": 240.0,  "act": 30.0},
        {"spec": 20, "ht": 33, "disc": "Manufacturing",          "wi": "Electrical Wiring - Machine", "bud": 480.0,  "act": 470.0},
        {"spec": 20, "ht": 34, "disc": "Manufacturing",          "wi": "Electrical Panel Building",   "bud": 0.0,    "act": 60.0},   # worked-but-unbudgeted
        {"spec": 0,  "ht": 40, "disc": "Project Management",     "wi": "Project Coordination",        "bud": 300.0,  "act": 280.0},
    ]}
    _store = {   # persists across requests within the process; cells: {(spec, ht): remaining hours}
        230219: {"planned_ship": "2026-10-02",
                 "labour_runout": None, "material_runout": None, "rework_threshold": 0.015,
                 "cells": {(10, 11): 120.0, (10, 31): 375.0, (10, 32): 40.0,
                           (20, 21): 95.0, (20, 22): 210.0, (20, 33): 25.0, (20, 34): 40.0,
                           (0, 40): 15.0}},
    }

    def list_projects(self):
        planned = set(DemoPlanService._store)
        try:                                              # share the reversible-exclusion set
            from console_web.pm import DemoPMService
            excl = DemoPMService._excluded
        except Exception:
            excl = set()
        prim = [{"id": pid, "name": _DEMO_NAMES.get(pid, "")}
                for pid in sorted(_DEMO_NAMES) if pid not in excl]
        avail = [{"id": pid, "name": _DEMO_NAMES.get(pid, "")}
                 for pid in sorted(_DEMO_NAMES) if pid in excl]
        return {"budgeted": prim, "available": avail, "planned": sorted(planned)}

    def get_plan(self, project_id):
        pid = int(project_id)
        rec = DemoPlanService._store.get(pid)
        base = {"project_id": pid, "name": _DEMO_NAMES.get(pid, ""), "exists": rec is not None,
                "planned_ship": None, "planned_ship_default": False,
                "labour_runout": None, "material_runout": None, "rework_threshold": None,
                "week": week_key(_dt.date.today())[2],
                "machines": []}
        cells = (rec or {}).get("cells", {})     # {(spec, ht): remaining hours}
        items = DemoPlanService._DEMO_ITEMS.get(pid, [])
        base["machines"] = LivePlanService._grid_wi(items, dict(cells))
        if any(it["pct"] is not None
               for m in base["machines"] for d in m["disciplines"] for it in d["items"]):
            base["exists"] = True
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
                spec, ht = int(c.get("spec")), int(c.get("hourtype"))
            except (TypeError, ValueError):
                continue
            cells[(spec, ht)] = _remaining_in(c.get("remaining"))
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


def _remaining_in(x):
    """Hours-remaining-to-completion input → a non-negative float (blank → None clears the cell)."""
    v = _num(x)
    if v is None:
        return None
    return round(v, 2) if v > 0 else 0.0


def _pct_from_remaining(actual, remaining):
    """% complete (0–1) derived from hours remaining: %C = actual / (actual + remaining), where
    EAC = actual + remaining. Blank remaining → None (nothing declared). 0 remaining → complete."""
    if remaining is None:
        return None
    a = float(actual or 0.0)
    r = max(0.0, float(remaining))
    eac = a + r
    if eac <= 0:
        return 1.0                # 0 remaining and 0 actual → nothing left to do = complete
    return round(a / eac, 4)


def _wi_metrics(bud, act, remaining):
    """(pct, earned_hrs, cpi) for one work item. pct = actual/(actual+remaining); earned = pct×budget;
    CPI = earned÷actual. pct is None until the PM declares a remaining; earned/CPI need a budget/actual."""
    pct = _pct_from_remaining(act, remaining)
    earned = round(pct * bud, 2) if (pct is not None and bud) else None
    cpi = round(earned / act, 3) if (earned is not None and act) else None
    return pct, earned, cpi


def _budget_weighted(pairs):
    """Roll a set of (fraction, weight) up to one budget-weighted fraction: Σ f×w ÷ Σ w. Weight is
    budget (or actual for unbudgeted work). None fractions and zero weights are skipped; None if empty."""
    num = den = 0.0
    for f, w in pairs:
        if f is None or not w:
            continue
        num += f * w
        den += w
    return round(num / den, 4) if den else None


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
