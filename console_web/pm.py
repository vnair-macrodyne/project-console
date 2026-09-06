"""
pm.py — PM write controls for the Project Console: bring a project in + author/edit
its budget. Mirrors the Executive Dashboard 'Budgets (Budget Set-Up)' sheet:

  General:   PO Ship Date · Customer Agreed Ship Date · Late Penalty?
  Materials: Total $
  Hours:     one budget-hours box per Hour Description, grouped under the six disciplines,
             with live per-discipline subtotals + a labour-hours grand total (the sheet's
             'Helpers' roll-ups).

Writes go through the existing versioned DAO (BudgetDAO.upsert_version → tblProjectBudget +
tblProjectBudgetDetail), so every save is a new SCD-2 version stamped with the PM's name.
The Console store is the only write target; ETO stays read-only.

DDL prerequisite (run once) — adds the Late Penalty flag the sheet has but the table lacks:
    ALTER TABLE Reporting.tblProjectBudget ADD LatePenalty bit NULL;
    -- and make sure Reporting.vw_Console_BudgetCurrent surfaces LatePenalty (SELECT * picks it up).
"""
import datetime as _dt

# Canonical Macrodyne grouping (from the Budgets sheet). Used verbatim by the demo and as the
# ordering/fallback for the live crosswalk-driven scaffold so the form matches the workbook.
DISCIPLINE_ORDER = ["Project Management", "Mechanical Engineering", "Electrical Engineering",
                    "Hydraulic Engineering", "Manufacturing", "Other"]

# Machine × discipline breakdown (same rule as the Machine Asset Re-Code report):
# SpecID >= this is overhead/contingency (899 "Management Contingency", 999 rework), not a machine.
_OVERHEAD_SPEC_MIN = 700
_OVERHEAD_LABEL = "Overhead / Contingency"


def _machines_payload(agg):
    """agg = {machine-key: {discipline: [budget_hrs, actual_hrs]}} → ordered list for the UI
    (real machines numeric-sorted, overhead last)."""
    def _mkey(k):
        return (1, 0) if k == _OVERHEAD_LABEL else (0, int(k))
    out = []
    for key in sorted(agg, key=_mkey):
        dh = agg[key]
        discs = [{"discipline": d, "budget_hours": round(dh[d][0], 2), "actual_hours": round(dh[d][1], 2)}
                 for d in sorted(dh)]
        out.append({
            "machine": (_OVERHEAD_LABEL if key == _OVERHEAD_LABEL else f"Machine {key}"),
            "spec": (0 if key == _OVERHEAD_LABEL else int(key)),   # 0 = overhead group (matches plan store)
            "overhead": key == _OVERHEAD_LABEL,
            "budget_hours": round(sum(v[0] for v in dh.values()), 2),
            "actual_hours": round(sum(v[1] for v in dh.values()), 2),
            "disciplines": discs,
        })
    return out


def _earned_cpi(budget, pct, actual):
    """Earned value in HOURS = %complete × budget; CPI = earned ÷ actual (>1 = ahead of the burn,
    <1 = burning faster than earning). Returns (earned, cpi), each None where undefined."""
    if pct is None or budget in (None, 0):
        return None, None
    earned = round(float(pct) * float(budget), 2)
    cpi = round(earned / float(actual), 3) if actual else None
    return earned, cpi


def _enrich_efficacy(disciplines, machines, cell_pct):
    """Attach pct_done / earned_hours / cpi (and actual_hours on disciplines) in place, plus an
    `unbudgeted` flag, from the MACHINE × DISCIPLINE cell %s (cell_pct keyed (SpecID, discipline)
    → 0..1 fraction):

      * each machine×discipline CELL: earned = cell% × cell budget; cpi = earned ÷ cell actual.
        A cell with actual hours but NO budget (`unbudgeted`) is off-plan work — the machine was
        worked but never budgeted (plan changed). Earned/CPI stay None (nothing to earn against);
        it's flagged so the PM can add it to the budget.
      * each machine SUBTOTAL / DISCIPLINE roll-up: %done is a COMPLETENESS-weighted roll-up where a
        cell's weight is its budget, or its actual hours when unbudgeted — so off-plan work still
        counts toward completeness without a rebudget. earned/cpi come only from budgeted hours.
    """
    roll = {}   # discipline -> [Σ(cell%×weight), Σweight, Σactual]
    for m in machines:
        mE = mPW = mW = mB = mA = 0.0
        entered = False
        m_unbudgeted = False
        for d in m.get("disciplines", []):
            b = d.get("budget_hours") or 0.0
            a = d.get("actual_hours") or 0.0
            unb = (b == 0 and a > 0)
            d["unbudgeted"] = unb
            m_unbudgeted = m_unbudgeted or unb
            pct = cell_pct.get((m.get("spec"), d["discipline"]))
            earned, cpi = _earned_cpi(b, pct, a)          # None when unbudgeted (b == 0)
            d["pct_done"] = pct
            d["earned_hours"] = earned
            d["cpi"] = cpi
            w = b if b > 0 else a                          # completeness weight (budget, else actual)
            mB += b; mA += a
            r = roll.setdefault(d["discipline"], [0.0, 0.0, 0.0])
            r[2] += a
            if pct is not None:
                entered = True
                mE += earned or 0.0
                mPW += pct * w; mW += w
                r[0] += pct * w; r[1] += w
        m["unbudgeted"] = m_unbudgeted or (mB == 0 and mA > 0)
        m["pct_done"] = round(mPW / mW, 4) if (entered and mW) else None
        m["earned_hours"] = round(mE, 2) if (entered and mB) else None    # only meaningful with budget
        m["cpi"] = round(mE / mA, 3) if (entered and mB and mA) else None
    for d in disciplines:
        r = roll.get(d["discipline"])
        if not r:
            d["pct_done"] = d["earned_hours"] = d["cpi"] = None
            d["actual_hours"] = 0.0
            continue
        pctw, wsum, act = r
        d["actual_hours"] = round(act, 2)
        pct = round(pctw / wsum, 4) if wsum else None
        d["pct_done"] = pct
        earned, cpi = _earned_cpi(d.get("hours"), pct, act)
        d["earned_hours"] = earned
        d["cpi"] = cpi

SHEET_GROUPING = {
    "Project Management": ["Customer Support", "Management", "Project Coordination", "Training",
                           "Boring Mill Maintenance", "Electrical Procurement", "Housekeeping",
                           "Miscellaneous", "Production Meeting", "Purchasing",
                           "Quality Management / ISO", "Sales"],
    "Mechanical Engineering": ["Mechanical Engineering", "Manuals"],
    "Electrical Engineering": ["Electrical Engineering", "Electrical Programming",
                               "Electrical Shop Start-Up"],
    "Hydraulic Engineering": ["Hydraulic Engineering", "Hydraulic Shop Start-Up"],
    "Manufacturing": ["Electrical Panel Building", "Electrical Wiring - Machine",
                      "Fabrication/Welding (IW)", "Field Service Start-Up/Testing", "Machining (IW)",
                      "Mechanical Assembly", "Mechanical Field Service", "Hydraulic Field Service",
                      "Painting", "Receiving", "Shipping/Dismantle/Prep", "Start-up/Testing",
                      "Travel Field Service", "Tubing/Piping", "Hydraulic Unit Assembly",
                      "Electrical Field Service"],
    "Other": ["Electrical shop (NC) Non-Conformance", "Mechanical shop (NC) Non-Conformance",
              "Engineering (NC) Non-Conformance", "Hydraulic Shop (NC) Non-Conformance"],
}


def _grouped(xwalk):
    """{HourDescription: discipline} → ordered [{discipline, hour_descriptions:[...]}].
    Disciplines in the sheet order (then any extras); Hour Descriptions in sheet order first,
    then any crosswalk extras appended."""
    by_disc = {}
    for hd, disc in xwalk.items():
        by_disc.setdefault(disc or "Other", []).append(hd)
    out, seen = [], set()
    order = DISCIPLINE_ORDER + [d for d in by_disc if d not in DISCIPLINE_ORDER]
    for disc in order:
        hds = by_disc.get(disc, [])
        if not hds:
            continue
        pref = [h for h in SHEET_GROUPING.get(disc, []) if h in hds]
        extra = sorted(h for h in hds if h not in pref)
        out.append({"discipline": disc, "hour_descriptions": pref + extra})
        seen.add(disc)
    return out


def _scaffold_from_sheet():
    return [{"discipline": d, "hour_descriptions": list(SHEET_GROUPING[d])} for d in DISCIPLINE_ORDER]


class PMService:
    def scaffold(self) -> dict:
        raise NotImplementedError

    def list_projects(self) -> dict:
        raise NotImplementedError

    def get_budget(self, project_id) -> dict:
        raise NotImplementedError

    def add_project(self, project_id, entered_by=None) -> dict:
        raise NotImplementedError

    def save_budget(self, payload) -> dict:
        raise NotImplementedError

    def close(self):
        pass


# ─────────────────────────────────────────────────────────────────────────────
# Live — real Console store (write) + ETO (read-only, for the project list/names)
# ─────────────────────────────────────────────────────────────────────────────
class LivePMService(PMService):
    def __init__(self):
        self._console = None
        self._eto = None
        self._xwalk = None

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

    def _crosswalk(self):
        if self._xwalk is None:
            from console.domain.crosswalk import CrosswalkDAO
            self._xwalk = CrosswalkDAO(self._cc()).load_map()
        return self._xwalk

    def _hd_discipline(self):
        return self._crosswalk()

    def _eto_names(self, pids=None):
        """{ProjectID: DisplayName} from ETO (best effort)."""
        try:
            cur = self._ec().cursor()
            if pids:
                ids = ",".join(str(int(p)) for p in pids)
                cur.execute(f"SELECT ProjectID, DisplayName FROM tblProjects WHERE ProjectID IN ({ids})")
            else:
                cur.execute("SELECT ProjectID, DisplayName, PStatus FROM tblProjects")
            out = {}
            for row in cur.fetchall():
                out[int(row[0])] = row[1]
            return out
        except Exception:
            return {}

    def scaffold(self):
        return {"disciplines": _grouped(self._crosswalk())}

    def _budgeted_ids(self):
        cur = self._cc().cursor()
        cur.execute("SELECT DISTINCT ProjectID FROM Reporting.vw_Console_BudgetCurrent")
        return [int(r[0]) for r in cur.fetchall()]

    def list_projects(self):
        budgeted_ids = set(self._budgeted_ids())
        names = self._eto_names()
        budgeted = [{"id": pid, "name": names.get(pid, "")} for pid in sorted(budgeted_ids)]
        available = [{"id": pid, "name": nm} for pid, nm in sorted(names.items())
                     if pid not in budgeted_ids]
        return {"budgeted": budgeted, "available": available}

    def _hourtype_map(self):
        """{HourType: discipline} — store table if seeded, else derived from ETO."""
        from console.domain.hourtype_map import HourTypeDisciplineDAO
        dao = HourTypeDisciplineDAO(self._cc())
        return dao.load_map() or HourTypeDisciplineDAO.derive_from_eto(self._ec())

    def _machine_discipline(self, pid):
        """Machine × discipline hours (budget + actual) for one project, from the SAME ETO tables
        as the Machine Asset Re-Code report — budget = SUM(tblSpecHours.Hours), actual =
        SUM(vwTimecards.HourTime), per SpecID × HourType→discipline — so the machine rows reconcile
        to the per-discipline totals above. Best-effort: returns [] on any error."""
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
            agg = {}
            for spec, ht, b, a in cur.fetchall():
                b = float(b or 0); a = float(a or 0)
                try:
                    s = int(spec)
                except (TypeError, ValueError):
                    s = None
                key = _OVERHEAD_LABEL if (s is None or s >= _OVERHEAD_SPEC_MIN) else s
                try:
                    disc = htmap.get(int(ht), "Other")
                except (TypeError, ValueError):
                    disc = "Other"
                slot = agg.setdefault(key, {}).get(disc, [0.0, 0.0])
                slot[0] += b; slot[1] += a
                agg[key][disc] = slot
            return _machines_payload(agg)
        except Exception:
            return []

    def _md_progress(self, pid):
        """{(SpecID(int), discipline): %complete fraction} — latest week per machine×discipline
        cell, from the plan store (tblProjectMachineDisciplineProgress)."""
        out = {}
        try:
            cur = self._cc().cursor()
            cur.execute(
                "SELECT SpecID, Discipline, PercentComplete FROM ("
                "  SELECT SpecID, Discipline, PercentComplete,"
                "         ROW_NUMBER() OVER (PARTITION BY SpecID, Discipline ORDER BY YearWeekKey DESC) rn"
                "  FROM Reporting.tblProjectMachineDisciplineProgress"
                "  WHERE ProjectID = ? AND PercentComplete IS NOT NULL) t WHERE rn = 1", pid)
            for s, d, p in cur.fetchall():
                if p is not None:
                    out[(int(s), str(d))] = float(p)
        except Exception:
            pass
        return out

    def get_budget(self, project_id):
        """Read-only budget straight from ETO — per-discipline hours + material + total, plus a
        machine × discipline breakdown. Each budgeted unit (discipline AND machine) also carries
        the PM-declared %complete and the CALCULATED earned hours (=%×budget) and CPI (earned÷
        actual), so hours consumed can be squared against hours budgeted. (Budgets are ETO-sourced;
        the manual store is no longer authored here.)"""
        from console.domain.eto_budget import EtoBudgetDAO
        pid = int(project_id)
        name = self._eto_names([pid]).get(pid, "")
        tracked = pid in set(self._budgeted_ids())
        b = EtoBudgetDAO(self._ec(), self._hourtype_map()).get_current(pid)
        if b is None or not b.discipline_hours:
            return {"project_id": pid, "name": name, "exists": False, "tracked": tracked,
                    "source": "ETO", "disciplines": [], "machines": [], "material_total": None,
                    "labour_hours": None}
        dh = b.discipline_hours
        disciplines = [{"discipline": d, "hours": dh[d]} for d in DISCIPLINE_ORDER if dh.get(d)]
        disciplines += [{"discipline": d, "hours": h} for d, h in dh.items()
                        if d not in DISCIPLINE_ORDER and h]
        machines = self._machine_discipline(pid)
        _enrich_efficacy(disciplines, machines, self._md_progress(pid))
        return {"project_id": pid, "name": name, "exists": True, "tracked": tracked,
                "source": "ETO", "read_only": True, "material_total": b.material_budget,
                "labour_hours": b.labour_budget_hours, "disciplines": disciplines,
                "machines": machines}

    def add_project(self, project_id, entered_by=None):
        """Bring an ETO project into the Console: bank its ETO budget as a versioned row
        (source='ETO'), which makes it tracked (dashboard-visible) and starts its history."""
        from console.domain.eto_budget import EtoBudgetDAO
        from console.domain.budget import BudgetDAO
        pid = int(project_id)
        b = EtoBudgetDAO(self._ec(), self._hourtype_map()).get_current(pid)
        if b is None or not b.discipline_hours:
            raise ValueError(f"Project {pid} has no ETO budget to bring in.")
        vid = BudgetDAO(self._cc()).upsert_version(
            b, effective=_dt.date.today(), source="ETO", created_by=(entered_by or "console"))
        return {"ok": True, "project_id": pid, "tracked": True, "version": int(vid),
                "labour_hours": b.labour_budget_hours}

    def save_budget(self, payload):
        from console.domain.budget import Budget, BudgetDAO, BudgetLine
        pid = int(payload["project_id"])
        lines = payload.get("lines") or {}
        xwalk = self._hd_discipline()
        detail, disc_hours = _build_detail(lines, xwalk)
        b = Budget(
            project_id=pid,
            po_ship_date=_as_date(payload.get("po_ship")),
            cust_agreed_ship_date=_as_date(payload.get("cust_agreed_ship")),
            late_penalty=_as_bool(payload.get("late_penalty")),
            material_budget=_num(payload.get("material_total")),
            labour_budget_hours=round(sum(disc_hours.values()), 2) if disc_hours else 0.0,
            discipline_hours=disc_hours,
            detail=detail,
        )
        entered_by = (payload.get("entered_by") or "").strip() or "console-pm"
        vid = BudgetDAO(self._cc()).upsert_version(
            b, effective=_dt.date.today(), source="console-pm", created_by=entered_by)
        return {"ok": True, "project_id": pid, "version": int(vid),
                "labour_hours": b.labour_budget_hours}

    def close(self):
        for c in (self._console, self._eto):
            try:
                if c:
                    c.close()
            except Exception:
                pass


# ─────────────────────────────────────────────────────────────────────────────
# Demo — in-memory (no DB), so the form is fully exercisable with `--demo`
# ─────────────────────────────────────────────────────────────────────────────
_DEMO_NAMES = {230219: "230219 - 5500 Ton Forging Press", 230312: "230312 - 2500T Compression Press",
               240087: "240087 - 650 Ton Trim Press", 250005: "250005 - 15,000 Ton Forging Press",
               240044: "240044 - Spitz"}
_DEMO_XWALK = {hd: disc for disc, hds in SHEET_GROUPING.items() for hd in hds}


class DemoPMService(PMService):
    _store = {   # project_id -> saved budget dict (module-level so it persists across requests)
        230219: {"po_ship": "2026-06-29", "cust_agreed_ship": "2026-06-29", "late_penalty": False,
                 "material_total": 2607952.0,
                 "lines": {"Project Coordination": 260, "Mechanical Engineering": 1640,
                           "Electrical Engineering": 712, "Electrical Programming": 700,
                           "Electrical Shop Start-Up": 320, "Hydraulic Engineering": 412,
                           "Hydraulic Shop Start-Up": 160, "Electrical Panel Building": 800,
                           "Electrical Wiring - Machine": 160, "Fabrication/Welding (IW)": 320}},
    }

    def scaffold(self):
        return {"disciplines": _scaffold_from_sheet()}

    def list_projects(self):
        budgeted_ids = set(DemoPMService._store)
        budgeted = [{"id": pid, "name": _DEMO_NAMES.get(pid, "")} for pid in sorted(budgeted_ids)]
        available = [{"id": pid, "name": nm} for pid, nm in sorted(_DEMO_NAMES.items())
                     if pid not in budgeted_ids]
        return {"budgeted": budgeted, "available": available}

    def get_budget(self, project_id):
        pid = int(project_id)
        rec = DemoPMService._store.get(pid)
        name = _DEMO_NAMES.get(pid, "")
        tracked = pid in DemoPMService._store
        if rec:
            _, disc = _build_detail(rec.get("lines", {}), _DEMO_XWALK)
            mat = rec.get("material_total")
        else:
            # a not-yet-added ETO project: show a placeholder ETO budget so "Add" is exercisable
            disc = {"Project Management": 200, "Mechanical Engineering": 1200,
                    "Electrical Engineering": 1000, "Hydraulic Engineering": 400,
                    "Manufacturing": 3000}
            mat = 1500000.0
        disciplines = [{"discipline": d, "hours": disc[d]} for d in DISCIPLINE_ORDER if disc.get(d)]
        # canned machine × discipline split (two machines 60/40 + a small overhead line), actuals
        # ~5% over budget, so the breakdown reconciles to the discipline totals above.
        agg = {}
        for d, hrs in disc.items():
            for m, share in ((10, 0.6), (20, 0.4)):
                agg.setdefault(m, {})[d] = [round(hrs * share, 2), round(hrs * share * 1.05, 2)]
        if disc:
            agg[_OVERHEAD_LABEL] = {"Project Management": [round(0.05 * sum(disc.values()), 2), 0.0]}
            agg[30] = {"Manufacturing": [0.0, 240.0]}   # worked but never budgeted (plan changed) — flagged
        machines = _machines_payload(agg)
        # canned cell %complete so earned/CPI are exercisable in demo (machine 10 @0.85, 20 @0.70,
        # overhead group @0.95), keyed (spec, discipline)
        cell_pct = {}
        for m in machines:
            base_pct = {10: 0.85, 20: 0.70}.get(m["spec"], 0.95)
            for d in m.get("disciplines", []):
                cell_pct[(m["spec"], d["discipline"])] = base_pct
        _enrich_efficacy(disciplines, machines, cell_pct)
        return {"project_id": pid, "name": name, "exists": bool(disc), "tracked": tracked,
                "source": "ETO", "read_only": True, "material_total": mat,
                "labour_hours": round(sum(disc.values()), 2) if disc else None,
                "disciplines": disciplines, "machines": machines}

    def add_project(self, project_id, entered_by=None):
        pid = int(project_id)
        DemoPMService._store.setdefault(pid, {
            "material_total": 1500000.0,
            "lines": {"Project Coordination": 200, "Mechanical Engineering": 1200,
                      "Electrical Engineering": 1000, "Hydraulic Engineering": 400,
                      "Mechanical Assembly": 3000}})
        return {"ok": True, "project_id": pid, "tracked": True, "version": 1, "labour_hours": 4800}

    def save_budget(self, payload):
        pid = int(payload["project_id"])
        lines = {k: _num(v) for k, v in (payload.get("lines") or {}).items() if _num(v)}
        DemoPMService._store[pid] = {
            "po_ship": payload.get("po_ship") or None,
            "cust_agreed_ship": payload.get("cust_agreed_ship") or None,
            "late_penalty": _as_bool(payload.get("late_penalty")),
            "material_total": _num(payload.get("material_total")),
            "lines": lines,
        }
        _, disc = _build_detail(lines, _DEMO_XWALK)
        return {"ok": True, "project_id": pid, "version": 1,
                "labour_hours": round(sum(disc.values()), 2)}


# ─────────────────────────────────────────────────────────────────────────────
# helpers
# ─────────────────────────────────────────────────────────────────────────────
def _build_detail(lines, xwalk):
    """lines {HourDescription: hours} → (detail list[BudgetLine], discipline_hours dict)."""
    from console.domain.budget import BudgetLine
    detail, disc = [], {}
    for hd, raw in lines.items():
        hrs = _num(raw)
        if hrs is None or hrs == 0:
            continue
        detail.append(BudgetLine(hd, hrs))
        d = xwalk.get(hd, "Other")
        disc[d] = round(disc.get(d, 0.0) + hrs, 2)
    return detail, disc


def _num(x):
    if x is None or x == "":
        return None
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def _as_bool(x):
    if x is None or x == "":
        return None
    if isinstance(x, str):
        return x.strip().lower() in ("y", "yes", "true", "1", "on")
    return bool(x)


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


def make_pm_service(demo=False) -> PMService:
    return DemoPMService() if demo else LivePMService()
