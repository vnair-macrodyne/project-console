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

    def get_budget(self, project_id):
        from console.domain.budget import BudgetDAO
        pid = int(project_id)
        b = BudgetDAO(self._cc()).get_current(pid)
        name = self._eto_names([pid]).get(pid, "")
        if b is None:
            return {"project_id": pid, "name": name, "exists": False, "lines": {},
                    "po_ship": None, "cust_agreed_ship": None, "late_penalty": None,
                    "material_total": None}
        return {
            "project_id": pid, "name": name, "exists": True,
            "po_ship": _iso(b.po_ship_date), "cust_agreed_ship": _iso(b.cust_agreed_ship_date),
            "late_penalty": b.late_penalty, "material_total": b.material_budget,
            "lines": {ln.hour_description: ln.budget_hours for ln in b.detail},
        }

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
        base = {"project_id": pid, "name": _DEMO_NAMES.get(pid, ""), "exists": rec is not None,
                "po_ship": None, "cust_agreed_ship": None, "late_penalty": None,
                "material_total": None, "lines": {}}
        if rec:
            base.update(rec)
        return base

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
