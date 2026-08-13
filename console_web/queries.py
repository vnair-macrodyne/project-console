"""
Named queries for the web interface.

Every query returns a `QueryResult` — a generic titled table (typed columns +
row dicts + optional summary cards). That single shape is what the browser
renders and what the exporters turn into xlsx/pdf, so adding a query never
touches the UI or the exporters.

Two backends implement the same `QueryService` interface:
  * LiveQueryService  — composes the domain DAOs / ProjectFinancialsService
                        against the real Console store + ETO (read-only).
  * DemoQueryService  — canned data (the validated Macrodyne figures) so the
                        UI runs with no database, e.g. `--demo`.
"""
from dataclasses import dataclass, field, asdict

from console.config import TENANT
from console.domain import earned_value as _ev
from console_web import etospec
from console_web import ncspec


def L(key: str) -> str:
    """Tenant display label for a canonical term (e.g. 'discipline' → 'Trade')."""
    return TENANT.term(key)


# ─────────────────────────────────────────────────────────────────────────────
# Generic result shape
# ─────────────────────────────────────────────────────────────────────────────
@dataclass(frozen=True)
class QueryColumn:
    key: str
    label: str
    type: str = "text"        # text | int | hours | money | pct | date | days | id | num
    align: str = "left"       # left | right
    block: str = ""           # group-band label (Executive Dashboard); "" = ungrouped
    wrap: bool = False         # long-text column: wrap within a max-width (others stay 1-line)
    calc: bool = False         # value is calculated live from ETO (rendered italic) vs manual entry


@dataclass
class Card:
    label: str
    value: str
    tone: str = "neutral"     # neutral | good | warn | bad


def _json_clean(rows):
    """Replace NaN / Inf / NaT (which leak from live pandas DataFrames — e.g. a blank text cell
    becomes a float NaN) with None, so every payload is valid JSON. Invalid floats make the
    browser's JSON.parse throw and the screen never renders, so this runs centrally for ALL
    reports rather than per-builder."""
    out = []
    for r in rows:
        d = {}
        for k, v in r.items():
            try:
                if v != v:                                   # True only for NaN / NaT
                    v = None
                elif v in (float("inf"), float("-inf")):     # +/- Infinity
                    v = None
            except (TypeError, ValueError):
                pass
            d[k] = v
        out.append(d)
    return out


@dataclass
class QueryResult:
    query_id: str
    title: str
    columns: list = field(default_factory=list)   # list[QueryColumn]
    rows: list = field(default_factory=list)       # list[dict]
    cards: list = field(default_factory=list)      # list[Card]
    note: str = ""
    export: dict = None       # server-side only: payload for the faithful xlsx writer (never serialized)

    def to_dict(self):
        return {
            "query_id": self.query_id,
            "title": self.title,
            "columns": [asdict(c) for c in self.columns],
            "rows": _json_clean(self.rows),
            "cards": [asdict(c) for c in self.cards],
            "note": self.note,
        }


# ─────────────────────────────────────────────────────────────────────────────
# Query catalogue (drives the UI dropdown)
# ─────────────────────────────────────────────────────────────────────────────
_QUERY_IDS = {"exec", "scorecard", "discipline", "budget_actual", "crosswalk",
              "lab_a", "lab_b", "lab_c", "lab_d", "lab_e", "lab_disc",
              "po_all", "po_status", "po_to_order", "po_exceptions", "po_late",
              "po_delivered", "po_buyer", "item_location", "inventory_value",
              "inventory_by_site", "packing_slip",
              "nc_summary", "nc_costs", "nc_impact", "nc_cause", "nc_discipline",
              "nc_supplier", "nc_detail", "nc_rework", "nc_dashboard"}

# reports that read ETO live and honour the optional date range / view
ETO_REPORT_IDS = {"lab_a", "lab_b", "lab_c", "lab_d", "lab_e", "lab_disc",
                  "po_all", "po_status", "po_to_order", "po_exceptions", "po_late",
                  "po_delivered", "po_buyer",
                  "nc_summary", "nc_costs", "nc_impact", "nc_cause", "nc_discipline",
                  "nc_supplier", "nc_detail"}

# labour reports carry the two-view toggle (This Pay Period / Project Lifetime)
LABOUR_VIEW_IDS = {"lab_a", "lab_b", "lab_c", "lab_d", "lab_e", "lab_disc"}


def catalogue():
    """Built per call so labels reflect the current tenant lexicon. Each entry carries
    a `menu` (top-nav group) and `label` (item); the UI renders menus across the top."""
    proj, disc = L("project"), L("discipline")
    labour, material = L("labour"), L("material")
    return [
        # ── Dashboards ────────────────────────────────────────────────────
        {"id": "exec", "menu": "Dashboards", "label": "Executive",
         "desc": "The full ranked board — schedule, budget, 2-week delta, labour by "
                 f"{disc.lower()} and procurement — one row per {proj.lower()}.",
         "needs_projects": True},
        {"id": "scorecard", "menu": "Dashboards", "label": proj,
         "desc": f"One row per {proj.lower()}: {labour.lower()} & {material.lower()} "
                 f"budget vs actual, schedule, progress, rank.",
         "needs_projects": True},
        {"id": "discipline", "menu": "Dashboards", "label": f"{disc} Financials",
         "desc": f"Per-{disc.lower()} budgeted vs actual hours, consumed % and remaining hours.",
         "needs_projects": True},
        {"id": "budget_actual", "menu": "Dashboards", "label": "Budget vs Actual",
         "desc": f"{labour}-hours and {material.lower()}-$ budget, actual, variance and "
                 f"consumed % per {proj.lower()}.",
         "needs_projects": True},
        {"id": "crosswalk", "menu": "Dashboards", "label": f"{L('crosswalk')} (map)",
         "desc": f"The {L('hour_description')} → {disc.lower()} mapping (reference).",
         "needs_projects": False},
        # ── Labour (the deployed eto-reporting daily suite — A–E) ──────────
        {"id": "lab_a", "menu": labour, "label": "Departmental Project Detail",
         "desc": f"Department → {proj.lower()} → employee: entries, hours, OT and labour cost, "
                 "with per-project and department subtotals.",
         "needs_projects": True},
        {"id": "lab_b", "menu": labour, "label": "Employee Summary",
         "desc": "Department → employee: entries, hours, OT and labour cost, one row per employee.",
         "needs_projects": True},
        {"id": "lab_c", "menu": labour, "label": "Job-Category Summary",
         "desc": "Department → labour category (Hour Description) with % of department hours.",
         "needs_projects": True},
        {"id": "lab_d", "menu": labour, "label": "Employee Job Detail",
         "desc": "Department → employee → job-detail lines (the timecard note per task).",
         "needs_projects": True},
        {"id": "lab_e", "menu": labour, "label": "Project Labour Spend",
         "desc": f"{proj} → department → employee — entries, hours, OT and labour cost.",
         "needs_projects": True},
        {"id": "lab_disc", "menu": labour, "label": f"By {disc}",
         "desc": f"{proj} → {disc.lower()} — headcount, hours, OT and applied-rate cost per "
                 f"{disc.lower()} (Hydraulic, Mechanical, Electrical, PM, Manufacturing, Other), "
                 "using the same crosswalk as the dashboard; rework (task 999) shown as its own "
                 "Re-work line.",
         "needs_projects": True},
        # ── Purchasing (the deployed PO reports) ───────────────────────────
        {"id": "po_all", "menu": "Purchasing", "label": "PO Report",
         "desc": f"All purchases per {proj.lower()} — total purchase value with the received "
                 "(closed) and open portions, and the overdue part. Scoped to orders placed in "
                 "the selected date range.",
         "needs_projects": True},
        {"id": "po_status", "menu": "Purchasing", "label": "PO Status",
         "desc": f"Open purchase-order lines — On Order and Overdue — grouped by {proj.lower()} "
                 "and machine, with an overdue-aging summary and total-purchases context.",
         "needs_projects": True},
        {"id": "po_to_order", "menu": "Purchasing", "label": "Lines to Order",
         "desc": f"Purchase-order lines entered in ETO but not yet issued (not printed or "
                 f"emailed to the vendor) — the still-to-place backlog, grouped by {proj.lower()} "
                 "and machine, with the age of each draft.",
         "needs_projects": True},
        {"id": "po_exceptions", "menu": "Purchasing", "label": "Procurement Exceptions",
         "desc": "Open purchase-order lines that are past their need-by date, one row per item, "
                 "grouped by buyer. A forward-looking, at-risk view.",
         "needs_projects": True},
        {"id": "po_late", "menu": "Purchasing", "label": "Overdue POs",
         "desc": "Open purchase-order lines whose need-by date has passed, grouped by vendor, "
                 "with how many days late. The expediting view — what's still outstanding.",
         "needs_projects": True},
        {"id": "po_delivered", "menu": "Purchasing", "label": "Late Vendors",
         "desc": "Vendor delivery scorecard — items that arrived after their need-by date, "
                 "grouped by vendor, with how many days late. Choose the date range by when the "
                 "orders were placed.",
         "needs_projects": True},
        {"id": "po_buyer", "menu": "Purchasing", "label": "By Buyer",
         "desc": "Purchasing workload by buyer — purchase orders, lines and committed value, "
                 "with the open and overdue portion for each buyer. Scoped to orders placed in "
                 "the selected date range.",
         "needs_projects": True},
        # ── Inventory ─────────────────────────────────────────────────────
        {"id": "item_location", "menu": "Inventory", "label": "Item Location",
         "desc": f"Current on-hand inventory for the items purchased on the selected "
                 f"{proj.lower()}s — by item and location (shared stock, live from ETO).",
         "needs_projects": True},
        {"id": "inventory_value", "menu": "Inventory", "label": "Inventory Value",
         "desc": f"On-hand inventory VALUE for the items purchased on the selected {proj.lower()}s "
                 "— extended value by item and location, from ETO's receipt-layer cost (reconciles "
                 "with material costs), summarised by location.",
         "needs_projects": True},
        {"id": "inventory_by_site", "menu": "Inventory", "label": "Inventory by Site",
         "desc": "Where inventory sits across the sites (Macrodyne 1, Racco, TOC, PS1, Quinton, and "
                 "In-Transit) — on-hand value by location for the whole shared stock pool. "
                 "In-transit stock appears here whenever a site-to-site move is under way.",
         "needs_projects": False},
        # ── Shipping ──────────────────────────────────────────────────────
        {"id": "packing_slip", "menu": "Shipping", "label": "Packing Slips",
         "desc": f"Packing slips for the selected {proj.lower()}s — slip number, type, ship "
                 "date, shipper and ship-to, with the lines shipped (live from ETO).",
         "needs_projects": True},
        # ── Non-Conformance ───────────────────────────────────────────────
        {"id": "nc_summary", "menu": "Non-Conformance", "label": "Summary",
         "desc": "NCR counts and cost by source (where detected), split open vs closed.",
         "needs_projects": True},
        {"id": "nc_costs", "menu": "Non-Conformance", "label": "Costing",
         "desc": "Cost of non-conformance for each NCR — labour, material and total — with its "
                 "source, root cause, discipline, department and supplier.",
         "needs_projects": True},
        {"id": "nc_impact", "menu": "Non-Conformance", "label": "Project Impact",
         "desc": f"One row per {proj.lower()}: open/closed NCRs, cost of non-conformance, and "
                 f"NC cost as a % of {material.lower()} actual spend.",
         "needs_projects": True},
        {"id": "nc_cause", "menu": "Non-Conformance", "label": "By Root Cause",
         "desc": "Cost grouped by root cause — the recurring, expensive types of fault.",
         "needs_projects": True},
        {"id": "nc_discipline", "menu": "Non-Conformance", "label": "By Discipline",
         "desc": f"Cost attributed to a {disc.lower()} and to the responsible department — "
                 "a separate view from the supplier breakdown.",
         "needs_projects": True},
        {"id": "nc_supplier", "menu": "Non-Conformance", "label": "By Supplier",
         "desc": "NCR count and cost broken down by supplier.",
         "needs_projects": True},
        {"id": "nc_detail", "menu": "Non-Conformance", "label": "Details",
         "desc": "Full NCR list — number, status, source, origin, discipline, part, supplier, "
                 "PO, cost, open corrective actions, root cause and CAPA.",
         "needs_projects": True},
        {"id": "nc_rework", "menu": "Non-Conformance", "label": "Rework Labour",
         "desc": f"Rework / non-conformance labour charged to task 999 — hours and applied-rate "
                 f"cost per {proj.lower()} and {disc.lower()} (actual-only; 999 carries no budget). "
                 "The real cost-of-non-conformance labour the per-NCR view can't see.",
         "needs_projects": True},
        {"id": "nc_dashboard", "menu": "Non-Conformance", "label": "NC Dashboard",
         "desc": f"Non-conformance as a % of budget — Labour (rework/999) and Material NC split, "
                 f"per {disc.lower()} and an overall {proj.lower()} view, flagged against the "
                 f"{proj.lower()}'s combined NC threshold (set in the Plan entry).",
         "needs_projects": True},
    ]


def _pct_tone(p):
    if p is None:
        return "neutral"
    if p > 1.0:
        return "bad"
    if p >= 0.9:
        return "warn"
    return "good"


# ─────────────────────────────────────────────────────────────────────────────
# Service interface
# ─────────────────────────────────────────────────────────────────────────────
class QueryService:
    def list_projects(self) -> list:
        raise NotImplementedError

    def run(self, query_id: str, project_ids=None, **kw) -> QueryResult:
        if query_id not in _QUERY_IDS:
            raise ValueError(f"unknown query '{query_id}'")
        return getattr(self, f"_q_{query_id}")(project_ids or [], **kw)


# ── Cross-request perf caches (module-level → shared across request-scoped services) ──────────
# The dashboards are dominated by two things that are FIXED-COST regardless of project scope
# (verified 2026-08-03): the financials build off two ETO rollup views, and the NC-cost rollup
# (vwCostingSummed_ByNC, ~3.5s, one project ≈ all projects). We cache both here on a simple TTL
# — deliberately NOT the data watermark, which moves on every new timecard/PO and would defeat
# the cache in an active shop. The background daemon (which warms the dashboards) keeps these
# warm, so a user click almost never pays the live cost. Staleness is bounded by the TTL and the
# UI already shows an "Updated Xs ago" stamp.
_PERF_TTL = 120                          # seconds a computed result stays fresh
_FIN_CACHE = {}                          # {sorted-pid-tuple: {"at": monotonic, "data": {pid: PF}}}
_NC_CACHE = {"at": 0.0, "data": None}    # whole-portfolio {pid: {"open","cost"}}


# ─────────────────────────────────────────────────────────────────────────────
# Live backend — composes the domain layer
# ─────────────────────────────────────────────────────────────────────────────
class LiveQueryService(QueryService):
    """Reads through the real DAOs. Opens both connections lazily and caches the
    crosswalk + overlay for the life of the request-scoped service instance."""

    def __init__(self):
        self._console = None
        self._eto = None
        self._xwalk = None
        self._overlay = None       # {project_id(str): dict of overlay keys}
        self._htmap = None         # {HourType: discipline} — budget (tblSpecHours)
        self._hdmap = None         # {HourDescription: discipline} — actuals (vwTimecards)

    # -- connection / shared reference data ------------------------------------
    def _console_conn(self):
        if self._console is None:
            from console.infra.connections import console_connection
            self._console = console_connection()
        return self._console

    def _eto_conn(self):
        if self._eto is None:
            from console.infra.connections import eto_connection
            self._eto = eto_connection()
        return self._eto

    def _crosswalk(self):
        if self._xwalk is None:
            from console.domain.crosswalk import CrosswalkDAO
            self._xwalk = CrosswalkDAO(self._console_conn()).load_map()
        return self._xwalk

    def _overlay_map(self):
        if self._overlay is None:
            import console_store
            df = console_store.read_manual_overlay(self._console_conn())
            self._overlay = {}
            if not df.empty:
                for rec in df.to_dict("records"):
                    self._overlay[str(rec.get("ProjectID"))] = rec
        return self._overlay

    def _project_meta(self, project_ids):
        """{project_id: (name, client)} from ETO (vwTimecards) — best-effort."""
        if not project_ids:
            return {}
        ids = ",".join(str(int(p)) for p in project_ids)
        try:
            cur = self._eto_conn().cursor()
            cur.execute(f"SELECT DISTINCT ProjectID, PDescription, Customer FROM dbo.vwTimecards "
                        f"WHERE ProjectID IN ({ids})")
            out = {}
            for r in cur.fetchall():
                pid = int(r[0])
                if pid not in out:
                    out[pid] = (r[1], _clean_client(r[2]))
            return out
        except Exception:
            return {}

    def _hourtype_map(self):
        """{HourType: discipline} for the BUDGET — from the store table if seeded, else
        derived from ETO's tlkpHourTypes + the rule. Cached for the request."""
        if self._htmap is None:
            from console.domain.hourtype_map import HourTypeDisciplineDAO
            dao = HourTypeDisciplineDAO(self._console_conn())
            self._htmap = dao.load_map() or HourTypeDisciplineDAO.derive_from_eto(self._eto_conn())
        return self._htmap

    def _hourdesc_map(self):
        """{HourDescription: discipline} for ACTUALS — same rule as the budget, so the
        per-discipline blocks compare like-for-like. Cached for the request."""
        if self._hdmap is None:
            from console.domain.hourtype_map import HourTypeDisciplineDAO
            self._hdmap = HourTypeDisciplineDAO.derive_description_map_from_eto(self._eto_conn())
        return self._hdmap

    def _rework_by_discipline(self, project_ids):
        """Rework / NC labour (task 999) by project → discipline, actual-only.
        Spec 999 is the project's Non-Conformance / Rework bucket; it carries NO budget
        (tblSpecHours has no 999 rows) and NONE of it is NCR-linked (verified 2026-08-07 —
        which is exactly why the per-NCR NC labour reads $0). We attribute it to disciplines with
        the SAME HourDescription→discipline crosswalk as normal actuals, so it lines up with the
        discipline blocks. Returns {pid: {discipline: [hours, cost]}} (applied-rate cost)."""
        pids = [int(p) for p in project_ids] if project_ids else []
        if not pids:
            return {}
        ids = _ids_sql(pids)
        hd = self._hourdesc_map() or {}
        sql = f"""
            SELECT ProjectID, HourDescription, SUM(HourTime) AS Hours,
                   SUM(LaborCostingValue) AS Cost
            FROM dbo.vwCostingTimecardsSummed_BySpecIDAndHourType
            WHERE SpecID = 999 AND ProjectID IN ({ids})
            GROUP BY ProjectID, HourDescription
        """
        out = {}
        try:
            cur = self._eto_conn().cursor()
            cur.execute(sql)
            for pid, hdesc, hrs, cost in cur.fetchall():
                disc = hd.get(hdesc, "Other")
                slot = out.setdefault(int(pid), {}).setdefault(disc, [0.0, 0.0])
                slot[0] += float(hrs or 0)
                slot[1] += float(cost or 0)
        except Exception:
            return {}
        return out

    def _rework_thresholds(self, project_ids):
        """Per-project rework/NCR threshold (fraction; 0.01 = 1%) from the latest PM/Plan entry
        (Reporting.tblProjectPMEntry). Absent / not-yet-migrated → {} and the caller applies the
        1% default. Set per project on the Plan entry screen."""
        pids = [int(p) for p in project_ids] if project_ids else []
        if not pids:
            return {}
        ids = ",".join(str(p) for p in pids)
        out = {}
        try:
            cur = self._console_conn().cursor()
            cur.execute(
                "SELECT ProjectID, ReworkThreshold FROM ("
                "  SELECT ProjectID, ReworkThreshold,"
                "         ROW_NUMBER() OVER (PARTITION BY ProjectID ORDER BY YearWeekKey DESC) AS rn"
                "  FROM Reporting.tblProjectPMEntry"
                f"  WHERE ReworkThreshold IS NOT NULL AND ProjectID IN ({ids})) t WHERE rn = 1")
            for pid, thr in cur.fetchall():
                if thr is not None:
                    out[int(pid)] = float(thr)
        except Exception:
            return {}
        return out

    def _discipline_progress(self, project_ids):
        """Per-discipline % complete (declared by PM / discipline lead), latest week per
        project+discipline, from Reporting.tblProjectDisciplineProgress. Returns
        {pid: {discipline: 0–1 fraction}}. Absent / not-yet-migrated → {} (callers then have no
        %C, so run-out stays blank rather than guessing). This is the ONE judgement the Carpedia
        run-out engine consumes; everything else is derived."""
        pids = [int(p) for p in project_ids] if project_ids else []
        if not pids:
            return {}
        ids = ",".join(str(p) for p in pids)
        out = {}
        try:
            cur = self._console_conn().cursor()
            cur.execute(
                "SELECT ProjectID, Discipline, PercentComplete FROM ("
                "  SELECT ProjectID, Discipline, PercentComplete,"
                "         ROW_NUMBER() OVER (PARTITION BY ProjectID, Discipline "
                "                            ORDER BY YearWeekKey DESC) AS rn"
                "  FROM Reporting.tblProjectDisciplineProgress"
                f"  WHERE PercentComplete IS NOT NULL AND ProjectID IN ({ids})) t WHERE rn = 1")
            for pid, disc, pct in cur.fetchall():
                if pct is not None:
                    out.setdefault(int(pid), {})[disc] = float(pct)
        except Exception:
            return {}
        return out

    def _financials(self, project_ids):
        # Cross-request TTL cache (module-level _FIN_CACHE), keyed by project-set. The Executive
        # board, Scorecard, Discipline Financials and Budget-vs-Actual all net the SAME financials
        # off two heavy ETO rollup views. Caching here (not just per-instance) means repeat views
        # of a scope — and all four boards for a scope — serve from memory instead of paying the
        # ~2–5s build every request, even when the data watermark churns.
        import time
        key = tuple(sorted(int(p) for p in (project_ids or [])))
        if not key:
            return {}
        now = time.monotonic()
        ent = _FIN_CACHE.get(key)
        if ent and (now - ent["at"]) <= _PERF_TTL:
            return ent["data"]
        from console.domain.discipline_actuals import DisciplineActualsDAO
        from console.domain.project_financials import ProjectFinancialsService
        from console.domain.eto_budget import EtoBudgetDAO
        # BUDGET now comes from ETO's estimate (was the manual store); ACTUALS are
        # classified with the SAME rule (58 controlled hour types) so the per-discipline
        # blocks compare like-for-like. See PROJECT_CONSOLE_ETO_BUDGET_SOURCE_2026-07-27.md.
        bdao = EtoBudgetDAO(self._eto_conn(), self._hourtype_map())
        adao = DisciplineActualsDAO(self._eto_conn(), self._hourdesc_map())
        svc = ProjectFinancialsService(bdao, adao)
        # MATERIAL: the headline actual is Resource Consumption (ETO ActTotalMaterials =
        # purchased + inventory + payables), so the dashboard ties to ETO's "Material Costs
        # Compared" report. Committed Spend (the purchased/costed component) rides alongside
        # as the cash lens. See PROJECT_CONSOLE_MATERIAL_CONSUMPTION_2026-07-31.md.
        mat = self._material_consumption(project_ids)
        cons = {pid: v.get("consumption") for pid, v in mat.items()}
        pids = [int(p) for p in project_ids]
        fin = svc.for_projects(pids, material_actuals=cons)
        for pid, f in fin.items():
            b = mat.get(pid)
            if b:
                f.material_committed = b.get("committed")
                f.material_inventory = b.get("inventory")
                f.material_payables = b.get("payables")
                f.labour_actual_cost = b.get("labour_cost")
                f.sales_price = b.get("sales_price")
                f.sold_margin = b.get("sold_margin")
        _FIN_CACHE[key] = {"at": now, "data": fin}
        if len(_FIN_CACHE) > 64:                       # bound the cache — evict the oldest
            _FIN_CACHE.pop(min(_FIN_CACHE, key=lambda k: _FIN_CACHE[k]["at"]), None)
        return fin

    def close(self):
        for c in (self._console, self._eto):
            try:
                if c:
                    c.close()
            except Exception:
                pass

    # -- interface --------------------------------------------------------------
    def list_projects(self):
        conn = self._console_conn()
        cur = conn.cursor()
        cur.execute("SELECT DISTINCT ProjectID FROM Reporting.vw_Console_BudgetCurrent "
                    "ORDER BY ProjectID")
        ids = [int(r[0]) for r in cur.fetchall()]
        ov = self._overlay_map()
        out = []
        for pid in ids:
            rec = ov.get(str(pid), {})
            out.append({"id": pid, "label": str(pid),
                        "ship": _iso(rec.get("CustAgreedDate") or rec.get("POShipDate"))})
        return out

    # -- queries ----------------------------------------------------------------
    def _q_exec(self, project_ids, **kw):
        fin = self._financials(project_ids)
        ov = self._overlay_map()
        meta = self._project_meta(project_ids)
        nc = self._nc_by_project(project_ids)
        proc = self._procurement_actuals(project_ids)
        tw = self._two_week_actuals(project_ids)
        rw = self._rework_by_discipline(project_ids)
        prog = self._discipline_progress(project_ids)
        committed = self._material_actuals(project_ids)
        rows = []
        for pid in fin:
            f = fin[pid]
            rec = dict(ov.get(str(pid), {}))       # copy — we augment with live actuals
            g = nc.get(pid, {})
            rec["NCOpen"], rec["NCCost"] = g.get("open"), g.get("cost")
            rec.update(proc.get(pid, {}))          # calculated Line Items / LLTP Del. Late
            rec.update(tw.get(pid, {}))            # calculated 2-week labour hrs / material $
            # % Done is the CALCULATED roll-up of per-discipline declared %C; material run-out is
            # computed from committed POs (both Carpedia-aligned). Manual entries are only overrides.
            rollup = _rollup_pct_complete(f.disciplines if f else [], prog.get(pid, {}))
            if rollup is not None:
                rec["PctDone"] = rollup
            rec["MaterialCommittedFull"] = committed.get(pid)
            name, client = meta.get(pid, (None, None))
            # per-discipline % is PLANNED (excludes rework 999), consistent with the scorecard and
            # Discipline Financials — rework is tracked separately as its own % of budget.
            prw = rw.get(pid, {})
            disc_pct = {}
            for d in (f.disciplines if f else []):
                rwh = prw.get(d.discipline, (0.0, 0.0))[0]
                planned = (d.actual_hours or 0.0) - float(rwh)
                disc_pct[d.discipline] = (round(planned / d.budget_hours, 4)
                                          if d.budget_hours else None)
            rows.append(_exec_row(pid, name, client, f, rec, disc_pct))
        return _finalize_exec(rows)

    def _procurement_actuals(self, project_ids):
        """{pid: {'TotalLineItems': n, 'LLTPDelLate': n}} computed live from ETO.

        Only the two figures ETO can support are calculated: total PO line items, and
        long-lead-time parts delivered after their need-by date (using ETO's maintained
        LLT flag). Ordered-late / released-late are NOT derivable — ETO holds no item
        lead time or planned engineering-release date — so those stay as PM entries.
        """
        out = {}
        pids = [int(p) for p in project_ids] if project_ids else []
        if not pids:
            return out
        ids = ",".join(str(p) for p in pids)
        try:  # total PO line items per project
            df = self._df("SELECT ProjectID, COUNT(*) AS n FROM dbo.vwPurchaseOrderDetails "
                          f"WHERE ProjectID IN ({ids}) GROUP BY ProjectID")
            for _, r in df.iterrows():
                out.setdefault(int(r["ProjectID"]), {})["TotalLineItems"] = int(r["n"])
        except Exception:
            pass
        try:  # LLTP delivered-late (needs the maintained item LLT flag)
            import datetime as _dt
            raw = self._df(etospec.query_po_exceptions(True, pids))
            items = etospec.exc_aggregate(etospec.exc_classify(raw, today=_dt.date.today()))
            if items is not None and not items.empty:
                for rec in items.to_dict("records"):
                    if str(rec.get("LLT")) == "LLT" and str(rec.get("DelLate")) == "LATE":
                        pv = rec.get("ProjectID")
                        if pv in (None, ""):
                            continue
                        pid = int(float(pv))
                        d = out.setdefault(pid, {})
                        d["LLTPDelLate"] = d.get("LLTPDelLate", 0) + 1
        except Exception:
            pass
        return out

    def _two_week_actuals(self, project_ids, days=14):
        """{pid: {'LabHrs2wk': hours, 'MatSpend2wk': $CAD}} over the trailing window, live.

        Labour hours from timecards; material = committed PO value (CAD) for POs placed in
        the window. The % Done 2-week delta stays a PM entry — % done isn't recorded in ETO.
        """
        import datetime as _dt
        pids = [int(p) for p in project_ids] if project_ids else []
        if not pids:
            return {}
        ids = ",".join(str(p) for p in pids)
        today = _dt.date.today()
        start = today - _dt.timedelta(days=days - 1)
        out = {}
        try:  # labour hours in the window
            df = self._df(
                "SELECT ProjectID, SUM(HourTime) AS Hrs FROM dbo.vwTimecards "
                f"WHERE ProjectID IN ({ids}) AND TimeDate >= '{start}' AND TimeDate <= '{today}' "
                "GROUP BY ProjectID")
            for _, r in df.iterrows():
                out.setdefault(int(r["ProjectID"]), {})["LabHrs2wk"] = round(float(r["Hrs"] or 0), 1)
        except Exception:
            pass
        try:  # material committed (POs placed) in the window, CAD
            rate = "CASE WHEN poh.PurchaseCurrRate > 0 THEN poh.PurchaseCurrRate ELSE 1 END"
            df = self._df(
                "SELECT pod.ProjectID AS ProjectID, "
                f"SUM(pod.ExtendedPrice * {rate}) AS Spend "
                "FROM dbo.vwPurchaseOrderDetails pod "
                "JOIN dbo.vwPurchaseOrderHeader poh ON poh.PurchaseOrderID = pod.PurchaseOrderID "
                f"WHERE pod.ProjectID IN ({ids}) AND poh.PurchaseActive = 1 "
                f"AND poh.PurchaseDate >= '{start}' AND poh.PurchaseDate <= '{today}' "
                "GROUP BY pod.ProjectID")
            for _, r in df.iterrows():
                out.setdefault(int(r["ProjectID"]), {})["MatSpend2wk"] = round(float(r["Spend"] or 0), 2)
        except Exception:
            pass
        return out

    def _q_scorecard(self, project_ids, **kw):
        fin = self._financials(project_ids)
        ov = self._overlay_map()
        nc = self._nc_by_project(project_ids)
        rw = self._rework_by_discipline(project_ids)
        thr = self._rework_thresholds(project_ids)
        prog = self._discipline_progress(project_ids)
        committed = self._material_actuals(project_ids)
        rows = []
        for pid in sorted(fin):
            f = fin[pid]
            rec = dict(ov.get(str(pid), {}))
            g = nc.get(pid, {})
            rec["NCOpen"], rec["NCCost"] = g.get("open"), g.get("cost")
            rec["Rework"] = round(sum(h for h, _ in rw.get(pid, {}).values()), 2) or None
            rec["ReworkThreshold"] = thr.get(pid)     # per-project; _scorecard_row defaults to 1%
            # % complete is now the CALCULATED roll-up of per-discipline declared %C; the overlay's
            # RunoutLabour/RunoutMaterial become optional overrides. (Manual RunoutLabour → % override.)
            rollup = _rollup_pct_complete(f.disciplines, prog.get(pid, {}))
            if rollup is not None:
                rec["PctDone"] = rollup
            rec["MaterialCommittedFull"] = committed.get(pid)
            rec["RunoutLabourPct"] = rec.pop("RunoutLabour", None)   # treat old manual as % override
            rows.append(_scorecard_row(pid, f, rec))
        return _scorecard_result(rows)

    def _q_discipline(self, project_ids, **kw):
        fin = self._financials(project_ids)
        rw = self._rework_by_discipline(project_ids)
        prog = self._discipline_progress(project_ids)
        rows = []
        for pid in sorted(fin):
            prw = rw.get(pid, {})
            pprog = prog.get(pid, {})
            for d in fin[pid].disciplines:
                rwh, rwc = prw.get(d.discipline, (0.0, 0.0))
                # Consumed % is PLANNED work only — rework(999) is pulled OUT of the actual and
                # shown separately, both in hours/$ and as its own % of budget (Vijay 2026-08-07).
                planned = round((d.actual_hours or 0.0) - float(rwh), 2)
                cons = round(planned / d.budget_hours, 4) if d.budget_hours else None
                rem = round(d.budget_hours - planned, 2) if d.budget_hours is not None else None
                rwpct = round(float(rwh) / d.budget_hours, 4) if d.budget_hours else None
                # Run-out uses TOTAL actual hours (incl. rework — real spend) ÷ declared %C.
                pct = pprog.get(d.discipline)
                ro = _ev.compute(d.budget_hours, d.actual_hours, pct)
                rows.append({"ProjectID": pid, "Discipline": d.discipline,
                             "BudgetHours": d.budget_hours, "ActualHours": planned,
                             "ConsumedPct": cons, "RemainingHours": rem,
                             "PctComplete": pct,
                             "RunoutHours": ro.eac, "RunoutPct": ro.runout_pct,
                             "ReworkHours": round(float(rwh), 2) or None,
                             "ReworkPct": rwpct,
                             "ReworkCost": round(float(rwc), 2) or None})
        return _discipline_result(rows)

    def _q_budget_actual(self, project_ids, **kw):
        fin = self._financials(project_ids)
        rows = [_budget_actual_row(pid, fin[pid]) for pid in sorted(fin)]
        return _budget_actual_result(rows)

    def _q_crosswalk(self, project_ids, **kw):
        rows = [{"HourDescription": hd, "Discipline": disc}
                for hd, disc in sorted(self._crosswalk().items())]
        return _crosswalk_result(rows)

    # -- Labour + Purchasing (the deployed eto-reporting engine, read from ETO) --
    def _df(self, sql):
        import pandas as pd
        cur = self._eto_conn().cursor()
        cur.execute(sql)
        cols = [d[0] for d in cur.description]
        return pd.DataFrame([tuple(r) for r in cur.fetchall()], columns=cols)

    def _labour(self, project_ids, report_id, date_from, date_to):
        import datetime as _dt
        dto = _as_date(date_to) or _dt.date.today()
        dfrom = _as_date(date_from)      # None = Start of Project to Date (no lower bound)
        pids = [int(p) for p in project_ids] if project_ids else None
        df = self._df(etospec.query_daily_labour(dfrom, dto, pids))
        if report_id == "lab_disc":
            df = _labour_add_discipline(df, self._hourdesc_map())
        return _spec_labour_result(report_id, df, _window_label(dfrom, dto))

    def _q_lab_disc(self, project_ids, date_from=None, date_to=None, **kw):
        return self._labour(project_ids, "lab_disc", date_from, date_to)

    def _q_lab_a(self, project_ids, date_from=None, date_to=None, **kw):
        return self._labour(project_ids, "lab_a", date_from, date_to)

    def _q_lab_b(self, project_ids, date_from=None, date_to=None, **kw):
        return self._labour(project_ids, "lab_b", date_from, date_to)

    def _q_lab_c(self, project_ids, date_from=None, date_to=None, **kw):
        return self._labour(project_ids, "lab_c", date_from, date_to)

    def _q_lab_d(self, project_ids, date_from=None, date_to=None, **kw):
        return self._labour(project_ids, "lab_d", date_from, date_to)

    def _q_lab_e(self, project_ids, date_from=None, date_to=None, **kw):
        return self._labour(project_ids, "lab_e", date_from, date_to)

    def _po_totals(self, pids, dfrom, dto):
        """Grand purchase totals (closed + open) across the selection, for context/cards."""
        try:
            df = self._df(etospec.query_po_totals_by_project(pids, dfrom, dto))
            if df is None or df.empty:
                return None
            return {k: float(df[k].fillna(0).sum())
                    for k in ("TotalPurchases", "ReceivedValue", "OpenValue", "OverdueValue")}
        except Exception:
            return None

    def _q_po_all(self, project_ids, date_from=None, date_to=None, **kw):
        pids = [int(p) for p in project_ids] if project_ids else None
        dfrom, dto = _as_date(date_from), _as_date(date_to)
        df = self._df(etospec.query_po_totals_by_project(pids, dfrom, dto))
        rows = [] if df is None or df.empty else df.to_dict("records")
        return _po_all_result(rows, _po_window_label(dfrom, dto))

    def _q_po_status(self, project_ids, date_from=None, date_to=None, **kw):
        import datetime as _dt
        pids = [int(p) for p in project_ids] if project_ids else None
        dfrom, dto = _as_date(date_from), _as_date(date_to)
        raw = self._df(etospec.query_po_status_open(pids, dfrom, dto))
        as_of = _dt.date.today()
        pdf = etospec.po_prep(raw, today=as_of)
        result = _spec_po_status_result(pdf, f"As at {as_of:%b %d, %Y}{_po_window_label(dfrom, dto)}")
        t = self._po_totals(pids, dfrom, dto)     # total purchases (closed + open) context
        if t:
            result.cards.append(Card("Total purchases", _fmt_money2(t["TotalPurchases"])))
            result.cards.append(Card("Received (closed)", _fmt_money2(t["ReceivedValue"])))
        return result

    def _q_po_to_order(self, project_ids, date_from=None, date_to=None, **kw):
        """Draft PO lines — entered in ETO but not yet issued (not printed AND not emailed
        to the vendor). Verified 2026-08-03: PurchasePrinted/PurchaseEmailed are the send
        flags; neither PurchaseDate nor PurchaseActive distinguishes drafts. See
        PROJECT_CONSOLE_PO_TO_ORDER_2026-08-03.md."""
        pids = [int(p) for p in project_ids] if project_ids else None
        dfrom, dto = _as_date(date_from), _as_date(date_to)
        proj = f" AND pod.ProjectID IN ({_ids_sql(pids)})" if pids else ""
        dtc = ""
        if dfrom:
            dtc += f" AND CAST(poh.PurchaseDate AS date) >= '{dfrom}'"
        if dto:
            dtc += f" AND CAST(poh.PurchaseDate AS date) <= '{dto}'"
        rate = "CASE WHEN poh.PurchaseCurrRate > 0 THEN poh.PurchaseCurrRate ELSE 1 END"
        sql = f"""
        SELECT pod.ProjectID AS ProjectID, p.DisplayName AS JobName, pcust.CName AS Customer,
               pod.SpecID AS MachineCode, pod.ItemID AS Item, pod.ItemDescription AS Description,
               poh.PurchaseOrderID AS PO, poh.CName AS Supplier,
               COALESCE(bu.EmpLastName + ', ' + bu.EmpFirstName,
                        CAST(poh.BuyerID AS varchar(20))) AS Buyer,
               poh.PurchaseCurr AS Curr, pod.PurchaseQty AS Qty, pod.PurchasePrice AS Price,
               CAST(pod.ExtendedPrice * {rate} AS decimal(20,2)) AS ExtValueCAD,
               CAST(pod.DateRequired AS date) AS Required, CAST(poh.PurchaseDate AS date) AS Entered,
               DATEDIFF(day, poh.PurchaseDate, GETDATE()) AS AgeDays
        FROM vwPurchaseOrderHeader poh
        JOIN vwPurchaseOrderDetails pod ON pod.PurchaseOrderID = poh.PurchaseOrderID
        LEFT JOIN tblProjects p     ON p.ProjectID = pod.ProjectID
        LEFT JOIN tblCompany  pcust ON pcust.CompanyID = p.CompanyID
        LEFT JOIN tblEmployee bu    ON bu.EmployeeID = poh.BuyerID
        WHERE poh.PurchaseActive = 1 AND poh.PurchasePrinted = 0 AND poh.PurchaseEmailed = 0
          AND ISNULL(pod.Archived, 0) = 0{proj}{dtc}
        ORDER BY pod.ProjectID, pod.SpecID, poh.PurchaseOrderID, pod.ItemID
        """
        return _po_to_order_result(self._df(sql), _po_window_label(dfrom, dto))

    def _q_po_exceptions(self, project_ids, date_from=None, date_to=None, **kw):
        import datetime as _dt
        pids = [int(p) for p in project_ids] if project_ids else None
        dfrom, dto = _as_date(date_from), _as_date(date_to)
        enriched = True
        try:
            raw = self._df(etospec.query_po_exceptions(True, pids, dfrom, dto))
        except Exception:
            enriched = False
            raw = self._df(etospec.query_po_exceptions(False, pids, dfrom, dto))
        as_of = _dt.date.today()
        items = etospec.exc_detail(raw, today=as_of)
        return _spec_po_exc_result(items, f"As at {as_of:%b %d, %Y}{_po_window_label(dfrom, dto)}", enriched)

    def _q_po_late(self, project_ids, date_from=None, date_to=None, **kw):
        import datetime as _dt
        pids = [int(p) for p in project_ids] if project_ids else None
        dfrom, dto = _as_date(date_from), _as_date(date_to)
        df = self._df(etospec.query_late_vendors(pids, dfrom, dto))
        return _spec_late_result(df, f"As at {_dt.date.today():%b %d, %Y}{_po_window_label(dfrom, dto)}")

    def _q_po_buyer(self, project_ids, date_from=None, date_to=None, **kw):
        pids = [int(p) for p in project_ids] if project_ids else None
        dfrom, dto = _as_date(date_from), _as_date(date_to)
        df = self._df(etospec.query_po_by_buyer(pids, dfrom, dto))
        rows = [] if df is None or df.empty else df.to_dict("records")
        return _po_buyer_result(rows, _po_window_label(dfrom, dto))

    def _q_item_location(self, project_ids, **kw):
        """On-hand inventory (item + location) for the items purchased on the selected projects.
        Inventory is a SHARED stock pool in ETO — no ProjectID — so we scope by the items on the
        projects' PO lines and read current on-hand from vwInventory (location + bin + qty already
        resolved). Verified 2026-08-03. See PROJECT_CONSOLE_ITEM_LOCATION_2026-08-03.md."""
        pids = [int(p) for p in project_ids] if project_ids else []
        if not pids:
            return _item_location_result(None)
        ids = _ids_sql(pids)
        sql = f"""
        SELECT pi.ProjectID AS ProjectID, p.DisplayName AS JobName,
               inv.ItemCompanyID AS ItemNo, inv.ItemDescription AS Description,
               inv.LocationName AS Location, inv.BinLabel AS Bin,
               inv.QtyOnHand AS OnHand, inv.QtyMinRequired AS MinReq
        FROM (SELECT DISTINCT ProjectID, ItemID FROM dbo.vwPurchaseOrderDetails
              WHERE ProjectID IN ({ids}) AND ItemID IS NOT NULL) pi
        JOIN dbo.vwInventory inv ON inv.ItemID = pi.ItemID
        LEFT JOIN dbo.tblProjects p ON p.ProjectID = pi.ProjectID
        WHERE inv.QtyOnHand > 0
        ORDER BY pi.ProjectID, inv.ItemCompanyID, inv.LocationName
        """
        return _item_location_result(self._df(sql))

    def _q_inventory_value(self, project_ids, **kw):
        """On-hand inventory VALUE (item + location) for the items purchased on the selected
        projects. Value = SUM over receipt layers of (InventoryDetailQty × PurchasePrice) from
        tblInventoryDetails — ETO's own UOM-consistent carrying cost, the SAME basis it consumes
        into vwCostingSummed_ByProjectID.TotalInventoryPulls, so it reconciles with material costs.
        On-hand quantity is the vwInventory snapshot (shared stock, scoped by the projects' PO
        items — same as Item Location). Made-to-project / adjusted stock without a purchase-price
        layer shows quantity but no purchased-material value. Verified 2026-08-06; see
        PROJECT_CONSOLE_SHIPPING_INVENTORY_BUILD_2026-08-06.md."""
        pids = [int(p) for p in project_ids] if project_ids else []
        if not pids:
            return _inventory_value_result(None)
        ids = _ids_sql(pids)
        sql = f"""
        SELECT pi.ProjectID AS ProjectID, p.DisplayName AS JobName,
               inv.ItemCompanyID AS ItemNo, inv.ItemDescription AS Description,
               inv.LocationName AS Location, inv.BinLabel AS Bin,
               inv.QtyOnHand AS OnHand, lay.ExtValue AS ExtValue, lay.LayerQty AS LayerQty
        FROM (SELECT DISTINCT ProjectID, ItemID FROM dbo.vwPurchaseOrderDetails
              WHERE ProjectID IN ({ids}) AND ItemID IS NOT NULL) pi
        JOIN dbo.vwInventory inv ON inv.ItemID = pi.ItemID
        LEFT JOIN (SELECT ItemID, InventoryLocation,
                          SUM(CAST(InventoryDetailQty AS float) * CAST(PurchasePrice AS float)) AS ExtValue,
                          SUM(CAST(InventoryDetailQty AS float)) AS LayerQty
                   FROM dbo.tblInventoryDetails GROUP BY ItemID, InventoryLocation) lay
          ON lay.ItemID = inv.ItemID AND lay.InventoryLocation = inv.InventoryLocation
        LEFT JOIN dbo.tblProjects p ON p.ProjectID = pi.ProjectID
        WHERE inv.QtyOnHand > 0
        ORDER BY pi.ProjectID, inv.LocationName, inv.ItemCompanyID
        """
        return _inventory_value_result(self._df(sql))

    def _q_inventory_by_site(self, project_ids, **kw):
        """Portfolio-wide on-hand VALUE by location/site — the whole shared stock pool, NOT scoped
        to projects (inventory is shared; this answers 'where does our stock sit and what's it
        worth'). Value = tblInventoryDetails layer cost (same basis as Inventory Value). In-transit
        locations appear as their own rows when a site-to-site move is under way. Verified
        2026-08-06; see PROJECT_CONSOLE_SHIPPING_INVENTORY_BUILD_2026-08-06.md."""
        sql = """
        SELECT inv.LocationName AS Location,
               COUNT(*) AS Lines, COUNT(DISTINCT inv.ItemID) AS Items,
               SUM(lay.ExtValue) AS Value,
               SUM(CASE WHEN lay.ExtValue IS NULL THEN 1 ELSE 0 END) AS Uncosted
        FROM dbo.vwInventory inv
        LEFT JOIN (SELECT ItemID, InventoryLocation,
                          SUM(CAST(InventoryDetailQty AS float) * CAST(PurchasePrice AS float)) AS ExtValue
                   FROM dbo.tblInventoryDetails GROUP BY ItemID, InventoryLocation) lay
          ON lay.ItemID = inv.ItemID AND lay.InventoryLocation = inv.InventoryLocation
        WHERE inv.QtyOnHand > 0
        GROUP BY inv.LocationName
        ORDER BY SUM(lay.ExtValue) DESC
        """
        return _inventory_by_site_result(self._df(sql))

    def _q_packing_slip(self, project_ids, **kw):
        """Packing slips for the selected projects — header (number, type, dates, shipper, ship-to,
        shipped/packed status) plus the lines shipped. ETO's own fully-joined shipping view
        vwPackingSlips_SearchResults is directly project-scoped (ProjectID on each detail line), so
        no manual header⋈detail join is needed. Verified 2026-08-06 — see
        PROJECT_CONSOLE_INVENTORY_VALUE_2026-08-06.md."""
        pids = [int(p) for p in project_ids] if project_ids else []
        if not pids:
            return _packing_slip_result(None)
        ids = _ids_sql(pids)
        sql = f"""
        SELECT ps.ProjectID AS ProjectID, p.DisplayName AS JobName,
               ps.PackingSlipID AS PackingSlipID, ps.PackingSlipNumber AS SlipNo,
               ps.PackingSlipTypeName AS SlipType, ps.CreatedDate AS CreatedDate,
               ps.ShippedDate AS ShippedDate, ps.ShipperName AS Shipper,
               ps.ShipFromCompany AS ShipFrom, ps.ShipFromSCity AS FromCity,
               ps.ShipToCompany AS ShipTo, ps.ShipToSCity AS ToCity,
               ps.Shipped AS Shipped, ps.Packed AS Packed,
               ps.SpecID AS Machine, ps.ItemCompanyID AS ItemNo,
               ps.ItemDescription AS Description, ps.CategoryDescription AS Category,
               ps.Quantity AS Qty
        FROM dbo.vwPackingSlips_SearchResults ps
        LEFT JOIN dbo.tblProjects p ON p.ProjectID = ps.ProjectID
        WHERE ps.ProjectID IN ({ids})
        ORDER BY ps.ProjectID, ps.ShippedDate DESC, ps.CreatedDate DESC,
                 ps.PackingSlipID DESC, ps.ItemCompanyID
        """
        return _packing_slip_result(self._df(sql))

    def _q_po_delivered(self, project_ids, date_from=None, date_to=None, **kw):
        pids = [int(p) for p in project_ids] if project_ids else None
        dfrom, dto = _as_date(date_from), _as_date(date_to)
        try:
            df = self._df(etospec.query_delivered_late(pids, dfrom, dto))
        except Exception:
            # no direct SELECT on vwReceiverLogSummed → run ETO's own proc, filter client-side
            df = self._exec_delivered(pids, dfrom, dto)
        return _spec_delivered_result(df, _delivered_label(dfrom, dto))

    def _exec_delivered(self, pids, dfrom, dto):
        import datetime as _dt, pandas as pd
        lower = str(dfrom) if dfrom else "2015-01-01"
        upper = str(dto) if dto else "2027-12-31"
        cur = self._eto_conn().cursor()
        cur.execute(etospec.EXEC_LATE_VENDORS, lower, upper)
        cols = [d[0] for d in cur.description]
        recs = []
        want = set(pids) if pids else None
        for row in cur.fetchall():
            d = dict(zip(cols, row))
            if want is not None and d.get("ProjectID") not in want:
                continue
            recs.append({v: d.get(k) for k, v in etospec.EXEC_COLMAP.items()})
        return pd.DataFrame(recs, columns=list(etospec.EXEC_COLMAP.values()))

    def _nc_rows(self, project_ids, date_from, date_to):
        return _live_nc_cost_rows(self._eto_conn().cursor(), project_ids, date_from, date_to)

    def _material_actuals(self, project_ids):
        """{pid: committed material $ (CAD)} derived live from purchase orders.

        Committed (ordered) = the value of every active PO line for the project, converted
        to Canadian dollars at the rate stored on each PO (an invalid/zero rate is treated
        as 1.0). Because it sums ALL orders — including the extra and rework POs raised off
        late deliveries and non-conformances — it captures the true committed material
        spend. Falls back to the manual PM entry only if the purchase data can't be read.
        """
        pids = [int(p) for p in project_ids] if project_ids else []
        if not pids:
            return {}
        ids = ",".join(str(p) for p in pids)
        try:
            df = self._df(
                "SELECT pod.ProjectID AS ProjectID, "
                "SUM(pod.ExtendedPrice * CASE WHEN poh.PurchaseCurrRate > 0 "
                "     THEN poh.PurchaseCurrRate ELSE 1 END) AS Committed "
                "FROM dbo.vwPurchaseOrderDetails pod "
                "JOIN dbo.vwPurchaseOrderHeader poh "
                "     ON poh.PurchaseOrderID = pod.PurchaseOrderID "
                f"WHERE pod.ProjectID IN ({ids}) AND poh.PurchaseActive = 1 "
                "GROUP BY pod.ProjectID")
            return {int(r["ProjectID"]): round(float(r["Committed"] or 0), 2)
                    for _, r in df.iterrows()}
        except Exception:
            keep = set(pids)
            return {int(pid): _num(rec.get("MatActual"))
                    for pid, rec in self._overlay_map().items()
                    if str(pid).isdigit() and int(pid) in keep}

    def _material_consumption(self, project_ids):
        """{pid: {'consumption','committed','inventory','payables','labour_cost','sales_price',
        'sold_margin'}} live from ETO's project costing rollup — dbo.vwCostingSummed_ByProjectID.

        Resource Consumption = TotalMaterials = TotalPurchasedMaterials + TotalInventoryPulls
        + TotalExtraCosts. This equals vwProjectActualsVSEstimates.ActTotalMaterials and ties to
        ETO's "Material Costs Compared" report to the penny (verified project 240154:
        2,870,408.22 + 32,996.87 + 54.00 = 2,903,459.09). Committed Spend = the purchased
        (costed) component only — the cash-out-the-door lens. The same rollup carries the priced
        labour actual (TotalLabor), the sold price (SalesPrice) and the margin booked at sale
        (ProjectMargin) — the pieces the earning-at-completion view nets. Where a project has no
        costing row (or the view can't be read) we fall back to the committed PO value so a tile
        never blanks (the earning fields stay None → the earning columns simply don't render).
        """
        pids = [int(p) for p in project_ids] if project_ids else []
        if not pids:
            return {}
        ids = ",".join(str(p) for p in pids)
        out = {}
        try:
            df = self._df(
                "SELECT ProjectID, TotalPurchasedMaterials AS Committed, "
                "TotalInventoryPulls AS Inventory, TotalExtraCosts AS Payables, "
                "TotalMaterials AS Consumption, TotalLabor AS LabourCost, "
                "SalesPrice, ProjectMargin AS SoldMargin "
                f"FROM dbo.vwCostingSummed_ByProjectID WHERE ProjectID IN ({ids})")
            for _, r in df.iterrows():
                out[int(r["ProjectID"])] = {
                    "committed": round(float(r["Committed"] or 0), 2),
                    "inventory": round(float(r["Inventory"] or 0), 2),
                    "payables": round(float(r["Payables"] or 0), 2),
                    "consumption": round(float(r["Consumption"] or 0), 2),
                    "labour_cost": _opt_money(r["LabourCost"]),
                    "sales_price": _opt_money(r["SalesPrice"]),
                    "sold_margin": _opt_frac(r["SoldMargin"]),
                }
        except Exception:
            out = {}
        missing = [p for p in pids if p not in out]     # fall back to committed PO value
        if missing:
            po = self._material_actuals(missing)
            for p in missing:
                v = po.get(p)
                out[p] = {"committed": v, "inventory": None, "payables": None, "consumption": v,
                          "labour_cost": None, "sales_price": None, "sold_margin": None}
        return out

    def _nc_by_project(self, project_ids):
        """{pid: {'open': n, 'cost': $}} for the dashboard NC-actuals columns.

        The NC-cost rollup is fixed-cost regardless of scope, so compute the WHOLE portfolio once,
        cache it on the module TTL, and filter to the requested scope instantly. On a refresh
        failure we keep serving the last good copy rather than blanking the columns."""
        import time
        if not project_ids:
            return {}
        keep = {int(p) for p in project_ids}
        global _NC_CACHE
        now = time.monotonic()
        if _NC_CACHE.get("data") is None or (now - _NC_CACHE.get("at", 0.0)) > _PERF_TTL:
            try:
                rows = _live_nc_cost_rows(self._eto_conn().cursor(), None, None, None)  # whole portfolio
                _NC_CACHE = {"at": now, "data": ncspec.by_project_totals(rows)}
            except Exception:
                if _NC_CACHE.get("data") is None:
                    return {}
        return {int(pid): g for pid, g in _NC_CACHE["data"].items() if int(pid) in keep}

    def _q_nc_summary(self, project_ids, date_from=None, date_to=None, **kw):
        return _nc_summary_result(self._nc_rows(project_ids, date_from, date_to))

    def _q_nc_costs(self, project_ids, date_from=None, date_to=None, **kw):
        return _nc_costs_result(self._nc_rows(project_ids, date_from, date_to))

    def _q_nc_cause(self, project_ids, date_from=None, date_to=None, **kw):
        return _nc_cause_result(self._nc_rows(project_ids, date_from, date_to))

    def _q_nc_discipline(self, project_ids, date_from=None, date_to=None, **kw):
        return _nc_discipline_result(self._nc_rows(project_ids, date_from, date_to))

    def _q_nc_supplier(self, project_ids, date_from=None, date_to=None, **kw):
        return _nc_supplier_result(self._nc_rows(project_ids, date_from, date_to))

    def _q_nc_impact(self, project_ids, date_from=None, date_to=None, **kw):
        rows = self._nc_rows(project_ids, date_from, date_to)
        return _nc_impact_result(rows, self._material_actuals(project_ids))

    def _q_nc_detail(self, project_ids, date_from=None, date_to=None, **kw):
        return _nc_detail_result(self._nc_rows(project_ids, date_from, date_to))

    def _q_nc_rework(self, project_ids, date_from=None, date_to=None, **kw):
        return _nc_rework_result(self._rework_by_discipline(project_ids))

    def _q_nc_dashboard(self, project_ids, date_from=None, date_to=None, **kw):
        # NC as % of budget, Labour (rework 999) vs Material (NC material $), by discipline +
        # overall. Lifetime view (NC is cumulative), so material NC ignores the date window.
        fin = self._financials(project_ids)
        rw = self._rework_by_discipline(project_ids)
        ncrows = self._nc_rows(project_ids, None, None)
        thr = self._rework_thresholds(project_ids)
        matnc_pid, matnc_pd = {}, {}
        for r in ncrows:
            pv = r.get("ProjectID")
            if pv in (None, ""):
                continue
            pid = int(pv)
            dsc = r.get("Discipline") or "Other"
            c = float(ncspec._material(r) or 0)
            matnc_pid[pid] = matnc_pid.get(pid, 0.0) + c
            dd = matnc_pd.setdefault(pid, {})
            dd[dsc] = dd.get(dsc, 0.0) + c
        data = []
        for pid in sorted(fin):
            f = fin[pid]
            disc_budgets = {d.discipline: d.budget_hours for d in (f.disciplines or [])}
            data.append(_nc_dash_record(
                pid, f.labour_budget_hours, getattr(f, "labour_rate", None), f.material_budget,
                disc_budgets, rw.get(pid, {}), matnc_pid.get(pid, 0.0),
                matnc_pd.get(pid, {}), thr.get(pid)))
        return _nc_dashboard_result(data)


# ─────────────────────────────────────────────────────────────────────────────
# Shared result builders (used by both live and demo backends)
# ─────────────────────────────────────────────────────────────────────────────
def _scorecard_result(rows):
    proj, labour, material = L("project"), L("labour"), L("material")
    cols = [
        QueryColumn("ProjectID", proj, "id", "left"),
        QueryColumn("LabourBudget", f"{labour} Budget (hrs)", "hours", "right"),
        QueryColumn("LabourActual", f"{labour} Actual (hrs)", "hours", "right", calc=True),
        QueryColumn("LabourPct", f"{labour} %", "pct", "right"),
        QueryColumn("LabourRework", "Rework (hrs)", "hours", "right", calc=True),
        QueryColumn("ReworkPct", "Rework % of budget", "pct", "right", calc=True),
        QueryColumn("ReworkThreshold", "Rework thresh %", "pct", "right"),
        QueryColumn("MaterialBudget", f"{material} Budget", "money", "right"),
        QueryColumn("MaterialCommitted", "Committed Spend", "money", "right", calc=True),
        QueryColumn("MaterialInventory", "Inventory", "money", "right", calc=True),
        QueryColumn("MaterialPayables", "Payables", "money", "right", calc=True),
        QueryColumn("MaterialActual", "Resource Consumption", "money", "right", calc=True),
        QueryColumn("MaterialPct", f"{material} %", "pct", "right"),
        QueryColumn("RunoutMaterialPct", f"{material} Run-out %", "pct", "right", calc=True),
        QueryColumn("NCOpen", "Open NCRs", "int", "right", calc=True),
        QueryColumn("NCCost", "Cost of NC", "money", "right", calc=True),
        QueryColumn("PctDone", "% Done", "pct", "right"),
        QueryColumn("CustAgreedDate", "Cust Agreed Ship", "date", "left"),
        QueryColumn("RunoutLabour", f"{labour} Run-out (hrs)", "hours", "right", calc=True),
        QueryColumn("RunoutPct", f"{labour} Run-out %", "pct", "right", calc=True),
        QueryColumn("RunoutOverride", "Run-out src", "text", "left"),
        QueryColumn("CPI", "CPI", "num", "right", "Earning at Completion", calc=True),
        QueryColumn("EarningEAC", "Earning $", "money", "right", "Earning at Completion", calc=True),
        QueryColumn("SoldMargin", "Sold Margin", "pct", "right", "Earning at Completion"),
        QueryColumn("MarginEAC", "Margin @ Compl.", "pct", "right", "Earning at Completion", calc=True),
        QueryColumn("Rank", "Rank", "int", "right"),
    ]
    over = [r for r in rows if (r.get("LabourPct") or 0) > 1.0]
    over_rw = [r for r in rows
               if r.get("ReworkPct") is not None and r.get("ReworkThreshold") is not None
               and r["ReworkPct"] > r["ReworkThreshold"]]
    earn = [r.get("EarningEAC") for r in rows if r.get("EarningEAC") is not None]
    cards = [
        Card(L("projects"), str(len(rows))),
        Card(f"Over {labour.lower()} budget", str(len(over)), "bad" if over else "good"),
        Card("Over rework threshold", str(len(over_rw)), "bad" if over_rw else "good"),
        Card(f"Total {material.lower()} budget",
             _fmt_money(sum(r.get("MaterialBudget") or 0 for r in rows))),
    ]
    if earn:                                            # projected earning across the scope
        tot = sum(earn)
        cards.append(Card("Projected earning @ completion", _fmt_money(tot),
                          "good" if tot >= 0 else "bad"))
    note = (f"Italic figures are live from ETO. {material} shows Resource Consumption — the "
            f"total resources drawn to the {proj.lower()}: Committed Spend (purchased material) + "
            f"Inventory (issued from stock) + Payables (other booked costs) — footing to ETO's "
            f"“Material Costs Compared” report. {material} % = Resource Consumption ÷ budget. "
            f"{labour} is hours from timecards; NCR figures from the costing data. Budgets are the "
            f"PM plan; % Done is the CALCULATED roll-up of the per-{L('discipline').lower()} % "
            f"complete (hours-weighted: Σ %C×budget ÷ Σ budget). Run-outs are CALCULATED "
            f"(Carpedia-aligned), not typed: {labour} run-out = Estimate at Completion = actual ÷ "
            f"% complete; {material} run-out = committed POs floored at budget (commitment-driven, "
            f"not %-complete driven). Both colour green ≤95% of budget, amber 95–105%, red >105%. "
            f"“Run-out src” shows “manual” only when a PM has entered an optional override. Earning at Completion "
            f"projects what the job will actually return: CPI (earned ÷ actual — under 1.0 = "
            f"trending over), Earning $ = sold price − cost at completion (labour run-out priced "
            f"at the applied rate + material EAC), and Margin @ Completion vs the margin sold. "
            f"These render only where ETO carries the sold price and a % complete to run out. "
            f"{labour} Actual and {labour} % are PLANNED work — rework (task 999) is excluded and "
            f"tracked separately as Rework (hrs) and Rework % of budget, flagged when it exceeds "
            f"the {proj.lower()}'s rework threshold (default 1%, set per {proj.lower()} in the "
            f"Plan entry). Run-out, CPI and earning stay on TOTAL labour (rework is still real "
            f"spend).")
    return QueryResult("scorecard", f"{proj} {L('scorecard')}", cols, rows, cards, note)


def _discipline_result(rows):
    proj, disc = L("project"), L("discipline")
    cols = [
        QueryColumn("ProjectID", proj, "id", "left"),
        QueryColumn("Discipline", disc, "text", "left"),
        QueryColumn("BudgetHours", "Budget (hrs)", "hours", "right"),
        QueryColumn("ActualHours", "Actual (hrs)", "hours", "right", calc=True),
        QueryColumn("ConsumedPct", "Consumed %", "pct", "right"),
        QueryColumn("PctComplete", "% Complete", "pct", "right"),
        QueryColumn("RunoutHours", "Run-out (hrs)", "hours", "right", calc=True),
        QueryColumn("RunoutPct", "Run-out %", "pct", "right", calc=True),
        QueryColumn("RemainingHours", "Remaining (hrs)", "hours", "right"),
        QueryColumn("ReworkHours", "Rework 999 (hrs)", "hours", "right", calc=True),
        QueryColumn("ReworkPct", "Rework % of budget", "pct", "right", calc=True),
        QueryColumn("ReworkCost", "Rework 999 ($)", "money", "right", calc=True),
    ]
    over = [r for r in rows if (r.get("ConsumedPct") or 0) > 1.0]
    rework = round(sum(r.get("ReworkCost") or 0 for r in rows), 2)
    cards = [
        Card(f"{disc} lines", str(len(rows))),
        Card("Over budget (planned)", str(len(over)), "bad" if over else "good"),
        Card("Rework labour (999)", _fmt_money2(rework), "warn" if rework else "neutral"),
    ]
    note = (f"Budgeted vs actual {L('labour').lower()} hours per {disc.lower()}. Actual and "
            "Consumed % are PLANNED work only — labour charged to task 999 (rework / "
            "non-conformance) is pulled OUT and shown separately: hours, its own % of the "
            f"{disc.lower()}'s budget hours, and applied-rate $. 999 carries no budget of its own, "
            "so it isn't counted in the budget-vs-actual position. Actual + Rework = total hours "
            f"charged to the {disc.lower()}. % Complete is declared per {disc.lower()} (the one "
            "judgement); Run-out is then CALCULATED (Carpedia-aligned): Estimate at Completion = "
            "total actual hours ÷ % complete, and Run-out % = EAC ÷ budget (green ≤95%, amber "
            "95–105%, red >105%). Below 15% complete an additive early-stage EAC is used and marked "
            "low-confidence. Blank % Complete ⇒ no run-out yet.")
    return QueryResult("discipline", f"{disc} Financials", cols, rows, cards, note)


# ---- Non-Conformance — Rework Labour (task 999, by project & discipline) ----
def _nc_rework_rows(rw):
    """rw = {pid: {discipline: [hours, cost]}}. Grouped project → discipline with per-project and
    grand subtotals (cost IS summable; hours too, within a project)."""
    if not rw:
        return []
    rows, ghrs, gcost = [], 0.0, 0.0
    for pid in sorted(rw, key=lambda x: int(x)):
        discs = rw[pid]
        rows.append({"_kind": "l3_sub", "Discipline": f"Project: {int(pid)}"})
        phrs = pcost = 0.0
        for disc in sorted(discs):
            h, c = discs[disc]
            rows.append({"_kind": "detail", "Discipline": disc,
                         "ReworkHours": round(float(h), 2), "ReworkCost": round(float(c), 2)})
            phrs += float(h)
            pcost += float(c)
        rows.append({"_kind": "l1_sub", "Discipline": f"Project {int(pid)} — total",
                     "ReworkHours": round(phrs, 2), "ReworkCost": round(pcost, 2)})
        ghrs += phrs
        gcost += pcost
    rows.append({"_kind": "grand", "Discipline": "GRAND TOTAL — rework labour",
                 "ReworkHours": round(ghrs, 2), "ReworkCost": round(gcost, 2)})
    return rows


def _nc_rework_result(rw):
    proj, disc = L("project"), L("discipline")
    cols = [
        QueryColumn("Discipline", disc, "text", "left"),
        QueryColumn("ReworkHours", "Rework (hrs)", "hours", "right", calc=True),
        QueryColumn("ReworkCost", "Rework ($)", "money", "right", calc=True),
    ]
    rw = rw or {}
    projects = len(rw)
    total_hrs = round(sum(h for d in rw.values() for h, _ in d.values()), 2)
    total_cost = round(sum(c for d in rw.values() for _, c in d.values()), 2)
    cards = [Card("Rework labour", _fmt_money2(total_cost), "warn" if total_cost else "neutral"),
             Card("Rework hours", "{:,.1f}".format(total_hrs)),
             Card(f"{proj}s with rework", str(projects))]
    note = (f"Rework / non-conformance labour — hours and applied-rate cost charged to task 999 "
            f"(the {proj.lower()}'s Non-Conformance / Rework bucket), by {proj.lower()} and "
            f"{disc.lower()}. This is actual-only: 999 carries no budget, and NONE of it is linked "
            "to an individual NCR (it's booked at the project level), which is why the per-NCR NC "
            f"costing shows ~$0 labour. {disc}s use the same crosswalk as the labour reports.")
    return QueryResult("nc_rework", "Non-Conformance — Rework Labour", cols,
                       _nc_rework_rows(rw), cards, note)


# ---- Non-Conformance — NC Dashboard (NC as % of budget: Labour + Material) ----
def _nc_dash_record(pid, lab_budget_hrs, lab_rate, mat_budget, disc_budgets,
                    rework_disc, mat_nc_total, mat_nc_disc, threshold):
    """One project's NC-dashboard record (pure). Labour NC = rework(999): hours ÷ budget hours.
    Material NC = NC material $ ÷ material budget $. Combined NC % = (rework $ + material NC $) ÷
    total budget $, where labour budget $ = budget hours × applied rate. Flagged vs the project's
    threshold (default 1%)."""
    lab_budget_hrs = float(lab_budget_hrs or 0)
    lab_rate = float(lab_rate or 0)
    mat_budget = float(mat_budget or 0)
    lab_nc_hrs = round(sum(float(h) for h, _ in rework_disc.values()), 2)
    lab_nc_cost = round(sum(float(c) for _, c in rework_disc.values()), 2)
    mat_nc = round(float(mat_nc_total or 0), 2)
    lab_nc_pct = round(lab_nc_hrs / lab_budget_hrs, 4) if lab_budget_hrs else None
    mat_nc_pct = round(mat_nc / mat_budget, 4) if mat_budget else None
    total_budget = lab_budget_hrs * lab_rate + mat_budget
    combined_cost = round(lab_nc_cost + mat_nc, 2)
    combined_pct = round(combined_cost / total_budget, 4) if total_budget else None
    thr = float(threshold) if threshold else 0.01
    over = combined_pct is not None and combined_pct > thr
    discs = []
    for d in sorted(set(rework_disc) | set(mat_nc_disc)):
        h, c = rework_disc.get(d, (0.0, 0.0))
        dbud = float(disc_budgets.get(d) or 0)
        discs.append({"disc": d, "hrs": round(float(h), 2) or None,
                      "cost": round(float(c), 2) or None,
                      "lab_pct": (round(float(h) / dbud, 4) if dbud else None),
                      "mat_cost": round(float(mat_nc_disc.get(d, 0.0)), 2) or None})
    return {"pid": int(pid), "lab_nc_hrs": lab_nc_hrs, "lab_nc_cost": lab_nc_cost,
            "lab_nc_pct": lab_nc_pct, "mat_nc": mat_nc, "mat_nc_pct": mat_nc_pct,
            "combined_cost": combined_cost, "combined_pct": combined_pct,
            "total_budget": round(total_budget, 2), "threshold": thr, "over": over,
            "disciplines": discs}


def _nc_dashboard_rows(data):
    if not data:
        return []

    def _p(x):                                   # fraction → "1.4%" / "n/a"
        return f"{x * 100:.1f}%" if x is not None else "n/a"

    rows = []
    for rec in data:
        pid = rec["pid"]
        thr = rec["threshold"]                       # colours every % pill on this project's rows
        cp, lp, mp = rec["combined_pct"], rec["lab_nc_pct"], rec["mat_nc_pct"]
        # Full-width project band header: carries the whole NC summary in the label (no numeric
        # column populated → the frontend renders it as a spanning band, so the discipline column
        # is sized only by the short discipline names below, not by this long line).
        band = (f"Project {pid} — Combined NC {_p(cp)} of budget"
                f"   ·   Labour {_p(lp)} · Material {_p(mp)}"
                f"   ·   threshold {thr * 100:.2f}%"
                + ("     ⚠ OVER" if rec["over"] else ""))
        rows.append({"_kind": "l3_sub", "Discipline": band, "_thr": thr})
        for d in rec["disciplines"]:
            rows.append({"_kind": "detail", "Discipline": d["disc"], "LabHrs": d["hrs"],
                         "LabCost": d["cost"], "LabPct": d["lab_pct"], "MatCost": d["mat_cost"],
                         "_thr": thr})
        # Numeric subtotal — short label so it doesn't stretch the discipline column.
        rows.append({"_kind": "l1_sub", "Discipline": f"Project {pid} — total",
                     "LabHrs": rec["lab_nc_hrs"] or None, "LabCost": rec["lab_nc_cost"] or None,
                     "LabPct": lp, "MatCost": rec["mat_nc"] or None, "NCPct": cp, "_thr": thr})
    tlab = round(sum(r["lab_nc_cost"] for r in data), 2)
    tmat = round(sum(r["mat_nc"] for r in data), 2)
    tbud = sum(r.get("total_budget") or 0 for r in data)
    grand = {"_kind": "grand", "Discipline": "GRAND TOTAL", "LabCost": tlab, "MatCost": tmat,
             "_thr": 0.01}
    if tbud:
        grand["NCPct"] = round((tlab + tmat) / tbud, 4)
    rows.append(grand)
    return rows


def _nc_dashboard_result(data):
    proj, disc = L("project"), L("discipline")
    cols = [
        QueryColumn("Discipline", disc, "text", "left", wrap=True),
        QueryColumn("LabHrs", "Labour NC (hrs)", "hours", "right", calc=True),
        QueryColumn("LabCost", "Labour NC ($)", "money", "right", calc=True),
        QueryColumn("LabPct", "Labour NC % (disc budget)", "pct", "right", calc=True),
        QueryColumn("MatCost", "Material NC ($)", "money", "right", calc=True),
        QueryColumn("NCPct", "NC % of budget", "pct", "right", calc=True),
    ]
    data = data or []
    tlab = round(sum(r["lab_nc_cost"] for r in data), 2)
    tmat = round(sum(r["mat_nc"] for r in data), 2)
    over = [r for r in data if r["over"]]
    cards = [Card("Labour NC ($)", _fmt_money2(tlab), "warn" if tlab else "neutral"),
             Card("Material NC ($)", _fmt_money2(tmat), "warn" if tmat else "neutral"),
             Card("Combined NC ($)", _fmt_money2(tlab + tmat)),
             Card("Over NC threshold", str(len(over)), "bad" if over else "good")]
    note = (f"Non-conformance as a % of budget, split into LABOUR (rework charged to task 999) and "
            f"MATERIAL (NC material cost). Per {disc.lower()}: Labour NC % = rework hours ÷ that "
            f"{disc.lower()}'s budget hours; Material NC $ is attributed by the NCR origin (no "
            f"per-{disc.lower()} material budget exists, so it's shown as $, not %). Per "
            f"{proj.lower()} (the band + subtotal): Combined NC % = (rework $ + material NC $) ÷ "
            f"total budget $ (labour budget hours × applied rate + material budget), flagged ⚠ when "
            f"it exceeds the {proj.lower()}'s NC threshold (Plan entry; default 1%). Lifetime view.")
    return QueryResult("nc_dashboard", "Non-Conformance — NC Dashboard", cols,
                       _nc_dashboard_rows(data), cards, note)


def _budget_actual_result(rows):
    proj, labour, material = L("project"), L("labour"), L("material")
    cols = [
        QueryColumn("ProjectID", proj, "id", "left"),
        QueryColumn("LabourBudget", f"{labour} Budget (hrs)", "hours", "right"),
        QueryColumn("LabourActual", f"{labour} Actual (hrs)", "hours", "right", calc=True),
        QueryColumn("LabourVar", f"{labour} Variance (hrs)", "hours", "right"),
        QueryColumn("LabourPct", f"{labour} %", "pct", "right"),
        QueryColumn("MaterialBudget", f"{material} Budget", "money", "right"),
        QueryColumn("MaterialActual", f"{material} Actual", "money", "right", calc=True),
        QueryColumn("MaterialVar", f"{material} Variance", "money", "right"),
        QueryColumn("MaterialPct", f"{material} %", "pct", "right"),
    ]
    cards = [Card(L("projects"), str(len(rows)))]
    note = (f"Italic Actual columns are live from ETO — {labour.lower()} hours from timecards and "
            f"{material.lower()} as Resource Consumption (purchased + inventory + payables, ties "
            f"to ETO's material report). Budgets are the PM plan; variance = budget − actual.")
    return QueryResult("budget_actual", "Budget vs Actual", cols, rows, cards, note)


def _crosswalk_result(rows):
    disc = L("discipline")
    cols = [
        QueryColumn("HourDescription", L("hour_description"), "text", "left", wrap=True),
        QueryColumn("Discipline", disc, "text", "left"),
    ]
    cards = [Card("Mappings", str(len(rows)))]
    return QueryResult("crosswalk", L("crosswalk"), cols, rows, cards)


# ── Carpedia run-out helpers (shared live + demo) ─────────────────────────────
# CARPEDIA-ALIGNED FORMULAE (PROJECT_CONSOLE_RUNOUT_METHODOLOGY_2026-07-28):
#   %C(project)      = Σ( %C(discipline) × budget_hrs(discipline) ) ÷ Σ budget_hrs   ( = EV ÷ BAC )
#   Labour run-out   : EV = %C×BAC ; CPI = EV÷AC ; EAC = AC÷%C ; run-out% = EAC÷BAC = %consumed÷%C
#                      (early stage %C<15% → EAC = AC + (BAC−EV); see earned_value.compute)
#   Material run-out : EAC = committed POs (received + open) + remaining-un-ordered
#                            where remaining-un-ordered = max(0, budget − committed)
#                            ⇒ EAC = max(committed, budget) ; run-out% = EAC ÷ budget
#                      Commitment-driven, floored at budget — NOT %-complete driven.
# Both are CALCULATED. The PM's typed run-out is only an optional OVERRIDE (flagged).

def _rollup_pct_complete(disciplines, prog):
    """Project %C = Σ(%C_disc × budget_hrs_disc) ÷ Σ budget_hrs_disc (hours-weighted EV÷BAC).
    prog = {discipline: 0–1 fraction}. A discipline with no declared % contributes 0 progress
    (it's budgeted work not yet started). Returns None when there are no budget hours at all."""
    num = den = 0.0
    for d in (disciplines or []):
        bh = float(getattr(d, "budget_hours", 0) or 0)
        if bh <= 0:
            continue
        p = prog.get(getattr(d, "discipline", None)) if prog else None
        num += bh * (float(p) if p is not None else 0.0)
        den += bh
    return round(num / den, 4) if den else None


def _material_runout(committed, budget):
    """Carpedia material run-out — commitment-driven, floored at budget.
    EAC = committed (received + open) + max(0, budget − committed) = max(committed, budget).
    Returns a dict; run-out % and EAC are None when there's no material budget to run out against."""
    b = _num(budget)
    c = _num(committed) or 0.0
    if not b:
        return {"eac": None, "runout_pct": None, "committed": (round(c, 2) or None),
                "unordered": None, "over": False}
    unordered = max(0.0, b - c)
    eac = c + unordered                                   # == max(c, b)
    return {"eac": round(eac, 2), "runout_pct": round(eac / b, 4),
            "committed": round(c, 2), "unordered": round(unordered, 2), "over": eac > b}


def _scorecard_row(pid, f, rec):
    # Run-out = computed EAC from budget/actual hours + PM %complete (earned_value engine),
    # falling back to the PM's typed run-out only when there's no % complete yet.
    _ro = _ev.compute(f.labour_budget_hours, f.labour_actual_hours, _num(rec.get("PctDone")))
    earning, margin = _earning_block(f, _ro)
    # Material run-out — Carpedia commitment basis (committed POs floored at budget), unless the PM
    # has typed an override (kept optional). RunoutMaterial in the overlay is that manual override.
    _mr = _material_runout(rec.get("MaterialCommittedFull"), f.material_budget)
    _mat_ovr = _num(rec.get("RunoutMaterial"))
    runout_mat_pct = _mat_ovr if _mat_ovr is not None else _mr["runout_pct"]
    lab_ovr = _num(rec.get("RunoutLabourPct"))            # optional labour run-out % override
    runout_lab_pct = lab_ovr if lab_ovr is not None else _ro.runout_pct
    overridden = (_mat_ovr is not None) or (lab_ovr is not None)
    # Labour Actual / % are PLANNED (exclude rework 999); rework is its own hours + % of budget,
    # flagged against the per-project threshold (default 1%). Run-out / CPI / earning above stay on
    # the TOTAL actual (rework is still real spend). Vijay 2026-08-07.
    rw_h = _num(rec.get("Rework")) or 0.0
    planned_actual = (round(f.labour_actual_hours - rw_h, 2)
                      if f.labour_actual_hours is not None else None)
    planned_pct = (round(planned_actual / f.labour_budget_hours, 4)
                   if (f.labour_budget_hours and planned_actual is not None) else None)
    rework_pct = round(rw_h / f.labour_budget_hours, 4) if f.labour_budget_hours else None
    rework_thresh = _num(rec.get("ReworkThreshold")) or 0.01     # per-project; 1% default
    return {
        "ProjectID": pid,
        "LabourBudget": f.labour_budget_hours,
        "LabourActual": planned_actual,
        "LabourPct": planned_pct,
        "LabourRework": (rw_h or None),
        "ReworkPct": rework_pct,
        "ReworkThreshold": rework_thresh,
        "MaterialBudget": f.material_budget,
        "MaterialCommitted": getattr(f, "material_committed", None),
        "MaterialInventory": getattr(f, "material_inventory", None),
        "MaterialPayables": getattr(f, "material_payables", None),
        "MaterialActual": f.material_actual,
        "MaterialPct": f.material_consumed_pct,
        "NCOpen": _int(rec.get("NCOpen")),
        "NCCost": _num(rec.get("NCCost")),
        "PctDone": _num(rec.get("PctDone")),
        "CustAgreedDate": _iso(rec.get("CustAgreedDate") or rec.get("POShipDate")),
        "RunoutLabour": (_ro.eac if _ro.eac is not None else _num(rec.get("RunoutLabour"))),
        "RunoutPct": runout_lab_pct,
        "RunoutMaterialPct": runout_mat_pct,
        "MaterialEAC": _mr["eac"],
        "MaterialUnordered": _mr["unordered"],
        "RunoutOverride": ("manual" if overridden else None),
        "CPI": (round(_ro.cpi, 3) if _ro.cpi is not None else None),
        "EarningEAC": earning,
        "SoldMargin": getattr(f, "sold_margin", None),
        "MarginEAC": margin,
        "Rank": _int(rec.get("Rank")),
    }


def _earning_block(f, ro):
    """Leadership earning lens → (earning_at_completion $, margin_at_completion fraction).

    Cost EAC = labour run-out priced at the applied rate + material EAC, netted against the sold
    price. Labour cost EAC = hours run-out (ro.eac) × applied $/hr (ETO cost ÷ hours). Material
    EAC = the max of Committed Spend, Resource Consumption and budget — you'll spend at least what
    you've committed, at least what you've consumed, and at least what you budgeted. Returns
    (None, None) unless there's a computable hours run-out, an applied rate and a sold price — so
    the columns stay blank rather than showing a half-built projection."""
    if ro is None or ro.eac is None:
        return None, None
    rate = getattr(f, "labour_rate", None)
    if rate is None:
        return None, None
    lab_cost_eac = round(ro.eac * rate, 2)
    mat_vals = [x for x in (getattr(f, "material_committed", None), f.material_actual,
                            f.material_budget) if x is not None]
    if not mat_vals:
        return None, None
    return _ev.earning_at_completion(getattr(f, "sales_price", None), lab_cost_eac, max(mat_vals))


def _budget_actual_row(pid, f):
    lb, la = f.labour_budget_hours, f.labour_actual_hours
    mb, ma = f.material_budget, f.material_actual
    return {
        "ProjectID": pid,
        "LabourBudget": lb, "LabourActual": la,
        "LabourVar": (round(lb - (la or 0), 2) if lb is not None else None),
        "LabourPct": f.labour_consumed_pct,
        "MaterialBudget": mb, "MaterialActual": ma,
        "MaterialVar": (round(mb - (ma or 0), 2) if mb is not None else None),
        "MaterialPct": f.material_consumed_pct,
    }


# ─────────────────────────────────────────────────────────────────────────────
# Executive Dashboard — the full ranked board (mirrors console_dashboard.py)
# ─────────────────────────────────────────────────────────────────────────────
_EXEC_DISC_ORDER = ["Project Management", "Mechanical Engineering",
                    "Hydraulic Engineering", "Electrical Engineering", "Manufacturing"]
_EXEC_DISC_SHORT = {"Project Management": "PM", "Mechanical Engineering": "Mechanical",
                    "Hydraulic Engineering": "Hydraulic",
                    "Electrical Engineering": "Electrical", "Manufacturing": "Manufacturing"}


def _exec_columns():
    labour, material, disc = L("labour"), L("material"), L("discipline")
    cols = [
        QueryColumn("Rank", "Rank", "int", "right", ""),
        QueryColumn("ProjectID", "Proj ID", "id", "left", ""),
        QueryColumn("Project", L("project"), "text", "left", "", wrap=True),
        # Schedule
        QueryColumn("POShipDate", "P.O. Ship", "date", "left", "Schedule"),
        QueryColumn("CustAgreedDate", "Cust. Agreed", "date", "left", "Schedule"),
        QueryColumn("PlannedShipDate", "Planned Ship", "date", "left", "Schedule"),
        QueryColumn("SlippageDays", "Slippage (d)", "days", "right", "Schedule"),
        QueryColumn("PctDone", "% Done", "pct", "right", "Schedule"),
        # Budget
        QueryColumn("LabPctHrs", f"{labour} % (hrs)", "pct", "right", "Budget"),
        QueryColumn("RunoutLabour", f"Run-out {labour}", "pct", "right", "Budget", calc=True),
        QueryColumn("MatPct", f"{material} %", "pct", "right", "Budget"),
        QueryColumn("RunoutMaterial", f"Run-out {material}", "pct", "right", "Budget"),
        # 2-Week Delta
        QueryColumn("PctDoneDelta", "Δ % Done", "pct", "right", "2-Week Delta"),
        QueryColumn("LabHrs2wk", f"Δ {labour} Hrs", "hours", "right", "2-Week Delta", calc=True),
        QueryColumn("MatSpend2wk", f"Δ {material} $", "money", "right", "2-Week Delta", calc=True),
    ]
    # Labour by discipline (block band reads as the labour word, per the workbook)
    for d in _EXEC_DISC_ORDER:
        cols.append(QueryColumn(f"disc::{d}", _EXEC_DISC_SHORT[d], "pct", "right", labour))
    # Procurement — italicised columns are calculated live from ETO; the rest are PM entries.
    _CALC_PROC = {"TotalLineItems", "LLTPDelLate"}
    for key, lab in [("TotalLineItems", "Line Items"), ("LLTPOrdered", "LLTP Ord."),
                     ("LLTPRelLate", "LLTP Rel. Late"), ("LLTPOrdLate", "LLTP Ord. Late"),
                     ("LLTPDelLate", "LLTP Del. Late"), ("PartsRelLate", "Parts Rel. Late"),
                     ("PartsOrdLate", "Parts Ord. Late")]:
        cols.append(QueryColumn(key, lab, "int", "right", "Procurement", calc=(key in _CALC_PROC)))
    # Non-Conformance actuals (calculated live from ETO → italic)
    cols.append(QueryColumn("NCOpen", "Open NCRs", "int", "right", "Non-Conformance", calc=True))
    cols.append(QueryColumn("NCCost", "Cost of NC", "money", "right", "Non-Conformance", calc=True))
    return cols


def _exec_result(rows):
    cols = _exec_columns()
    over = [r for r in rows if (r.get("LabPctHrs") or 0) > 1.0]
    slipped = [r for r in rows if (r.get("SlippageDays") or 0) > 0]
    cards = [
        Card(L("projects"), str(len(rows))),
        Card(f"Over {L('labour').lower()} budget", str(len(over)), "bad" if over else "good"),
        Card("Schedule slipped", str(len(slipped)), "bad" if slipped else "good"),
    ]
    note = (f"Italicised figures are calculated live from the system: {L('labour').lower()} & "
            f"{L('material').lower()} %, the 2-week {L('labour').lower()}-hours and "
            f"{L('material').lower()}-$ deltas, Line Items, LLTP Del. Late, and the "
            f"Non-Conformance figures, and the {L('labour').lower()} Run-out (computed Estimate at "
            f"Completion = actual ÷ % complete). Schedule, % Done (incl. its 2-week delta), "
            f"{L('material').lower()} run-out and the remaining procurement counts are PM entries. "
            f"Ranked by {L('labour').lower()} % of budget (hours).")
    return QueryResult("exec", "Executive Dashboard", cols, rows, cards, note)


def _exec_row(pid, name, client, f, rec, disc_pct):
    """Assemble one ranked row from financials (ETO) + overlay (manual)."""
    planned = rec.get("PlannedShipDate")
    agreed = rec.get("CustAgreedDate")
    _ro = _ev.compute(f.labour_budget_hours if f else None,
                      f.labour_actual_hours if f else None, _frac(rec.get("PctDone")))
    # Material run-out: Carpedia commitment basis (committed POs floored at budget), PM override wins.
    _mr = _material_runout(rec.get("MaterialCommittedFull"), f.material_budget if f else None)
    _mat_ovr = _num(rec.get("RunoutMaterial"))
    row = {
        "Rank": _int(rec.get("Rank")),
        "ProjectID": pid,
        "Project": name or str(pid),
        "Client": client,
        "POShipDate": _iso(rec.get("POShipDate")),
        "CustAgreedDate": _iso(agreed),
        "PlannedShipDate": _iso(planned),
        "SlippageDays": _slip(planned, agreed),
        "PctDone": _frac(rec.get("PctDone")),
        "LabPctHrs": f.labour_consumed_pct if f else None,
        "RunoutLabour": (_ro.runout_pct if _ro.runout_pct is not None else _num(rec.get("RunoutLabour"))),
        "MatPct": f.material_consumed_pct if f else None,
        "RunoutMaterial": (_mat_ovr if _mat_ovr is not None else _mr["runout_pct"]),
        "PctDoneDelta": _frac(rec.get("PctDoneDelta")),
        "LabHrs2wk": _num(rec.get("LabHrs2wk")),
        "MatSpend2wk": _num(rec.get("MatSpend2wk")),
        "TotalLineItems": _int(rec.get("TotalLineItems")),
        "LLTPOrdered": _int(rec.get("LLTPOrdered")),
        "LLTPRelLate": _int(rec.get("LLTPRelLate")),
        "LLTPOrdLate": _int(rec.get("LLTPOrdLate")),
        "LLTPDelLate": _int(rec.get("LLTPDelLate")),
        "PartsRelLate": _int(rec.get("PartsRelLate")),
        "PartsOrdLate": _int(rec.get("PartsOrdLate")),
        "NCOpen": _int(rec.get("NCOpen")),
        "NCCost": _num(rec.get("NCCost")),
    }
    for d in _EXEC_DISC_ORDER:
        row[f"disc::{d}"] = disc_pct.get(d)
    return row


def _finalize_exec(rows):
    """Rank sort (ranked first asc, then by labour % desc) and renumber 1..n."""
    def sortkey(r):
        has = r.get("Rank") is not None
        return (0 if has else 1, r.get("Rank") if has else 0,
                -(r.get("LabPctHrs") or 0))
    rows = sorted(rows, key=sortkey)
    for i, r in enumerate(rows, 1):
        r["Rank"] = i
    return _exec_result(rows)


# ─────────────────────────────────────────────────────────────────────────────
# ETO report families — Labour / Purchase / Non-Conformance (read-only, live)
# Each reads a canonical ETO view (never base tables), scoped to the selected
# projects, honouring an optional [date_from, date_to] window. Kept in separate
# queries per the fan-out rule (never join timecards to PO/NCR).
# ─────────────────────────────────────────────────────────────────────────────
# Reports render the FULL result set — no row cap. Large reports are paginated in
# the browser for practicality; the Excel and PDF exports always contain every row.


def _ids_sql(project_ids):
    return ",".join(str(int(p)) for p in (project_ids or []))


def _date_clause(col, dfrom, dto):
    parts = []
    if dfrom:
        parts.append(f"{col} >= '{_as_date(dfrom)}'")
    if dto:
        parts.append(f"{col} <= '{_as_date(dto)}'")
    return (" AND " + " AND ".join(parts)) if parts else ""


# ---- Labour + Purchasing result builders (the deployed eto-reporting engine) --
# The five daily labour reports (A–E) and the two PO reports are produced by the
# vendored `etospec` module — the SAME code the on-prem eto-reporting suite runs —
# so the on-screen tables and the Excel exports match the deployed reports exactly.
# Rows carry a reserved "_kind" (detail / l1_sub / l2_sub / l3_sub / grand /
# section) that the browser and the exporter use to style subtotal bands.

def _fmt_money2(v):
    try:
        return "${:,.2f}".format(float(v))
    except (TypeError, ValueError):
        return str(v)


def _grand_of(col_defs, grouped_rows):
    keys = [c[0] for c in col_defs]
    for cells, kind in grouped_rows:
        if kind == "grand":
            return dict(zip(keys, cells))
    return {}


def _spec_labour_cards(col_defs, grouped_rows):
    g = _grand_of(col_defs, grouped_rows)
    cards = []
    if g.get("Entries") not in (None, ""):
        cards.append(Card("Entries", "{:,}".format(int(g["Entries"]))))
    if g.get("Hours") not in (None, ""):
        cards.append(Card("Hours", "{:,.2f}".format(float(g["Hours"]))))
    if g.get("LabourCost") not in (None, ""):
        cards.append(Card("Labour Cost", _fmt_money2(g["LabourCost"])))
    return cards


def _window_label(dfrom, dto):
    """Human label for the reporting window (all windows are cumulative to `dto`)."""
    if dfrom is None:
        return f"from project start through {dto:%b %d, %Y}"
    return f"{dfrom:%b %d, %Y} – {dto:%b %d, %Y}"


def _labour_add_discipline(df, xwalk):
    """Add a 'Discipline' column to the labour frame using the HourDescription→discipline crosswalk
    (the SAME map the dashboard uses). Category carries the HourDescription; task-999 rows arrive as
    'Re-work' and stay their own bucket. Unmapped descriptions fall back to the keyword rule."""
    if df is None or getattr(df, "empty", True):
        if df is not None:
            df["Discipline"] = []
        return df
    try:
        from console.domain.hourtype_map import discipline_for
    except Exception:
        discipline_for = None
    xw = xwalk or {}

    def _one(cat, dept):
        if cat == "Re-work":
            return "Re-work"
        d = xw.get(cat)
        if d:
            return d
        return discipline_for(dept, cat) if discipline_for else "Other"

    out = df.copy()
    out["Discipline"] = [_one(c, dep) for c, dep in zip(out["Category"], out["Department"])]
    return out


def _spec_labour_result(report_id, df, label):
    """Build a labour QueryResult for one time window (single control = the date range)."""
    meta = etospec.LABOUR_REPORTS[report_id]
    grouped = meta["builder"](df)
    qcols = [QueryColumn(k, l, t, a, "", w) for (k, l, t, a, w) in etospec.web_columns(meta["cols"])]
    rows = etospec.web_rows(meta["cols"], grouped)
    cards = _spec_labour_cards(meta["cols"], grouped)
    note = (f"{meta['title']} — {label}. Labour cost includes overtime and uses the rate on "
            "each timecard. Figures run from project start through the end date.")
    export = {"kind": "labour", "report_id": report_id, "rows": grouped, "label": label}
    return QueryResult(report_id, f"{L('labour')} — {meta['label']}", qcols, rows, cards, note, export)


def _spec_po_status_result(pdf, label):
    """pdf is a po_prep'd DataFrame. Web shows the grouped detail; export writes the
    full Contents & Summary + PO Status workbook."""
    grouped, _idx = etospec.po_build_rows(pdf)
    qcols = [QueryColumn(k, l, t, a, "", w) for (k, l, t, a, w) in etospec.web_columns(etospec.COLS_PO)]
    rows = etospec.web_rows(etospec.COLS_PO, grouped)
    aging = etospec.po_aging_summary(pdf)
    ov_lines = sum(l for _, l, _ in aging)
    ov_val = sum(v for _, _, v in aging)
    open_lines = 0 if pdf is None or pdf.empty else len(pdf)
    cards = [Card("Open lines", "{:,}".format(open_lines)),
             Card("Overdue lines", "{:,}".format(ov_lines), "bad" if ov_lines else "good"),
             Card("Overdue value", _fmt_money2(ov_val), "bad" if ov_val else "good")]
    note = ("Open purchase-order lines — On Order and Overdue. Overdue means the need-by date "
            "has passed. Grouped by project and machine, with an overdue-aging summary; the "
            "Excel export adds a contents and summary sheet.")
    return QueryResult("po_status", "Purchasing — PO Status", qcols, rows, cards, note,
                       {"kind": "po_status", "df": pdf, "label": label})


def _spec_po_exc_result(items, label, enriched=True):
    """items = exc_detail output — one row per OPEN, OVERDUE PO line (per-line detail)."""
    grouped = etospec.exc_detail_build_rows(items)
    qcols = [QueryColumn(k, l, t, a, "", w) for (k, l, t, a, w) in etospec.web_columns(etospec.COLS_EXC)]
    rows = etospec.web_rows(etospec.COLS_EXC, grouped)
    n = 0 if items is None or items.empty else len(items)
    val = 0.0 if not n else float(items["ExtValue"].sum())
    cards = [Card("Overdue lines", "{:,}".format(n), "bad" if n else "good"),
             Card("At-risk value", _fmt_money2(val), "bad" if val else "good")]
    note = ("Open purchase-order lines past their need-by date (revised else required), one row per "
            "line. Code = machine/spec; Category = item category; Receipt Date = last receipt. Status "
            "is derived. Planned Ship, Days to Assembly, RFQ Date, Permit Dates, Last Updated and Lead "
            "Time are shown for the workbook layout but ETO holds no maintained source for them, so "
            "they read blank."
            + ("" if enriched else " Item details weren't available this run, so LLT / Oversize are blank."))
    return QueryResult("po_exceptions", "Purchasing — Procurement Exceptions", qcols, rows, cards, note,
                       {"kind": "exceptions", "items": items, "label": label})


def _spec_late_result(df, label):
    """df = query_late_vendors output (overdue open lines). Web shows vendor-grouped lines;
    export writes the faithful single-sheet workbook."""
    grouped = etospec.late_build_rows(df)
    qcols = [QueryColumn(k, l, t, a, "", w) for (k, l, t, a, w) in etospec.web_columns(etospec.COLS_LATE)]
    rows = etospec.web_rows(etospec.COLS_LATE, grouped)
    empty = df is None or df.empty
    n = 0 if empty else len(df)
    vendors = 0 if empty else int(df["Supplier"].nunique())
    val = 0.0 if empty else float(df["ExtValue"].sum())
    worst = 0 if empty else int(df["DaysLate"].max())
    cards = [Card("Overdue lines", "{:,}".format(n), "bad" if n else "good"),
             Card("Vendors", "{:,}".format(vendors)),
             Card("Worst (days)", "{:,}".format(worst), "bad" if worst else "good"),
             Card("Overdue value", _fmt_money2(val), "bad" if val else "good")]
    note = ("Open purchase-order lines whose need-by date has already passed, grouped by vendor. "
            "Days Late = today minus the need-by date. This is the expediting view — what's still "
            "outstanding and late. For items that were delivered late, see the Late Vendors report.")
    return QueryResult("po_late", "Purchasing — Overdue POs", qcols, rows, cards, note,
                       {"kind": "late", "df": df, "label": label})


def _delivered_label(dfrom, dto):
    if dfrom or dto:
        return f"POs created {dfrom or '…'} → {dto or 'today'}"
    return "POs created — all history"


def _spec_delivered_result(df, label):
    """df = query_delivered_late output (received-late). Vendor delivery scorecard."""
    grouped = etospec.delivered_build_rows(df)
    qcols = [QueryColumn(k, l, t, a, "", w) for (k, l, t, a, w) in etospec.web_columns(etospec.COLS_DELIVERED)]
    rows = etospec.web_rows(etospec.COLS_DELIVERED, grouped)
    empty = df is None or df.empty
    n = 0 if empty else len(df)
    vendors = 0 if empty else int(df["Supplier"].nunique())
    val = 0.0 if empty else float(df["ExtValue"].sum())
    worst = 0 if empty else int(df["DaysLate"].max())
    cards = [Card("Late lines", "{:,}".format(n), "bad" if n else "good"),
             Card("Vendors", "{:,}".format(vendors)),
             Card("Worst (days)", "{:,}".format(worst), "bad" if worst else "good"),
             Card("Late value", _fmt_money2(val), "bad" if val else "good")]
    note = ("Vendor delivery scorecard — items received after their need-by date, grouped by "
            "vendor. Days Late = the receipt date minus the need-by date; value is shown in "
            "Canadian dollars. Covers the selected projects and the date range you chose (by "
            "when the orders were placed).")
    return QueryResult("po_delivered", "Purchasing — Late Vendors", qcols, rows, cards, note,
                       {"kind": "delivered", "df": df, "label": label})


# ---- Purchasing — PO Report (all purchases) + By Buyer -------------------
def _po_all_result(rows, window_label=""):
    out = []
    for r in rows:
        out.append({
            "ProjectID": _int(r.get("ProjectID")),
            "Project": r.get("JobName") or "",
            "POs": _int(r.get("POs")),
            "Lines": _int(r.get("Lines")),
            "TotalPurchases": _num(r.get("TotalPurchases")),
            "ReceivedValue": _num(r.get("ReceivedValue")),
            "OpenValue": _num(r.get("OpenValue")),
            "OverdueValue": _num(r.get("OverdueValue")),
        })
    out.sort(key=lambda d: -(d["TotalPurchases"] or 0))
    cols = [
        QueryColumn("ProjectID", "Proj ID", "id", "left"),
        QueryColumn("Project", "Project", "text", "left", wrap=True),
        QueryColumn("POs", "POs", "int", "right"),
        QueryColumn("Lines", "Lines", "int", "right"),
        QueryColumn("TotalPurchases", "Total Purchases", "money", "right"),
        QueryColumn("ReceivedValue", "Received (closed)", "money", "right"),
        QueryColumn("OpenValue", "Open", "money", "right"),
        QueryColumn("OverdueValue", "Overdue", "money", "right"),
    ]
    total = sum(x["TotalPurchases"] or 0 for x in out)
    opn = sum(x["OpenValue"] or 0 for x in out)
    rcv = sum(x["ReceivedValue"] or 0 for x in out)
    od = sum(x["OverdueValue"] or 0 for x in out)
    cards = [Card(L("projects"), str(len(out))),
             Card("Total purchases", _fmt_money2(total)),
             Card("Received (closed)", _fmt_money2(rcv)),
             Card("Open", _fmt_money2(opn)),
             Card("Overdue", _fmt_money2(od), "bad" if od else "good")]
    note = ("All purchase-order lines per project — closed (received) and open — with total "
            "purchases, the open portion and the overdue portion. Committed value in Canadian "
            "dollars." + (window_label or ""))
    return QueryResult("po_all", "Purchasing — PO Report (all purchases)", cols, out, cards, note)


def _po_window_label(dfrom, dto):
    """Subtitle fragment naming the PO-placed window (blank when unbounded)."""
    if not dfrom and not dto:
        return ""
    lo = dfrom.strftime("%b %d, %Y") if dfrom else "project start"
    hi = dto.strftime("%b %d, %Y") if dto else "today"
    return f"  ·  orders placed {lo} – {hi}"


def _po_buyer_result(rows, window_label=""):
    out = []
    for r in rows:
        out.append({
            "Buyer": r.get("Buyer") or "(unassigned)",
            "POs": _int(r.get("POs")),
            "Lines": _int(r.get("Lines")),
            "ExtValue": _num(r.get("ExtValue")),
            "OpenLines": _int(r.get("OpenLines")),
            "OverdueLines": _int(r.get("OverdueLines")),
            "OverdueValue": _num(r.get("OverdueValue")),
        })
    out.sort(key=lambda d: (-(d["OverdueValue"] or 0), -(d["ExtValue"] or 0)))
    cols = [
        QueryColumn("Buyer", "Buyer", "text", "left", wrap=True),
        QueryColumn("POs", "POs", "int", "right"),
        QueryColumn("Lines", "Lines", "int", "right"),
        QueryColumn("ExtValue", "Committed $", "money", "right"),
        QueryColumn("OpenLines", "Open Lines", "int", "right"),
        QueryColumn("OverdueLines", "Overdue Lines", "int", "right"),
        QueryColumn("OverdueValue", "Overdue $", "money", "right"),
    ]
    committed = sum(x["ExtValue"] or 0 for x in out)
    od_val = sum(x["OverdueValue"] or 0 for x in out)
    od_lines = sum(x["OverdueLines"] or 0 for x in out)
    cards = [Card("Buyers", str(len(out))),
             Card("Committed", _fmt_money2(committed)),
             Card("Overdue lines", "{:,}".format(od_lines), "bad" if od_lines else "good"),
             Card("Overdue value", _fmt_money2(od_val), "bad" if od_val else "good")]
    note = ("Purchasing workload by buyer — purchase orders, lines and committed value (CAD), "
            "with the open and overdue portion for each buyer." + (window_label or ""))
    return QueryResult("po_buyer", "Purchasing — By Buyer", cols, out, cards, note)


# ---- Purchasing — Lines to Order (draft POs not yet issued) ---------------
def _mc_label(mc):
    """SpecID (float) → a clean machine label, matching the PO Status grouping."""
    try:
        f = float(mc)
        return str(int(f)) if f.is_integer() else str(f)
    except (TypeError, ValueError):
        return str(mc)


def _po_to_order_rows(df):
    """Grouped rows (project → machine → line) with subtotal bands, as _kind-tagged dicts
    (the same band convention the other grouped reports use)."""
    if df is None or df.empty:
        return []
    rows, total = [], 0.0
    for pid in sorted(df["ProjectID"].dropna().unique(), key=lambda x: int(x)):
        psub = df[df["ProjectID"] == pid]
        job = _s(psub["JobName"].iloc[0]) if "JobName" in psub.columns else ""
        cust = psub["Customer"].iloc[0] if "Customer" in psub.columns else ""
        head = f"Project: {int(pid)} — {job or ''}".rstrip(" —")
        if cust:
            head += f"   ·   {cust}"
        rows.append({"_kind": "l3_sub", "Item": head})
        for mc in sorted(psub["MachineCode"].dropna().unique(), key=str):
            msub = psub[psub["MachineCode"] == mc]
            rows.append({"_kind": "l2_sub", "Item": f"Machine {_mc_label(mc)}"})
            for _, r in msub.iterrows():
                rows.append({
                    "_kind": "detail",
                    "Item": _int(r.get("Item")), "Description": r.get("Description"),
                    "PO": _int(r.get("PO")), "Supplier": r.get("Supplier"),
                    "Buyer": r.get("Buyer"), "Curr": r.get("Curr"),
                    "Qty": _num(r.get("Qty")), "Price": _num(r.get("Price")),
                    "ExtValueCAD": _num(r.get("ExtValueCAD")),
                    "Required": (str(r.get("Required")) if r.get("Required") not in (None, "") else None),
                    "Entered": (str(r.get("Entered")) if r.get("Entered") not in (None, "") else None),
                    "AgeDays": _int(r.get("AgeDays")),
                })
        psum = float(psub["ExtValueCAD"].fillna(0).sum())
        total += psum
        rows.append({"_kind": "l1_sub", "Description": f"Project {int(pid)} — To-Order Value",
                     "ExtValueCAD": round(psum, 2)})
    rows.append({"_kind": "grand", "Item": "GRAND TOTAL — To-Order Value",
                 "ExtValueCAD": round(total, 2)})
    return rows


def _po_to_order_result(df, window_label=""):
    proj = L("project")
    cols = [
        QueryColumn("Item", "Item", "id", "left"),
        QueryColumn("Description", "Description", "text", "left", wrap=True),
        QueryColumn("PO", "PO #", "id", "left"),
        QueryColumn("Supplier", "Supplier", "text", "left", wrap=True),
        QueryColumn("Buyer", "Buyer", "text", "left"),
        QueryColumn("Curr", "Curr", "text", "left"),
        QueryColumn("Qty", "Qty", "num", "right"),
        QueryColumn("Price", "Unit Price", "num", "right"),
        QueryColumn("ExtValueCAD", "Ext. Value (CAD)", "money", "right"),
        QueryColumn("Required", "Need-by", "date", "left"),
        QueryColumn("Entered", "PO Entered", "date", "left"),
        QueryColumn("AgeDays", "Age (days)", "days", "right"),
    ]
    empty = df is None or df.empty
    n = 0 if empty else int(len(df))
    val = 0.0 if empty else float(df["ExtValueCAD"].fillna(0).sum())
    stale = 0 if empty else int((df["AgeDays"].fillna(0) > 90).sum())
    cards = [Card("Lines to order", "{:,}".format(n)),
             Card("To-order value", _fmt_money2(val)),
             Card("Stale (>90d)", "{:,}".format(stale), "warn" if stale else "good")]
    note = ("Purchase-order lines entered in ETO but not yet issued to the vendor — the PO "
            "has not been printed or emailed, so it is still to be placed. Grouped by "
            f"{proj.lower()} then machine/spec (ETO SpecID). Ext. Value is in Canadian dollars; "
            "Age is days since the PO was entered — a large age flags a draft to review or "
            "cancel." + (window_label or ""))
    return QueryResult("po_to_order", "Purchasing — Lines to Order", cols,
                       _po_to_order_rows(df), cards, note)


# ---- Inventory — Item Location (on-hand by item & location, project-scoped) ----
def _item_location_rows(df):
    """Grouped rows (project → stocked line) with a per-project count band. No numeric
    subtotal — on-hand quantities are mixed units of measure, so summing is meaningless."""
    if df is None or df.empty:
        return []
    rows, total = [], 0
    for pid in sorted(df["ProjectID"].dropna().unique(), key=lambda x: int(x)):
        psub = df[df["ProjectID"] == pid]
        job = _s(psub["JobName"].iloc[0]) if "JobName" in psub.columns else ""
        head = f"Project: {int(pid)} — {job or ''}".rstrip(" —")
        rows.append({"_kind": "l3_sub", "ItemNo": head})
        for _, r in psub.iterrows():
            rows.append({
                "_kind": "detail",
                "ItemNo": r.get("ItemNo"), "Description": r.get("Description"),
                "Location": r.get("Location"), "Bin": r.get("Bin"),
                "OnHand": _num(r.get("OnHand")), "MinReq": _num(r.get("MinReq")),
            })
        total += len(psub)
        rows.append({"_kind": "l1_sub", "Description":
                     f"Project {int(pid)} — {len(psub)} stocked line(s), "
                     f"{psub['ItemNo'].nunique()} item(s) across {psub['Location'].nunique()} location(s)"})
    rows.append({"_kind": "grand", "ItemNo": f"GRAND TOTAL — {total} stocked line(s)"})
    return rows


def _item_location_result(df):
    proj = L("project")
    cols = [
        QueryColumn("ItemNo", "Item", "id", "left"),
        QueryColumn("Description", "Description", "text", "left", wrap=True),
        QueryColumn("Location", "Location", "text", "left"),
        QueryColumn("Bin", "Bin", "text", "left"),
        QueryColumn("OnHand", "On Hand", "num", "right"),
        QueryColumn("MinReq", "Min Req", "num", "right"),
    ]
    empty = df is None or df.empty
    lines = 0 if empty else int(len(df))
    items = 0 if empty else int(df["ItemNo"].nunique())
    locs = 0 if empty else int(df["Location"].nunique())
    cards = [Card("Stocked lines", "{:,}".format(lines)),
             Card("Distinct items", "{:,}".format(items)),
             Card("Locations", "{:,}".format(locs))]
    note = (f"Current on-hand inventory for the items purchased on the selected {proj.lower()}s, "
            "by item and location (live from ETO). On-hand is SHARED stock — not reserved to a "
            f"{proj.lower()}, so an item used on more than one {proj.lower()} appears under each. "
            "Only items with on-hand > 0 are listed; Bin is the sub-location where recorded.")
    return QueryResult("item_location", "Inventory — Item Location", cols,
                       _item_location_rows(df), cards, note)


# ---- Inventory — On-Hand Value (extended value by item & location, project-scoped) ----
def _inventory_value_rows(df):
    """Grouped project → location → line, with per-location value bands (the by-location summary),
    a per-project value subtotal and a grand total. Value IS summable (unlike raw on-hand qty)."""
    if df is None or df.empty:
        return []
    rows, gtot = [], 0.0
    for pid in sorted(df["ProjectID"].dropna().unique(), key=lambda x: int(x)):
        psub = df[df["ProjectID"] == pid]
        job = _s(psub["JobName"].iloc[0]) if "JobName" in psub.columns else ""
        rows.append({"_kind": "l3_sub",
                     "ItemNo": f"Project: {int(pid)} — {job or ''}".rstrip(" —")})
        pval = 0.0
        for loc in sorted(psub["Location"].dropna().unique(), key=str):
            lsub = psub[psub["Location"] == loc]
            lval = float(lsub["ExtValue"].fillna(0).sum())
            pval += lval
            rows.append({"_kind": "l2_sub",
                         "ItemNo": f"{loc} — {len(lsub)} line(s), {lsub['ItemNo'].nunique()} item(s)",
                         "ExtValue": round(lval, 2)})
            for _, r in lsub.iterrows():
                rows.append({
                    "_kind": "detail",
                    "ItemNo": r.get("ItemNo"), "Description": r.get("Description"),
                    "Bin": r.get("Bin"), "OnHand": _num(r.get("OnHand")),
                    "ExtValue": _num(r.get("ExtValue")),
                })
        gtot += pval
        rows.append({"_kind": "l1_sub", "Description": f"Project {int(pid)} — on-hand value",
                     "ExtValue": round(pval, 2)})
    rows.append({"_kind": "grand", "ItemNo": "GRAND TOTAL — on-hand value",
                 "ExtValue": round(gtot, 2)})
    return rows


def _inventory_value_result(df):
    proj = L("project")
    cols = [
        QueryColumn("ItemNo", "Item", "id", "left"),
        QueryColumn("Description", "Description", "text", "left", wrap=True),
        QueryColumn("Bin", "Bin", "text", "left"),
        QueryColumn("OnHand", "On Hand", "num", "right"),
        QueryColumn("ExtValue", "Ext. Value", "money", "right"),
    ]
    empty = df is None or df.empty
    lines = 0 if empty else int(len(df))
    items = 0 if empty else int(df["ItemNo"].nunique())
    locs = 0 if empty else int(df["Location"].nunique())
    val = 0.0 if empty else float(df["ExtValue"].fillna(0).sum())
    uncosted = 0 if empty else int(df["ExtValue"].isna().sum())
    cards = [Card("On-hand value", _fmt_money2(val)),
             Card("Stocked lines", "{:,}".format(lines)),
             Card("Distinct items", "{:,}".format(items)),
             Card("Locations", "{:,}".format(locs))]
    note = (f"On-hand inventory value for the items purchased on the selected {proj.lower()}s, by "
            "item and location, grouped by location (live from ETO). Extended value is ETO's "
            "purchased-material carrying cost from receipt layers (tblInventoryDetails: quantity × "
            "purchase price) — the same basis consumed into material costs, so it reconciles. "
            "On-hand is SHARED stock, not reserved to a "
            f"{proj.lower()} — an item on more than one {proj.lower()} appears under each. "
            + (f"{uncosted:,} line(s) are made-to-{proj.lower()} or adjusted stock without a "
               "purchase-price layer, so they show on-hand quantity but no purchased-material "
               "value. " if uncosted else "")
            + "Only items with on-hand > 0 are listed.")
    return QueryResult("inventory_value", "Inventory — On-Hand Value", cols,
                       _inventory_value_rows(df), cards, note)


# ---- Inventory — By Site (portfolio-wide on-hand value by location) ----
def _inventory_by_site_rows(df):
    """One row per site (location) with lines, items and on-hand value, plus a grand total.
    Portfolio-wide — the whole shared stock pool, not project-scoped."""
    if df is None or df.empty:
        return []
    rows, tot_val, tot_lines = [], 0.0, 0
    for _, r in df.iterrows():
        rows.append({
            "_kind": "detail",
            "Location": r.get("Location"), "Lines": _int(r.get("Lines")),
            "Items": _int(r.get("Items")), "Value": _num(r.get("Value")),
        })
        tot_val += float(r.get("Value") or 0)
        tot_lines += int(r.get("Lines") or 0)
    rows.append({"_kind": "grand", "Location": "GRAND TOTAL — all sites",
                 "Lines": tot_lines, "Value": round(tot_val, 2)})
    return rows


def _inventory_by_site_result(df):
    cols = [
        QueryColumn("Location", "Site", "text", "left"),
        QueryColumn("Lines", "Stocked Lines", "num", "right"),
        QueryColumn("Items", "Distinct Items", "num", "right"),
        QueryColumn("Value", "On-Hand Value", "money", "right"),
    ]
    empty = df is None or df.empty
    sites = 0 if empty else int(len(df))
    lines = 0 if empty else int(df["Lines"].fillna(0).sum())
    val = 0.0 if empty else float(df["Value"].fillna(0).sum())
    uncosted = 0 if empty else int(df["Uncosted"].fillna(0).sum()) if "Uncosted" in df.columns else 0
    cards = [Card("Total on-hand value", _fmt_money2(val)),
             Card("Sites", "{:,}".format(sites)),
             Card("Stocked lines", "{:,}".format(lines))]
    note = ("On-hand inventory value across all sites — the whole SHARED stock pool (not scoped to "
            "a project). Extended value is ETO's purchased-material carrying cost from receipt "
            "layers (tblInventoryDetails: quantity × purchase price), the same basis as material "
            "costs. In-transit locations appear as their own rows whenever stock is mid-move "
            "between sites. "
            + (f"{uncosted:,} stocked line(s) across all sites are made-to-project or adjusted "
               "stock without a purchase-price layer, so their quantity is on hand but not valued "
               "as purchased material. " if uncosted else "")
            + "Only items with on-hand > 0 are counted.")
    return QueryResult("inventory_by_site", "Inventory — By Site", cols,
                       _inventory_by_site_rows(df), cards, note)


# ---- Shipping — Packing Slips (shipped lines by slip, project-scoped) ----
def _s(v):
    """Safe display string: blank for None / NaN / NaT. A pandas NULL is a truthy float NaN (and a
    null datetime is NaT), which defeats `x or ''` / `if x:` guards and would leak the literal
    'nan'/'NaT' into composed band text. Belt-and-suspenders: also blank any value that stringifies
    to a null sentinel, whatever its source."""
    if v is None:
        return ""
    try:
        if v != v:                      # NaN / NaT — the only values not equal to themselves
            return ""
    except (TypeError, ValueError):
        pass
    s = str(v).strip()
    return "" if s.lower() in ("nan", "nat", "none", "<na>", "nattype") else s


def _spec_label(v):
    """SpecID reads as a float (e.g. 10.0); show the whole-number machine code ('' if blank)."""
    s = _s(v)
    if not s:
        return ""
    try:
        f = float(s)
        return str(int(f)) if f == int(f) else str(f)
    except (TypeError, ValueError):
        return s


def _place(company, city):
    """Concise 'place' label: shorten the (many) Macrodyne legal names to 'Macrodyne', append the
    city when present. Blank if both are null."""
    c, ct = _s(company), _s(city)
    if not c and not ct:
        return ""
    if "macrodyne" in c.lower():
        c = "Macrodyne"
    return f"{c} ({ct})" if (c and ct) else (c or ct)


def _is_internal(r):
    """Macrodyne → Macrodyne = an internal site-to-site transfer (vs a customer shipment)."""
    return "macrodyne" in _s(r.get("ShipTo")).lower()


def _packslip_band(r):
    """One-line header band for a packing slip: number · type · status+date · From → To · route type.
    Every field goes through _s() so a NULL (pandas NaN) never renders as 'nan'."""
    no = _s(r.get("SlipNo"))
    typ = _s(r.get("SlipType"))
    shipped = r.get("Shipped") is True or r.get("Shipped") == 1
    packed = r.get("Packed") is True or r.get("Packed") == 1
    status = "Shipped" if shipped else ("Packed" if packed else "Open")
    dstr = (_s(r.get("ShippedDate")) or _s(r.get("CreatedDate")))[:10]
    parts = [f"Slip {no}" if no else "Slip"]
    if typ:
        parts.append(typ)
    parts.append(status + (f" {dstr}" if dstr else ""))
    frm = _place(r.get("ShipFrom"), r.get("FromCity"))
    to = _place(r.get("ShipTo"), r.get("ToCity"))
    if frm or to:
        parts.append(f"{frm or '?'} → {to or '?'}")
    parts.append("internal transfer" if _is_internal(r) else "customer shipment")
    shipper = _s(r.get("Shipper"))
    if shipper:
        parts.append(f"via {shipper}")
    return "   ·   ".join(parts)


def _packing_slip_rows(df):
    """Grouped rows (project → packing slip → shipped line) with bands. Line counts only —
    shipped quantities are mixed units of measure, so no numeric total (as with Item Location)."""
    if df is None or df.empty:
        return []
    rows, total = [], 0
    for pid in sorted(df["ProjectID"].dropna().unique(), key=lambda x: int(x)):
        psub = df[df["ProjectID"] == pid]
        job = _s(psub["JobName"].iloc[0]) if "JobName" in psub.columns else ""
        head = f"Project: {int(pid)} — {job or ''}".rstrip(" —")
        rows.append({"_kind": "l3_sub", "Item": head})
        seen = []
        for sid in psub["PackingSlipID"]:
            if sid not in seen:
                seen.append(sid)
        for sid in seen:
            ssub = psub[psub["PackingSlipID"] == sid]
            rows.append({"_kind": "l2_sub", "Item": _packslip_band(ssub.iloc[0])})
            for _, r in ssub.iterrows():
                rows.append({
                    "_kind": "detail",
                    "Item": r.get("ItemNo"), "Description": r.get("Description"),
                    "Machine": _spec_label(r.get("Machine")), "Category": r.get("Category"),
                    "Qty": _num(r.get("Qty")),
                })
        total += len(psub)
        rows.append({"_kind": "l1_sub", "Description":
                     f"Project {int(pid)} — {psub['PackingSlipID'].nunique()} packing slip(s), "
                     f"{len(psub)} line(s), {psub['ItemNo'].nunique()} item(s)"})
    rows.append({"_kind": "grand", "Item": f"GRAND TOTAL — {total} shipped line(s)"})
    return rows


def _packing_slip_result(df):
    proj = L("project")
    cols = [
        QueryColumn("Item", "Item", "id", "left"),
        QueryColumn("Description", "Description", "text", "left", wrap=True),
        QueryColumn("Machine", "Machine", "id", "left"),
        QueryColumn("Category", "Category", "text", "left"),
        QueryColumn("Qty", "Qty", "num", "right"),
    ]
    empty = df is None or df.empty
    slips = 0 if empty else int(df["PackingSlipID"].nunique())
    lines = 0 if empty else int(len(df))
    items = 0 if empty else int(df["ItemNo"].nunique())
    if empty:
        shipped = internal = 0
    else:
        mask = df["Shipped"].map(lambda v: v is True or v == 1)
        shipped = int(df.loc[mask, "PackingSlipID"].nunique())
        imask = df["ShipTo"].map(lambda v: "macrodyne" in _s(v).lower()) \
            if "ShipTo" in df.columns else df["PackingSlipID"].map(lambda v: False)
        internal = int(df.loc[imask, "PackingSlipID"].nunique())
    cards = [Card("Packing slips", "{:,}".format(slips)),
             Card("Internal transfers", "{:,}".format(internal),
                  "neutral"),
             Card("Distinct items", "{:,}".format(items)),
             Card("Slips shipped", "{:,}".format(shipped),
                  "good" if slips and shipped == slips else "neutral")]
    note = (f"Packing slips for the selected {proj.lower()}s — one band per slip (number, type, "
            "status, ship date, From → To and route type) with the lines shipped, live from ETO "
            f"(vwPackingSlips_SearchResults). Grouped by {proj.lower()} then slip. From → To is the "
            "physical ship-from and ship-to on the slip; a Macrodyne → Macrodyne route is an "
            "INTERNAL site-to-site transfer, anything else is a customer shipment (that split is "
            "the inventory-transfer view ETO's StockTransfer flag couldn't provide). Quantities are "
            "per slip line and are not summed (mixed units of measure). Machine is the ETO SpecID.")
    return QueryResult("packing_slip", "Shipping — Packing Slips", cols,
                       _packing_slip_rows(df), cards, note)


# ---- Non-Conformance (costed + attributed) -------------------------------
# One scoped source feeds every NC report: vwNonConformances LEFT JOIN
# vwCostingSummed_ByNC (+ origin department) — a transcription of ETO's
# urpNonConformancesWithCosts (verified 2026-07-26). Rows are ncspec-normalized
# dicts, shared with the demo backend. Labour books $0 at Macrodyne (no rework time
# attributed to NCs); cost is purchased material + inventory + extra/payables.

_NC_COST_NOTE = (
    "Cost of non-conformance is the total cost tied to each NCR — labour, plus material "
    "(purchased and from stock), plus other costs. Labour currently shows $0 because rework "
    "time isn't recorded against NCRs today, so the figure reflects replacement material and "
    "related purchases. Discipline is inferred from the type of fault; Department is the "
    "responsible area recorded against it.")


def _live_nc_cost_rows(cur, pids, dfrom, dto):
    """Fetch + normalize the costed NC rows, with best-effort corrective-action counts."""
    cur.execute(ncspec.sql_nc_costs(_ids_sql(pids)))
    cols = [d[0] for d in cur.description]
    recs = [dict(zip(cols, r)) for r in cur.fetchall()]
    rows = ncspec.to_rows(recs, dfrom, dto)
    try:  # Outstanding corrective-actions live on a separate view — tolerate its absence
        cur.execute(ncspec.sql_nc_outstanding(_ids_sql(pids)))
        ocols = [d[0] for d in cur.description]
        obync = {}
        for r in cur.fetchall():
            d = dict(zip(ocols, r))
            obync[d.get("NonConformanceID")] = d.get("Outstanding")
        ncspec.attach_outstanding(rows, obync)
    except Exception:
        ncspec.attach_outstanding(rows, {})
    return rows


def _nc_cards(rows):
    t = ncspec.totals(rows)
    return [Card("NCRs", "{:,}".format(t["NCRs"])),
            Card("Open", "{:,}".format(t["Open"]), "bad" if t["Open"] else "good"),
            Card("Cost of NC", _fmt_money2(t["Total"]), "bad" if t["Total"] else "good"),
            Card("Material", _fmt_money2(t["Material"]))]


def _nc_summary_result(rows):
    out = ncspec.by_source(rows)
    cols = [
        QueryColumn("Source", "Source (detected)", "text", "left"),
        QueryColumn("NCRs", "NCRs", "int", "right"),
        QueryColumn("Open", "Open", "int", "right"),
        QueryColumn("Closed", "Closed", "int", "right"),
        QueryColumn("Material", "Material $", "money", "right"),
        QueryColumn("Total", "Cost of NC", "money", "right"),
    ]
    return QueryResult("nc_summary", "Non-Conformance — Summary", cols, out, _nc_cards(rows),
                       "Counts and cost by source (where the NCR was detected). " + _NC_COST_NOTE)


def _nc_costs_result(rows):
    ordered = sorted(rows, key=lambda r: (-r["Total"], r["Status"] != "Open", -(r["NCID"] or 0)))
    cols = [
        QueryColumn("NCR", "NCR", "id", "left"),
        QueryColumn("ProjectID", "Proj ID", "id", "left"),
        QueryColumn("Status", "Status", "text", "left"),
        QueryColumn("Source", "Source", "text", "left"),
        QueryColumn("Origin", "Origin / Root Cause", "text", "left", wrap=True),
        QueryColumn("Discipline", "Discipline", "text", "left"),
        QueryColumn("Department", "Department", "text", "left"),
        QueryColumn("Supplier", "Supplier", "text", "left", wrap=True),
        QueryColumn("Labour", "Labour $", "money", "right"),
        QueryColumn("Purchased", "Purchased $", "money", "right"),
        QueryColumn("Inventory", "Stock $", "money", "right"),
        QueryColumn("Extra", "Other $", "money", "right"),
        QueryColumn("Total", "Total $", "money", "right"),
    ]
    return QueryResult("nc_costs", "Non-Conformance — Costing", cols, ordered, _nc_cards(rows),
                       "One row per NCR, sorted by cost. " + _NC_COST_NOTE)


def _nc_cause_result(rows):
    out = ncspec.by_cause(rows)
    cols = [
        QueryColumn("Origin", "Origin / Root Cause", "text", "left", wrap=True),
        QueryColumn("NCRs", "NCRs", "int", "right"),
        QueryColumn("Open", "Open", "int", "right"),
        QueryColumn("Closed", "Closed", "int", "right"),
        QueryColumn("Labour", "Labour $", "money", "right"),
        QueryColumn("Material", "Material $", "money", "right"),
        QueryColumn("Total", "Total $", "money", "right"),
    ]
    return QueryResult("nc_cause", "Non-Conformance — Cost by Root Cause", cols, out,
                       _nc_cards(rows), "Cost grouped by origin / root cause. " + _NC_COST_NOTE)


def _nc_regroup(items, keyname):
    """Relabel a roll-up's group key to the shared 'Group' column."""
    out = []
    for d in items:
        row = {"Group": d.get(keyname)}
        for k in ("NCRs", "Open", "Closed", "Labour", "Material", "Total"):
            row[k] = d.get(k)
        out.append(row)
    return out


def _nc_discipline_result(rows):
    # Two stacked sections: derived discipline, then ETO responsible department.
    out = ([{"_kind": "section", "Group": "By discipline (derived from origin)"}]
           + _nc_regroup(ncspec.by_discipline(rows), "Discipline")
           + [{"_kind": "section", "Group": "By ETO responsible department"}]
           + _nc_regroup(ncspec.by_department(rows), "Department"))
    cols = [
        QueryColumn("Group", "Discipline / Department", "text", "left"),
        QueryColumn("NCRs", "NCRs", "int", "right"),
        QueryColumn("Open", "Open", "int", "right"),
        QueryColumn("Closed", "Closed", "int", "right"),
        QueryColumn("Labour", "Labour $", "money", "right"),
        QueryColumn("Material", "Material $", "money", "right"),
        QueryColumn("Total", "Total $", "money", "right"),
    ]
    return QueryResult("nc_discipline", "Non-Conformance — By Discipline / Department", cols, out,
                       _nc_cards(rows),
                       "Cost attributed to a discipline (inferred from the type of fault) and "
                       "to the responsible department. " + _NC_COST_NOTE)


def _nc_supplier_result(rows):
    out = ncspec.by_supplier(rows)
    cols = [
        QueryColumn("Supplier", "Supplier", "text", "left", wrap=True),
        QueryColumn("NCRs", "NCRs", "int", "right"),
        QueryColumn("Open", "Open", "int", "right"),
        QueryColumn("Closed", "Closed", "int", "right"),
        QueryColumn("Material", "Material $", "money", "right"),
        QueryColumn("Total", "Total $", "money", "right"),
    ]
    return QueryResult("nc_supplier", "Non-Conformance — By Supplier", cols, out, _nc_cards(rows),
                       "Vendor attribution (supplier is set on PO-linked NCRs; internal NCRs "
                       "group as 'no supplier'). " + _NC_COST_NOTE)


def _nc_impact_result(rows, material_by_pid=None):
    out = ncspec.impact(rows, material_by_pid or {})
    cols = [
        QueryColumn("ProjectID", "Proj ID", "id", "left"),
        QueryColumn("NCRs", "NCRs", "int", "right"),
        QueryColumn("Open", "Open", "int", "right"),
        QueryColumn("Closed", "Closed", "int", "right"),
        QueryColumn("NCCost", "Cost of NC", "money", "right"),
        QueryColumn("MaterialActual", "Material Actual", "money", "right"),
        QueryColumn("NCPctOfMaterial", "NC % of Material", "pct", "right"),
    ]
    return QueryResult("nc_impact", "Non-Conformance — Project Impact", cols, out, _nc_cards(rows),
                       "Per-project cost of non-conformance and its share of material actual "
                       "spend. " + _NC_COST_NOTE)


def _nc_detail_result(rows):
    ordered = sorted(rows, key=lambda r: (r["Status"] != "Open", -(r["NCID"] or 0)))
    cols = [
        QueryColumn("NCR", "NCR", "id", "left"),
        QueryColumn("ProjectID", "Proj ID", "id", "left"),
        QueryColumn("Status", "Status", "text", "left"),
        QueryColumn("Source", "Source", "text", "left"),
        QueryColumn("Origin", "Origin", "text", "left", wrap=True),
        QueryColumn("Discipline", "Discipline", "text", "left"),
        QueryColumn("Department", "Department", "text", "left"),
        QueryColumn("Part", "Part", "text", "left"),
        QueryColumn("Supplier", "Supplier", "text", "left", wrap=True),
        QueryColumn("PO", "PO", "id", "left"),
        QueryColumn("Raised", "Raised", "date", "left"),
        QueryColumn("Closed", "Closed", "date", "left"),
        QueryColumn("Outstanding", "Open Actions", "int", "right"),
        QueryColumn("Total", "Cost $", "money", "right"),
        QueryColumn("RootCause", "Root Cause", "text", "left", wrap=True),
        QueryColumn("CAPA", "Corrective / Preventive Action", "text", "left", wrap=True),
    ]
    openn = sum(1 for r in rows if r.get("Status") == "Open")
    outstanding = sum(int(r.get("Outstanding") or 0) for r in rows)
    cards = [Card("NCRs", "{:,}".format(len(rows))),
             Card("Open", str(openn), "bad" if openn else "good"),
             Card("Open action items", str(outstanding), "bad" if outstanding else "good"),
             Card("Cost of NC", _fmt_money2(ncspec.totals(rows)["Total"]))]
    return QueryResult("nc_detail", "Non-Conformance — Detail", cols, ordered, cards,
                       "Not every NCR is linked to a purchase order. Open action items = "
                       "outstanding corrective-action tasks across these NCRs — one NCR can have "
                       "several, so this total is action items, not NCRs, and can exceed the NCR "
                       "count. " + _NC_COST_NOTE)


def _fmt_hours(v):
    return "{:,.0f}".format(v or 0)


def _clean_client(s):
    """Trim ETO customer decorations, e.g. 'ACME Corp [Detroit] (Approved)' -> 'ACME Corp'."""
    if not s:
        return None
    s = str(s)
    for sep in (" [", " ("):
        i = s.find(sep)
        if i != -1:
            s = s[:i]
    return s.strip() or None


# ─────────────────────────────────────────────────────────────────────────────
# Demo backend — canned, DB-free (validated Macrodyne figures)
# ─────────────────────────────────────────────────────────────────────────────
_DEMO = {
    230219: {"lb": 8429.0, "la": 10528.0, "mb": 2596000.0, "ma": 2393609.47,
             "lc": 1000160.0, "sp": 4320000.0, "sm": 0.22,
             "done": 0.93, "runout": 1.25, "rank": 1, "ship": "2026-09-18",
             "disc": {"Project Management": (642.0, 588.0),
                      "Mechanical Engineering": (2140.0, 2760.0),
                      "Electrical Engineering": (1180.0, 1395.0),
                      "Hydraulic Engineering": (960.0, 1004.0),
                      "Manufacturing": (3200.0, 4471.0),
                      "Other": (307.0, 310.0)}},
    230312: {"lb": 6120.0, "la": 5488.0, "mb": 1840000.0, "ma": 1502233.10,
             "lc": 504896.0, "sp": 2900000.0, "sm": 0.20,
             "done": 0.78, "runout": 0.91, "rank": 3, "ship": "2026-11-06",
             "disc": {"Project Management": (410.0, 366.0),
                      "Mechanical Engineering": (1680.0, 1512.0),
                      "Electrical Engineering": (900.0, 848.0),
                      "Hydraulic Engineering": (720.0, 690.0),
                      "Manufacturing": (2210.0, 1876.0),
                      "Other": (200.0, 196.0)}},
    240087: {"lb": 4980.0, "la": 2210.0, "mb": 1310000.0, "ma": 402881.55,
             "lc": 198900.0, "sp": 2200000.0, "sm": 0.25,
             "done": 0.41, "runout": 0.88, "rank": 5, "ship": "2027-02-19",
             "disc": {"Project Management": (330.0, 150.0),
                      "Mechanical Engineering": (1400.0, 640.0),
                      "Electrical Engineering": (760.0, 300.0),
                      "Hydraulic Engineering": (600.0, 250.0),
                      "Manufacturing": (1720.0, 810.0),
                      "Other": (170.0, 60.0)}},
}
_DEMO_XWALK = {
    "Project Management": "Project Management", "Project Coordination": "Project Management",
    "Electrical Procurement": "Project Management",
    "Mechanical Design": "Mechanical Engineering", "Mechanical Detailing": "Mechanical Engineering",
    "Electrical Design": "Electrical Engineering", "Controls": "Electrical Engineering",
    "Hydraulic Design": "Hydraulic Engineering", "Hydraulic Field Service": "Manufacturing",
    "Assembly": "Manufacturing", "Machining": "Manufacturing", "Welding": "Manufacturing",
    "Commissioning": "Other", "Documentation": "Other",
}

# Rework / NC (task 999) labour by project → discipline — actual-only, no budget.
# {pid: {discipline: (hours, applied-rate cost)}}. Must be ≤ the demo disc actual so planned ≥ 0.
_DEMO_REWORK = {
    230219: {"Mechanical Engineering": (60.0, 5100.0), "Electrical Engineering": (18.0, 1530.0),
             "Manufacturing": (67.0, 5360.0)},
    230312: {"Mechanical Engineering": (12.0, 1020.0)},
}

# Declared % complete per discipline (0–1) — the ONE judgement; run-out is derived from it.
_DEMO_PROGRESS = {
    230219: {"Project Management": 0.95, "Mechanical Engineering": 0.88,
             "Electrical Engineering": 0.90, "Hydraulic Engineering": 0.92,
             "Manufacturing": 0.80, "Other": 0.85},
    230312: {"Project Management": 0.80, "Mechanical Engineering": 0.75,
             "Electrical Engineering": 0.78, "Hydraulic Engineering": 0.82,
             "Manufacturing": 0.60, "Other": 0.70},
    240087: {"Project Management": 0.50, "Mechanical Engineering": 0.40,
             "Electrical Engineering": 0.42, "Hydraulic Engineering": 0.45,
             "Manufacturing": 0.30, "Other": 0.35},
}
# Committed material POs (received + open), CAD — the Carpedia material run-out basis.
# 230219 committed > budget (over → run-out >100%); the others under (floored at 100%).
_DEMO_COMMITTED = {230219: 2700000.0, 230312: 1600000.0, 240087: 500000.0}


def _demo_rollup_pct(pid):
    """Demo project %C = hours-weighted roll-up of _DEMO_PROGRESS over the discipline budgets."""
    prog = _DEMO_PROGRESS.get(pid, {})
    num = den = 0.0
    for disc, (b, _a) in _DEMO[pid]["disc"].items():
        if not b or b <= 0:
            continue
        p = prog.get(disc)
        num += b * (float(p) if p is not None else 0.0)
        den += b
    return round(num / den, 4) if den else None


# Executive-board extras for the demo (schedule/2-wk/procurement — the manual overlay)
_DEMO_EXEC = {
    230219: {"name": "3000T Hydraulic Press", "client": "Nucor Steel", "po": "2026-09-04",
             "planned": "2026-10-02", "mat_runout": 1.08, "done_delta": 0.04, "lab2wk": 214,
             "mat2wk": 61000, "proc": (612, 44, 3, 5, 2, 9, 4)},
    230312: {"name": "1600T Trim Press Line", "client": "Magna International", "po": "2026-10-23",
             "planned": "2026-11-06", "mat_runout": 0.94, "done_delta": 0.06, "lab2wk": 176,
             "mat2wk": 38500, "proc": (488, 31, 0, 1, 0, 4, 2)},
    240087: {"name": "800T Forming Cell", "client": "Alcoa", "po": "2027-02-05",
             "planned": "2027-02-05", "mat_runout": 0.90, "done_delta": 0.05, "lab2wk": 132,
             "mat2wk": 20100, "proc": (395, 22, 0, 0, 0, 1, 0)},
}
_PROC_KEYS = ["TotalLineItems", "LLTPOrdered", "LLTPRelLate", "LLTPOrdLate",
              "LLTPDelLate", "PartsRelLate", "PartsOrdLate"]


class DemoQueryService(QueryService):
    def list_projects(self):
        return [{"id": pid, "label": str(pid), "ship": d["ship"]}
                for pid, d in sorted(_DEMO.items())]

    def _q_exec(self, project_ids, **kw):
        rows = []
        for pid in self._sel(project_ids):
            d, e = _DEMO[pid], _DEMO_EXEC[pid]
            f = _DemoFin(d)
            prw = _DEMO_REWORK.get(pid, {})
            disc_pct = {disc: (round((a - prw.get(disc, (0.0, 0.0))[0]) / b, 4) if b else None)
                        for disc, (b, a) in d["disc"].items()}
            rec = {"Rank": d["rank"], "POShipDate": e["po"], "CustAgreedDate": d["ship"],
                   "PlannedShipDate": e["planned"],
                   "PctDone": _demo_rollup_pct(pid),          # calculated roll-up (was d["done"])
                   "MaterialCommittedFull": _DEMO_COMMITTED.get(pid),  # material run-out basis
                   "PctDoneDelta": e["done_delta"], "LabHrs2wk": e["lab2wk"],
                   "MatSpend2wk": e["mat2wk"]}
            rec.update(dict(zip(_PROC_KEYS, e["proc"])))
            g = _demo_nc_by_project().get(pid, {})
            rec["NCOpen"], rec["NCCost"] = g.get("open"), g.get("cost")
            rows.append(_exec_row(pid, e["name"], e["client"], f, rec, disc_pct))
        return _finalize_exec(rows)

    def _sel(self, project_ids):
        pids = [int(p) for p in project_ids] or list(_DEMO)
        return [p for p in sorted(pids) if p in _DEMO]

    def _q_scorecard(self, project_ids, **kw):
        rows = []
        for pid in self._sel(project_ids):
            d = _DEMO[pid]
            f = _DemoFin(d)
            # % Done is now the calculated roll-up of per-discipline %C; material run-out is
            # computed from committed POs. No manual overrides in the demo (all Carpedia-computed).
            rec = {"PctDone": _demo_rollup_pct(pid), "Rank": d["rank"], "CustAgreedDate": d["ship"],
                   "MaterialCommittedFull": _DEMO_COMMITTED.get(pid)}
            g = _demo_nc_by_project().get(pid, {})
            rec["NCOpen"], rec["NCCost"] = g.get("open"), g.get("cost")
            rec["Rework"] = round(sum(h for h, _ in _DEMO_REWORK.get(pid, {}).values()), 2) or None
            rows.append(_scorecard_row(pid, f, rec))
        return _scorecard_result(rows)

    def _q_discipline(self, project_ids, **kw):
        rows = []
        for pid in self._sel(project_ids):
            prw = _DEMO_REWORK.get(pid, {})
            pprog = _DEMO_PROGRESS.get(pid, {})
            for disc, (b, a) in sorted(_DEMO[pid]["disc"].items()):
                rwh, rwc = prw.get(disc, (0.0, 0.0))
                planned = round(a - rwh, 2)
                pct = round(planned / b, 4) if b else None
                rwpct = round(rwh / b, 4) if b else None
                # Run-out from TOTAL actual hours (a) ÷ declared %C (Carpedia EAC).
                pc = pprog.get(disc)
                ro = _ev.compute(b, a, pc)
                rows.append({"ProjectID": pid, "Discipline": disc,
                             "BudgetHours": b, "ActualHours": planned, "ConsumedPct": pct,
                             "PctComplete": pc, "RunoutHours": ro.eac, "RunoutPct": ro.runout_pct,
                             "RemainingHours": round(b - planned, 2),
                             "ReworkHours": round(rwh, 2) or None, "ReworkPct": rwpct,
                             "ReworkCost": round(rwc, 2) or None})
        return _discipline_result(rows)

    def _q_nc_rework(self, project_ids, date_from=None, date_to=None, **kw):
        rw = {pid: {d: list(v) for d, v in _DEMO_REWORK[pid].items()}
              for pid in self._sel(project_ids) if pid in _DEMO_REWORK}
        return _nc_rework_result(rw)

    def _q_nc_dashboard(self, project_ids, date_from=None, date_to=None, **kw):
        ncrows = self._nc_rows(project_ids)
        matnc_pid, matnc_pd = {}, {}
        for r in ncrows:
            pid = int(r["ProjectID"])
            dsc = r.get("Discipline") or "Other"
            c = float(ncspec._material(r) or 0)
            matnc_pid[pid] = matnc_pid.get(pid, 0.0) + c
            dd = matnc_pd.setdefault(pid, {})
            dd[dsc] = dd.get(dsc, 0.0) + c
        # a per-project NC threshold (fraction) to exercise the ⚠ flag in demo; absent → 1%
        thr = {230219: 0.01, 230312: 0.02}
        data = []
        for pid in self._sel(project_ids):
            d = _DEMO[pid]
            f = _DemoFin(d)
            disc_budgets = {disc: b for disc, (b, _a) in d["disc"].items()}
            rework = {disc: tuple(v) for disc, v in _DEMO_REWORK.get(pid, {}).items()}
            data.append(_nc_dash_record(
                pid, f.labour_budget_hours, f.labour_rate, f.material_budget,
                disc_budgets, rework, matnc_pid.get(pid, 0.0),
                matnc_pd.get(pid, {}), thr.get(pid)))
        return _nc_dashboard_result(data)

    def _q_budget_actual(self, project_ids, **kw):
        rows = [_budget_actual_row(pid, _DemoFin(_DEMO[pid])) for pid in self._sel(project_ids)]
        return _budget_actual_result(rows)

    def _q_crosswalk(self, project_ids, **kw):
        rows = [{"HourDescription": hd, "Discipline": disc}
                for hd, disc in sorted(_DEMO_XWALK.items())]
        return _crosswalk_result(rows)

    # -- Labour + Purchasing (canned; the deployed daily reports A–E + PO) ------
    def _demo_labour_df(self, project_ids, lifetime=False):
        import pandas as pd
        sel = set(self._sel(project_ids))
        src = _DEMO_LAB_LIFE if lifetime else _DEMO_LAB_PERIOD
        rows = []
        for rec in src:
            if rec["ProjectID"] not in sel:
                continue
            factor = rec.get("Factor", 1.0)
            hrs = rec["Hours"]
            rows.append({"Department": rec["Department"], "ProjectID": rec["ProjectID"],
                         "JobName": rec["JobName"], "Customer": rec["Customer"],
                         "EmpNo": rec["EmpNo"], "Employee": rec["Employee"],
                         "Category": rec["Category"], "JobDetail": rec.get("JobDetail", ""),
                         "Entries": 1, "Hours": hrs, "OTHours": (hrs if factor > 1 else 0),
                         "LabourCost": round(hrs * rec["Rate"] * factor, 2)})
        cols = ["Department", "ProjectID", "JobName", "Customer", "EmpNo", "Employee",
                "Category", "JobDetail", "Entries", "Hours", "OTHours", "LabourCost"]
        return pd.DataFrame(rows, columns=cols)

    def _labour_demo(self, project_ids, report_id, date_from):
        lifetime = _as_date(date_from) is None      # Start of Project to Date = all history
        df = self._demo_labour_df(project_ids, lifetime=lifetime)
        if report_id == "lab_disc":
            df = _labour_add_discipline(df, _DEMO_XWALK)
        label = ("from project start through Jul 25, 2026 (demo)" if lifetime
                 else "selected window (demo)")
        return _spec_labour_result(report_id, df, label)

    def _q_lab_disc(self, project_ids, date_from=None, date_to=None, **kw):
        return self._labour_demo(project_ids, "lab_disc", date_from)

    def _q_lab_a(self, project_ids, date_from=None, date_to=None, **kw):
        return self._labour_demo(project_ids, "lab_a", date_from)

    def _q_lab_b(self, project_ids, date_from=None, date_to=None, **kw):
        return self._labour_demo(project_ids, "lab_b", date_from)

    def _q_lab_c(self, project_ids, date_from=None, date_to=None, **kw):
        return self._labour_demo(project_ids, "lab_c", date_from)

    def _q_lab_d(self, project_ids, date_from=None, date_to=None, **kw):
        return self._labour_demo(project_ids, "lab_d", date_from)

    def _q_lab_e(self, project_ids, date_from=None, date_to=None, **kw):
        return self._labour_demo(project_ids, "lab_e", date_from)

    def _q_po_status(self, project_ids, date_from=None, date_to=None, **kw):
        import pandas as pd, datetime as _dt
        sel = set(self._sel(project_ids))
        raw = pd.DataFrame([r for r in _DEMO_PO_STATUS if r["ProjectID"] in sel],
                           columns=_DEMO_PO_STATUS_COLS)
        pdf = etospec.po_prep(raw, today=_dt.date(2026, 7, 24))
        return _spec_po_status_result(pdf, "As at Jul 24, 2026 (demo)")

    def _q_po_exceptions(self, project_ids, date_from=None, date_to=None, **kw):
        import pandas as pd, datetime as _dt
        sel = set(self._sel(project_ids))
        raw = pd.DataFrame([r for r in _DEMO_EXC_RAW if r["ProjectID"] in sel],
                           columns=_DEMO_EXC_COLS)
        items = etospec.exc_detail(raw, today=_dt.date(2026, 7, 22))
        return _spec_po_exc_result(items, "As at Jul 22, 2026 (demo)", True)

    def _q_po_late(self, project_ids, date_from=None, date_to=None, **kw):
        import pandas as pd
        sel = set(self._sel(project_ids))
        df = pd.DataFrame([r for r in _DEMO_LATE if r["ProjectID"] in sel], columns=_DEMO_LATE_COLS)
        return _spec_late_result(df, "As at Jul 25, 2026 (demo)")

    def _q_po_delivered(self, project_ids, date_from=None, date_to=None, **kw):
        import pandas as pd
        sel = set(self._sel(project_ids))
        df = pd.DataFrame([r for r in _DEMO_DELIVERED if r["ProjectID"] in sel],
                          columns=_DEMO_DELIVERED_COLS)
        return _spec_delivered_result(df, "POs created — all history (demo)")

    def _nc_rows(self, project_ids):
        sel = set(self._sel(project_ids))
        return [dict(r) for r in _DEMO_NC if r["ProjectID"] in sel]

    def _nc_mat_actuals(self, project_ids):
        return {pid: _DEMO[pid]["ma"] for pid in self._sel(project_ids)}

    def _q_po_all(self, project_ids, date_from=None, date_to=None, **kw):
        sel = set(self._sel(project_ids))
        agg = {}
        for r in _DEMO_PO_STATUS:
            if r["ProjectID"] not in sel:
                continue
            g = agg.setdefault(r["ProjectID"], {"ProjectID": r["ProjectID"], "JobName": r["JobName"],
                               "_pos": set(), "Lines": 0, "TotalPurchases": 0.0,
                               "ReceivedValue": 0.0, "OpenValue": 0.0, "OverdueValue": 0.0})
            g["_pos"].add(r["PO"])
            g["Lines"] += 1
            ext = r["ExtValue"]
            g["TotalPurchases"] += ext
            closed = r["Received"] is not None and r["Received"] >= r["Qty"]
            g["ReceivedValue" if closed else "OpenValue"] += ext
        rows = [{**{k: v for k, v in g.items() if k != "_pos"}, "POs": len(g["_pos"])}
                for g in agg.values()]
        return _po_all_result(rows, " (demo)")

    def _q_po_buyer(self, project_ids, date_from=None, date_to=None, **kw):
        sel = set(self._sel(project_ids))
        agg = {}
        for r in _DEMO_EXC:
            if r["ProjectID"] not in sel:
                continue
            b = agg.setdefault(r["Buyer"], {"Buyer": r["Buyer"], "POs": 0, "Lines": 0,
                               "ExtValue": 0.0, "OpenLines": 0, "OverdueLines": 0,
                               "OverdueValue": 0.0})
            b["POs"] += 1
            b["Lines"] += 1
            b["ExtValue"] += r["ExtValue"]
            b["OpenLines"] += 1
            if r.get("DelLate") == "LATE":
                b["OverdueLines"] += 1
                b["OverdueValue"] += r["ExtValue"]
        return _po_buyer_result(list(agg.values()), " (demo)")

    def _q_po_to_order(self, project_ids, date_from=None, date_to=None, **kw):
        import pandas as pd
        sel = set(self._sel(project_ids))
        recs = [r for r in _DEMO_TOORDER if r["ProjectID"] in sel]
        return _po_to_order_result(pd.DataFrame(recs, columns=_DEMO_TOORDER_COLS), " (demo)")

    def _q_item_location(self, project_ids, **kw):
        import pandas as pd
        sel = set(self._sel(project_ids))
        recs = [r for r in _DEMO_ITEMLOC if r["ProjectID"] in sel]
        return _item_location_result(pd.DataFrame(recs, columns=_DEMO_ITEMLOC_COLS))

    def _q_inventory_value(self, project_ids, **kw):
        import pandas as pd
        sel = set(self._sel(project_ids))
        recs = [r for r in _DEMO_INVVAL if r["ProjectID"] in sel]
        return _inventory_value_result(pd.DataFrame(recs, columns=_DEMO_INVVAL_COLS))

    def _q_inventory_by_site(self, project_ids, **kw):
        import pandas as pd
        return _inventory_by_site_result(pd.DataFrame(_DEMO_BYSITE, columns=_DEMO_BYSITE_COLS))

    def _q_packing_slip(self, project_ids, **kw):
        import pandas as pd
        sel = set(self._sel(project_ids))
        recs = [r for r in _DEMO_PACKSLIP if r["ProjectID"] in sel]
        return _packing_slip_result(pd.DataFrame(recs, columns=_DEMO_PACKSLIP_COLS))

    def _q_nc_summary(self, project_ids, date_from=None, date_to=None, **kw):
        return _nc_summary_result(self._nc_rows(project_ids))

    def _q_nc_costs(self, project_ids, date_from=None, date_to=None, **kw):
        return _nc_costs_result(self._nc_rows(project_ids))

    def _q_nc_cause(self, project_ids, date_from=None, date_to=None, **kw):
        return _nc_cause_result(self._nc_rows(project_ids))

    def _q_nc_discipline(self, project_ids, date_from=None, date_to=None, **kw):
        return _nc_discipline_result(self._nc_rows(project_ids))

    def _q_nc_supplier(self, project_ids, date_from=None, date_to=None, **kw):
        return _nc_supplier_result(self._nc_rows(project_ids))

    def _q_nc_impact(self, project_ids, date_from=None, date_to=None, **kw):
        return _nc_impact_result(self._nc_rows(project_ids), self._nc_mat_actuals(project_ids))

    def _q_nc_detail(self, project_ids, date_from=None, date_to=None, **kw):
        return _nc_detail_result(self._nc_rows(project_ids))


# Canned ETO data for the demo (plausible Macrodyne press-shop figures)
_DEMO_LABOUR = {   # pid -> [(dept, emps, entries, hours, cost)]
    230219: [("Engineering", 42, 610, 5159, 495000.0),
             ("Manufacturing", 63, 1320, 4471, 402000.0),
             ("Project Management", 9, 140, 588, 66200.0)],
    230312: [("Engineering", 31, 470, 3416, 328000.0),
             ("Manufacturing", 48, 980, 1876, 169000.0),
             ("Project Management", 7, 96, 366, 41200.0)],
    240087: [("Engineering", 18, 210, 1440, 138000.0),
             ("Manufacturing", 22, 360, 810, 73000.0),
             ("Project Management", 4, 40, 150, 16900.0)],
}
_DEMO_LABOUR_DETAIL = {   # pid -> [(date, emp, dept, hourdesc, reg/ot, hours, rate)]
    230219: [("2026-07-17", "107", "Manufacturing", "Mechanical Assembly", "Reg", 8.0, 46.5),
             ("2026-07-17", "142", "Engineering", "Mechanical Engineering", "Reg", 7.5, 58.0),
             ("2026-07-16", "088", "Manufacturing", "Machining (IW)", "OT", 3.0, 44.0),
             ("2026-07-16", "203", "Electrical Engineering", "Electrical Design", "Reg", 8.0, 55.0),
             ("2026-07-15", "107", "Manufacturing", "Fabrication/Welding (IW)", "Reg", 8.0, 46.5)],
    230312: [("2026-07-17", "155", "Engineering", "Hydraulic Engineering", "Reg", 7.0, 57.0),
             ("2026-07-16", "121", "Manufacturing", "Tubing/Piping", "Reg", 8.0, 45.0),
             ("2026-07-15", "142", "Engineering", "Mechanical Engineering", "Reg", 6.5, 58.0)],
    240087: [("2026-07-14", "203", "Electrical Engineering", "Controls", "Reg", 8.0, 55.0),
             ("2026-07-11", "088", "Manufacturing", "Assembly", "Reg", 7.0, 44.0)],
}
_DEMO_PO = {   # pid -> [(po, date, vendor, item, qty, uom, value, received, curr)]
    230219: [(48210, "2026-06-12", "Bosch Rexroth", "Main hydraulic pump A10VSO", 2, "EA", 184500.0, 2, "US"),
             (48231, "2026-06-19", "Parker Hannifin", "Proportional valve set", 6, "EA", 62300.0, 3, "US"),
             (48255, "2026-07-02", "SKF Canada", "Spherical roller bearings (lot)", 40, "PC", 28800.0, 0, "CA"),
             (48260, "2026-07-08", "Bosch Rexroth", "Cylinder seals & glands", 12, "KIT", 15400.0, 0, "US")],
    230312: [(47980, "2026-05-28", "Gefran", "Pressure transducers", 8, "EA", 21900.0, 8, "US"),
             (48120, "2026-06-22", "Siemens", "S7-1500 PLC + IO", 1, "LOT", 47600.0, 0, "US")],
    240087: [(48301, "2026-07-05", "Nachi", "Servo motors (pair)", 2, "EA", 33400.0, 0, "US")],
}
_DEMO_FX = {"US": 1.31, "CA": 1.0}   # demo currency rate → base (CAD)
def _dnc(ncid, pid, status, source, origin, dept, supplier, part, purchased,
         raised="2026-03-01", closed=None, po=None, outstanding=0, inventory=0.0,
         extra=0.0, rootcause="", capa=""):
    """Build one normalized demo NC row (same shape ncspec.normalize produces)."""
    total = purchased + inventory + extra           # labour books $0 (as in live)
    return {
        "NCID": ncid, "NCR": f"NCO{ncid:010d}", "ProjectID": pid, "Title": "",
        "Status": status, "Source": source, "Origin": origin, "Department": dept,
        "Discipline": ncspec.derive_discipline(origin),
        "Part": part, "Supplier": supplier, "Customer": None, "PO": po,
        "Raised": raised, "Closed": closed, "RootCause": rootcause, "CAPA": capa,
        "Labour": 0.0, "Purchased": purchased, "Inventory": inventory, "Extra": extra,
        "Total": total, "Outstanding": outstanding,
    }


_DEMO_NC = [   # normalized demo NC rows (validated-shape figures)
    _dnc(2563, 230219, "Open", "Manufacturing", "Macrodyne Part Handling Error",
         "Manufacturing", None, None, 8711.88, raised="2026-02-04", outstanding=1,
         rootcause="Parts consumed on another job", capa="Tighten kit control"),
    _dnc(2586, 230219, "Open", "Manufacturing", "Hydraulic Design Error",
         "Engineering", None, "7075H0.0.0.0-00", 0.0, raised="2026-02-17", outstanding=2,
         rootcause="Interference with light curtain", capa="Check mechanical first"),
    _dnc(2592, 230219, "Closed", "Manufacturing", "Supplier Machining Error",
         "Manufacturing", "Sudak Precision", "GUIDE BLOCK", 760.0, raised="2026-02-19",
         closed="2026-03-05", po=33706, rootcause="Radius left in corner",
         capa="Supplier inspection procedure"),
    _dnc(2604, 230219, "Closed", "Receiving", "Supplier Fabrication Error",
         "Purchasing", "Quinton Steel", "FRAME", 2190.0, raised="2026-01-20",
         closed="2026-02-15", po=33050, outstanding=0),
    _dnc(2711, 230312, "Open", "Engineering", "Electrical Design Error",
         "Engineering", None, "W-2210", 0.0, raised="2026-04-11", outstanding=1,
         rootcause="Duplicate wire numbers", capa="Renumber before fuse blocks"),
    _dnc(2750, 230312, "Closed", "Manufacturing", "Mechanical Design Error",
         "Engineering", "Qingdao CPL", "PLATFORM", 1340.0, raised="2026-03-22",
         closed="2026-04-30", po=34269),
    _dnc(2801, 240087, "Open", "Receiving", "Supplier Machining Error",
         "Purchasing", "Nachi", "S-9001", 3450.0, raised="2026-05-02", outstanding=3,
         rootcause="Servo shaft undersized", capa="Return + re-machine"),
]


def _demo_nc_by_project():
    return ncspec.by_project_totals(_DEMO_NC)
# Canned procurement exceptions (open PO lines, delivered/ordered-late)
_DEMO_EXC = [
    {"Buyer": "Nolan, Pat", "ProjectID": 230219, "PO": 48255, "Vendor": "SKF Canada",
     "Item": 14398, "Descr": "Spherical roller bearings (lot)", "Qty": 40.0, "Received": 0.0,
     "ExtValue": 28800.0, "NeedBy": "2026-06-30", "Ordered": "2026-07-02", "Lead": 62,
     "LLT": "LLT", "OrdLate": "LATE", "DelLate": "LATE", "DaysLate": 25},
    {"Buyer": "Nolan, Pat", "ProjectID": 230219, "PO": 48260, "Vendor": "Bosch Rexroth",
     "Item": 15112, "Descr": "Cylinder seals & glands", "Qty": 12.0, "Received": 0.0,
     "ExtValue": 15400.0, "NeedBy": "2026-07-10", "Ordered": "2026-07-08", "Lead": 30,
     "LLT": "", "OrdLate": "", "DelLate": "LATE", "DaysLate": 15},
    {"Buyer": "Ferreira, Sam", "ProjectID": 230312, "PO": 48120, "Vendor": "Siemens",
     "Item": 20055, "Descr": "S7-1500 PLC + IO", "Qty": 1.0, "Received": 0.0,
     "ExtValue": 47600.0, "NeedBy": "2026-07-01", "Ordered": "2026-06-22", "Lead": 50,
     "LLT": "LLT", "OrdLate": "LATE", "DelLate": "LATE", "DaysLate": 24},
]

# ── Canned ETO-shaped frames for the deployed daily reports (demo) ────────────
_D19 = ("230219 - 5500 Ton Forging Press", "Williams International")
_D12 = ("230312 - 2500T Compression Press", "Eaton Corporation")
_D87 = ("240087 - 650 Ton Trim Press", "Norris Cylinder")


def _lab(dept, pid, jn, cust, empno, emp, cat, jd, hrs, rate, factor=1.0):
    return {"Department": dept, "ProjectID": pid, "JobName": jn, "Customer": cust,
            "EmpNo": empno, "Employee": emp, "Category": cat, "JobDetail": jd,
            "Hours": hrs, "Rate": rate, "Factor": factor}


# "This Pay Period" — a handful of charges per project
_DEMO_LAB_PERIOD = [
    _lab("Administration", 230219, *_D19, "5143", "5143 - Yang, Qin", "Customer Support", "Misc", 2.5, 95),
    _lab("Engineering", 230219, *_D19, "222", "222 - Papenfuss, Paul", "Mechanical Engineering", "HPU Design", 8.0, 95),
    _lab("Engineering", 230219, *_D19, "5070", "5070 - Rozik, Greg", "Electrical Engineering", "PLC programming", 4.0, 80, 1.5),
    _lab("Manufacturing", 230219, *_D19, "5281", "5281 - Hacault, Nathan", "Mechanical Assembly", "", 10.5, 95),
    _lab("Manufacturing", 230219, *_D19, "5281", "5281 - Hacault, Nathan", "Re-work", "NCR rework (task 999)", 6.0, 95),
    _lab("Engineering", 230219, *_D19, "222", "222 - Papenfuss, Paul", "Re-work", "NCR rework (task 999)", 3.0, 95),
    _lab("Engineering", 230312, *_D12, "155", "155 - Tam, SzeWai", "Hydraulic Engineering", "Manifold layout", 7.0, 95),
    _lab("Manufacturing", 230312, *_D12, "121", "121 - Ferns, Rob", "Tubing/Piping", "", 8.0, 95),
    _lab("Engineering", 240087, *_D87, "203", "203 - Kerridge, Trevor", "Electrical Engineering", "Controls", 8.0, 95),
]
# "Project Lifetime" — everything above plus prior-period history (same jobs)
_DEMO_LAB_LIFE = _DEMO_LAB_PERIOD + [
    _lab("Engineering", 230219, *_D19, "222", "222 - Papenfuss, Paul", "Mechanical Engineering", "Frame design", 152.0, 95),
    _lab("Engineering", 230219, *_D19, "5070", "5070 - Rozik, Greg", "Electrical Engineering", "Schematics", 88.0, 80),
    _lab("Manufacturing", 230219, *_D19, "5281", "5281 - Hacault, Nathan", "Mechanical Assembly", "", 240.0, 95),
    _lab("Administration", 230219, *_D19, "5141", "5141 - Mirzaei, Anna", "Project Coordination", "", 146.5, 88),
    _lab("Engineering", 230312, *_D12, "155", "155 - Tam, SzeWai", "Hydraulic Engineering", "HPU sizing", 96.0, 95),
    _lab("Manufacturing", 230312, *_D12, "121", "121 - Ferns, Rob", "Tubing/Piping", "", 130.0, 95),
    _lab("Engineering", 240087, *_D87, "203", "203 - Kerridge, Trevor", "Electrical Engineering", "Controls", 210.0, 95),
]

# PO Status — query_po_status_open output shape
_DEMO_PO_STATUS_COLS = ["ProjectID", "JobName", "Customer", "MachineCode", "Item", "Description",
                        "PO", "Supplier", "ProjStatus", "Qty", "Received", "Price", "ExtValue",
                        "Required", "Revised"]
_DEMO_PO_STATUS = [
    {"ProjectID": 230219, "JobName": _D19[0], "Customer": _D19[1], "MachineCode": 10.0,
     "Item": "48210", "Description": "Main hydraulic pump A10VSO", "PO": "48210",
     "Supplier": "Bosch Rexroth", "ProjStatus": "Sold", "Qty": 2, "Received": 1,
     "Price": 92250.0, "ExtValue": 92250.0, "Required": "2026-05-10", "Revised": None},
    {"ProjectID": 230219, "JobName": _D19[0], "Customer": _D19[1], "MachineCode": 10.0,
     "Item": "48255", "Description": "Spherical roller bearings (lot)", "PO": "48255",
     "Supplier": "SKF Canada", "ProjStatus": "Sold", "Qty": 40, "Received": 0,
     "Price": 720.0, "ExtValue": 28800.0, "Required": "2026-06-30", "Revised": None},
    {"ProjectID": 230312, "JobName": _D12[0], "Customer": _D12[1], "MachineCode": 10.0,
     "Item": "48120", "Description": "S7-1500 PLC + IO", "PO": "48120",
     "Supplier": "Siemens", "ProjStatus": "Sold", "Qty": 1, "Received": 0,
     "Price": 47600.0, "ExtValue": 47600.0, "Required": "2026-07-01", "Revised": "2026-08-15"},
    {"ProjectID": 240087, "JobName": _D87[0], "Customer": _D87[1], "MachineCode": 20.0,
     "Item": "48301", "Description": "Servo motors (pair)", "PO": "48301",
     "Supplier": "Nachi", "ProjStatus": "Sold", "Qty": 2, "Received": 0,
     "Price": 16700.0, "ExtValue": 33400.0, "Required": "2026-08-01", "Revised": None},
]

# Lines to Order — _q_po_to_order output shape (draft POs: not printed, not emailed)
_DEMO_TOORDER_COLS = ["ProjectID", "JobName", "Customer", "MachineCode", "Item", "Description",
                      "PO", "Supplier", "Buyer", "Curr", "Qty", "Price", "ExtValueCAD",
                      "Required", "Entered", "AgeDays"]
_DEMO_TOORDER = [
    {"ProjectID": 230219, "JobName": _D19[0], "Customer": _D19[1], "MachineCode": 10, "Item": 28041,
     "Description": "Cylinder gland seals (spare set)", "PO": 48310, "Supplier": "Bosch Rexroth",
     "Buyer": "Nolan, Pat", "Curr": "US", "Qty": 4, "Price": 180.0, "ExtValueCAD": 943.20,
     "Required": "2026-08-20", "Entered": "2026-07-22", "AgeDays": 3},
    {"ProjectID": 230219, "JobName": _D19[0], "Customer": _D19[1], "MachineCode": 10, "Item": 28115,
     "Description": "Proximity sensors, M18", "PO": 48310, "Supplier": "Bosch Rexroth",
     "Buyer": "Nolan, Pat", "Curr": "US", "Qty": 12, "Price": 46.0, "ExtValueCAD": 723.12,
     "Required": "2026-08-20", "Entered": "2026-07-22", "AgeDays": 3},
    {"ProjectID": 230219, "JobName": _D19[0], "Customer": _D19[1], "MachineCode": 20, "Item": 30880,
     "Description": "Guarding mesh panels", "PO": 48291, "Supplier": "Axelent",
     "Buyer": "Ferreira, Sam", "Curr": "CA", "Qty": 8, "Price": 240.0, "ExtValueCAD": 1920.00,
     "Required": "2026-09-04", "Entered": "2026-04-02", "AgeDays": 116},
    {"ProjectID": 230312, "JobName": _D12[0], "Customer": _D12[1], "MachineCode": 10, "Item": 20142,
     "Description": "S7-1500 spare IO card", "PO": 48277, "Supplier": "Siemens",
     "Buyer": "Ferreira, Sam", "Curr": "US", "Qty": 2, "Price": 590.0, "ExtValueCAD": 1546.40,
     "Required": "2026-08-15", "Entered": "2026-07-25", "AgeDays": 0},
    {"ProjectID": 240087, "JobName": _D87[0], "Customer": _D87[1], "MachineCode": 20, "Item": 51002,
     "Description": "Servo cable, 15m", "PO": 48305, "Supplier": "Nachi",
     "Buyer": "Nolan, Pat", "Curr": "US", "Qty": 2, "Price": 210.0, "ExtValueCAD": 550.20,
     "Required": "2026-09-01", "Entered": "2026-07-18", "AgeDays": 7},
]

# Item Location — _q_item_location output shape (on-hand by item & location, shared stock)
_DEMO_ITEMLOC_COLS = ["ProjectID", "JobName", "ItemNo", "Description", "Location", "Bin",
                      "OnHand", "MinReq"]
_DEMO_ITEMLOC = [
    {"ProjectID": 230219, "JobName": _D19[0], "ItemNo": "E05416",
     "Description": "Cable tie, Black, 11.4\" (bags of 1000)", "Location": "Macrodyne 1",
     "Bin": "", "OnHand": 4000, "MinReq": 500},
    {"ProjectID": 230219, "JobName": _D19[0], "ItemNo": "E05416",
     "Description": "Cable tie, Black, 11.4\" (bags of 1000)", "Location": "Macrodyne 2 (Racco)",
     "Bin": "FW3", "OnHand": 4, "MinReq": 0},
    {"ProjectID": 230219, "JobName": _D19[0], "ItemNo": "E04919",
     "Description": "Lugs, (2@350MCM), box of 3", "Location": "Macrodyne 2 (Racco)",
     "Bin": "E4B4", "OnHand": 1, "MinReq": 2},
    {"ProjectID": 230312, "JobName": _D12[0], "ItemNo": "E05413",
     "Description": "Cable tie, Black, 5\" (bags of 1000)", "Location": "Macrodyne 1",
     "Bin": "", "OnHand": 2000, "MinReq": 0},
    {"ProjectID": 240087, "JobName": _D87[0], "ItemNo": "E05442",
     "Description": "Heat Shrink, Clear, 1/16\" dia", "Location": "Macrodyne 1",
     "Bin": "", "OnHand": 20, "MinReq": 5},
    {"ProjectID": 240087, "JobName": _D87[0], "ItemNo": "E00216",
     "Description": "Mounting bracket for SL-C light curtain", "Location": "TOC",
     "Bin": "", "OnHand": 3, "MinReq": 1},
]

# Inventory Value — _q_inventory_value output shape (on-hand value by item & location)
_DEMO_INVVAL_COLS = ["ProjectID", "JobName", "ItemNo", "Description", "Location", "Bin",
                     "OnHand", "ExtValue", "LayerQty"]
_DEMO_INVVAL = [
    {"ProjectID": 230219, "JobName": _D19[0], "ItemNo": "E03308",
     "Description": "Three level sensor terminal block; Grey; 6.2mm", "Location": "Macrodyne 2 (Racco)",
     "Bin": "E4B4", "OnHand": 4100, "ExtValue": 26650.0, "LayerQty": 4100},
    {"ProjectID": 230219, "JobName": _D19[0], "ItemNo": "E05416",
     "Description": "Cable tie, Black, 11.4\" (bags of 1000)", "Location": "Macrodyne 1",
     "Bin": "", "OnHand": 4000, "ExtValue": 400.0, "LayerQty": 4000},
    {"ProjectID": 230219, "JobName": _D19[0], "ItemNo": "8005M0.0.0.0-04",
     "Description": "SHCS 0.25-20 UNC x 0.625 (made-to-project, part-costed)",
     "Location": "Macrodyne 2 (Racco)", "Bin": "M2", "OnHand": 1513, "ExtValue": 89.45,
     "LayerQty": 1180},
    {"ProjectID": 230219, "JobName": _D19[0], "ItemNo": "9001S-001",
     "Description": "Fabricated bracket (no purchase-price layer)", "Location": "Macrodyne 1",
     "Bin": "", "OnHand": 6, "ExtValue": None, "LayerQty": None},
    {"ProjectID": 230312, "JobName": _D12[0], "ItemNo": "E05413",
     "Description": "Cable tie, Black, 5\" (bags of 1000)", "Location": "Macrodyne 1",
     "Bin": "", "OnHand": 2000, "ExtValue": 100.0, "LayerQty": 2000},
]

# Inventory by Site — _q_inventory_by_site output shape (portfolio value by location)
_DEMO_BYSITE_COLS = ["Location", "Lines", "Items", "Value", "Uncosted"]
_DEMO_BYSITE = [
    {"Location": "Macrodyne 2 (Racco)", "Lines": 2478, "Items": 2461, "Value": 4318220.55,
     "Uncosted": 220},
    {"Location": "Macrodyne 1", "Lines": 512, "Items": 508, "Value": 986431.20, "Uncosted": 61},
    {"Location": "TOC", "Lines": 34, "Items": 34, "Value": 118764.00, "Uncosted": 3},
    {"Location": "PS1", "Lines": 8, "Items": 8, "Value": 22110.40, "Uncosted": 0},
    {"Location": "In Transit to Racco", "Lines": 0, "Items": 0, "Value": 0.0, "Uncosted": 0},
]

# Packing Slips — _q_packing_slip output shape (shipped lines by slip, project-scoped)
_DEMO_PACKSLIP_COLS = ["ProjectID", "JobName", "PackingSlipID", "SlipNo", "SlipType",
                       "CreatedDate", "ShippedDate", "Shipper", "ShipFrom", "FromCity", "ShipTo",
                       "ToCity", "Shipped", "Packed", "Machine", "ItemNo", "Description",
                       "Category", "Qty"]
_DEMO_PACKSLIP = [
    # customer shipment: Racco → Honeywell
    {"ProjectID": 230219, "JobName": _D19[0], "PackingSlipID": 9001, "SlipNo": "900004009336",
     "SlipType": "Default", "CreatedDate": "2026-06-24", "ShippedDate": "2026-06-25",
     "Shipper": "Purolator", "ShipFrom": "Macrodyne Technologies Inc", "FromCity": "Thornhill",
     "ShipTo": "Honeywell Electronic Materials", "ToCity": "Spokane Valley", "Shipped": True,
     "Packed": True, "Machine": 10.0, "ItemNo": "7077H0.0.0.0-05",
     "Description": "2.5\" SCH 40 WELD NECK FLAT FACE FLANGE 150 LBS CARBON STEEL",
     "Category": "FLANGES", "Qty": 2},
    {"ProjectID": 230219, "JobName": _D19[0], "PackingSlipID": 9001, "SlipNo": "900004009336",
     "SlipType": "Default", "CreatedDate": "2026-06-24", "ShippedDate": "2026-06-25",
     "Shipper": "Purolator", "ShipFrom": "Macrodyne Technologies Inc", "FromCity": "Thornhill",
     "ShipTo": "Honeywell Electronic Materials", "ToCity": "Spokane Valley", "Shipped": True,
     "Packed": True, "Machine": 10.0, "ItemNo": "7086H0.0.0.0-12",
     "Description": "2\" LONG RADIUS BUTTWELD SCH.40 ELBOW-90", "Category": "PIPE", "Qty": 4},
    # internal transfer: Racco → Concord (Macrodyne → Macrodyne)
    {"ProjectID": 230312, "JobName": _D12[0], "PackingSlipID": 9002, "SlipNo": "20260429-3",
     "SlipType": "AutoShip", "CreatedDate": "2026-04-30", "ShippedDate": None,
     "Shipper": "", "ShipFrom": "Macrodyne Technologies Inc", "FromCity": "Thornhill",
     "ShipTo": "Macrodyne Technologies Inc.", "ToCity": "Concord", "Shipped": False, "Packed": True,
     "Machine": 20.0, "ItemNo": "8900M0.0.0.0-66", "Description": "CONNECTING TUBE 33.750 LG",
     "Category": "MACHINED", "Qty": 7},
]

# Procurement Exceptions — query_po_exceptions output shape
_DEMO_EXC_COLS = ["Buyer", "ProjectID", "JobName", "Code", "Item", "Description", "Category",
                  "PO", "Vendor", "Qty", "Received", "ExtValue", "DateRequired", "DateRevised",
                  "ReceiptDate", "Ordered", "LeadDays", "LLTFlag", "OverFlag", "EngReleaseDate"]
_DEMO_EXC_RAW = [
    {"Buyer": "Nolan, Pat", "ProjectID": 230219, "JobName": _D19[0], "Code": 10, "Item": "48255",
     "Description": "Spherical roller bearings (lot)", "Category": "Bearings", "PO": "48255",
     "Vendor": "SKF Canada", "Qty": 40, "Received": 0, "ExtValue": 28800.0,
     "DateRequired": "2026-06-30", "DateRevised": None, "ReceiptDate": None, "Ordered": "2026-05-02",
     "LeadDays": 62, "LLTFlag": 1, "OverFlag": 0, "EngReleaseDate": "2026-04-15"},
    {"Buyer": "Nolan, Pat", "ProjectID": 230219, "JobName": _D19[0], "Code": 10, "Item": "48260",
     "Description": "Cylinder seals & glands", "Category": "Hydraulic Components", "PO": "48260",
     "Vendor": "Bosch Rexroth", "Qty": 12, "Received": 4, "ExtValue": 15400.0,
     "DateRequired": "2026-07-10", "DateRevised": None, "ReceiptDate": "2026-07-18",
     "Ordered": "2026-07-08", "LeadDays": 30, "LLTFlag": 0, "OverFlag": 0, "EngReleaseDate": None},
    {"Buyer": "Ferreira, Sam", "ProjectID": 230312, "JobName": _D12[0], "Code": 20, "Item": "48120",
     "Description": "S7-1500 PLC + IO", "Category": "Electrical / Controls", "PO": "48120",
     "Vendor": "Siemens", "Qty": 1, "Received": 0, "ExtValue": 47600.0, "DateRequired": "2026-07-01",
     "DateRevised": None, "ReceiptDate": None, "Ordered": "2026-06-22", "LeadDays": 120,
     "LLTFlag": 1, "OverFlag": 1, "EngReleaseDate": "2026-05-30"},
]

# Late Vendors — query_late_vendors output shape (OVERDUE open lines, not yet received)
_DEMO_LATE_COLS = ["Supplier", "ProjectID", "PO", "Item", "Description", "Qty", "Received",
                   "Required", "Revised", "DaysLate", "ExtValue", "JobName", "ProjStatus"]
_DEMO_LATE = [
    {"Supplier": "SKF Canada", "ProjectID": 230219, "PO": "48255", "Item": "14398",
     "Description": "Spherical roller bearings (lot)", "Qty": 40, "Received": 0,
     "Required": "2026-06-30", "Revised": None, "DaysLate": 25, "ExtValue": 28800.0,
     "JobName": _D19[0], "ProjStatus": "Sold"},
    {"Supplier": "Bosch Rexroth", "ProjectID": 230219, "PO": "48260", "Item": "15112",
     "Description": "Cylinder seals & glands", "Qty": 12, "Received": 0,
     "Required": "2026-07-10", "Revised": None, "DaysLate": 15, "ExtValue": 15400.0,
     "JobName": _D19[0], "ProjStatus": "Sold"},
    {"Supplier": "Siemens", "ProjectID": 230312, "PO": "48120", "Item": "20055",
     "Description": "S7-1500 PLC + IO", "Qty": 1, "Received": 0,
     "Required": "2026-07-01", "Revised": None, "DaysLate": 24, "ExtValue": 47600.0,
     "JobName": _D12[0], "ProjStatus": "Sold"},
]

# Late Vendors (delivered-late) — query_delivered_late output shape (RECEIVED late lines)
_DEMO_DELIVERED_COLS = ["Supplier", "ProjectID", "PO", "Item", "Description", "Qty", "QtyReceived",
                        "Required", "Revised", "Received", "DaysLate", "ExtValue", "JobName", "ProjStatus"]
_DEMO_DELIVERED = [
    {"Supplier": "Bosch-Rexroth Canada Corp.", "ProjectID": 230219, "PO": "35584", "Item": "28040",
     "Description": "Cylinder seals & glands", "Qty": 1, "QtyReceived": 1, "Required": "2025-12-12",
     "Revised": None, "Received": "2026-03-06", "DaysLate": 84, "ExtValue": 1773.27,
     "JobName": _D19[0], "ProjStatus": "Sold"},
    {"Supplier": "Bosch-Rexroth Canada Corp.", "ProjectID": 230219, "PO": "35879", "Item": "28040",
     "Description": "Cylinder seals & glands", "Qty": 1, "QtyReceived": 1, "Required": "2026-01-12",
     "Revised": None, "Received": "2026-04-06", "DaysLate": 84, "ExtValue": 1822.92,
     "JobName": _D19[0], "ProjStatus": "Sold"},
    {"Supplier": "Hope Land", "ProjectID": 230219, "PO": "33146", "Item": "23508",
     "Description": "Freight / courier", "Qty": 1, "QtyReceived": 1, "Required": "2025-09-15",
     "Revised": None, "Received": "2025-11-20", "DaysLate": 66, "ExtValue": 16303.00,
     "JobName": _D19[0], "ProjStatus": "Sold"},
    {"Supplier": "Sudak Precision", "ProjectID": 230219, "PO": "33706", "Item": "27790",
     "Description": "Machined component", "Qty": 2, "QtyReceived": 2, "Required": "2025-11-30",
     "Revised": None, "Received": "2026-01-22", "DaysLate": 53, "ExtValue": 20.00,
     "JobName": _D19[0], "ProjStatus": "Sold"},
    {"Supplier": "AirLoc Corporation", "ProjectID": 230219, "PO": "34560", "Item": "27798",
     "Description": "Leveling mounts", "Qty": 4, "QtyReceived": 4, "Required": "2025-11-06",
     "Revised": None, "Received": "2025-11-17", "DaysLate": 11, "ExtValue": 19756.33,
     "JobName": _D19[0], "ProjStatus": "Sold"},
]


class _DemoFin:
    """Duck-types the ProjectFinancials fields the row builders read."""
    def __init__(self, d):
        self.labour_budget_hours = d["lb"]
        self.labour_actual_hours = d["la"]
        self.material_budget = d["mb"]
        self.material_actual = d["ma"]            # Resource Consumption (headline)
        # split the consumption into the three ETO lenses so the scorecard tile renders
        inv = round(d["ma"] * 0.02, 2)
        pay = round(d["ma"] * 0.005, 2)
        self.material_inventory = inv
        self.material_payables = pay
        self.material_committed = round(d["ma"] - inv - pay, 2)   # purchased (costed) portion
        self.labour_consumed_pct = round(d["la"] / d["lb"], 4) if d["lb"] else None
        self.material_consumed_pct = round(d["ma"] / d["mb"], 4) if d["mb"] else None
        # earning-at-completion inputs (ETO costing rollup in live mode)
        self.labour_actual_cost = d.get("lc")
        self.sales_price = d.get("sp")
        self.sold_margin = d.get("sm")
        self.labour_rate = (round(d["lc"] / d["la"], 4)
                            if d.get("lc") is not None and d.get("la") else None)


# ─────────────────────────────────────────────────────────────────────────────
# helpers
# ─────────────────────────────────────────────────────────────────────────────
def _num(x):
    try:
        return None if x is None else float(x)
    except (TypeError, ValueError):
        return None


def _int(x):
    try:
        return None if x is None else int(float(x))
    except (TypeError, ValueError):
        return None


def _opt_money(x):
    """Money read that treats a genuine 0/blank as 'no value' (None) — so the earning columns
    stay empty rather than projecting a $0 sold price or a zero labour rate."""
    v = _num(x)
    return round(v, 2) if v else None


def _opt_frac(x):
    """A margin from ETO that may arrive as a fraction (0.28) or a percent (28.4) → 0–1 fraction.
    Signed (overruns can be negative), so normalise on magnitude, not a >1 test."""
    v = _num(x)
    if v is None:
        return None
    return round(v / 100.0, 4) if abs(v) > 1.0 else round(v, 4)


def _frac(x):
    """Normalise a %-done that may arrive as 0–1 or 0–100 into a 0–1 fraction."""
    v = _num(x)
    if v is None:
        return None
    return v / 100.0 if v > 1.0 else v


def _as_date(x):
    """Coerce to a date; 2099 (PM 'TBD' placeholder) and blanks → None."""
    if x is None:
        return None
    try:
        import pandas as pd
        if pd.isna(x):
            return None
    except Exception:
        pass
    d = None
    if hasattr(x, "date") and not isinstance(x, str):
        try:
            d = x.date()
        except Exception:
            d = None
    elif hasattr(x, "year") and not isinstance(x, str):
        d = x
    elif isinstance(x, str):
        from datetime import date as _date
        try:
            d = _date.fromisoformat(x[:10])
        except ValueError:
            return x  # leave unparseable strings as-is
    if d is not None and getattr(d, "year", 0) >= 2099:
        return None
    return d


def _iso(x):
    d = _as_date(x)
    if d is None:
        return None
    try:
        return d.isoformat()
    except AttributeError:
        return str(d)


def _slip(planned, agreed):
    p, a = _as_date(planned), _as_date(agreed)
    try:
        return (p - a).days if (p and a and hasattr(p, "toordinal") and hasattr(a, "toordinal")) else None
    except Exception:
        return None


def _fmt_money(v):
    return "${:,.2f}".format(v or 0)


def make_service(demo=False) -> QueryService:
    return DemoQueryService() if demo else LiveQueryService()


def branding():
    return {"product": TENANT.product_name, "company": TENANT.company_name,
            "color": TENANT.header_color, "logo": getattr(TENANT, "logo_path", ""),
            "lexicon": dict(TENANT.lexicon),
            "fiscal_year_start_month": getattr(TENANT, "fiscal_year_start_month", 1),
            "pay_period_anchor": getattr(TENANT, "pay_period_anchor", None),
            "pay_period_days": getattr(TENANT, "pay_period_days", 14)}


def data_watermark():
    """Cheap "has the dashboard data moved?" probe for the warm cache (cache.py).

    Combines the two ETO driver tables' max identity keys (insert-sensitive — a new
    timecard or PO line advances them) with the Console store's max edit timestamps.
    Every term is an indexed/scalar MAX, so the whole probe is a couple of fast
    round-trips regardless of table size. The return is opaque: identical string
    across two calls == nothing the dashboard depends on has changed, so the cache
    can skip the expensive recompute. Read-only against ETO like everything else.

    (In-place store edits that don't advance a max are still caught two other ways:
    the PM budget / plan save handlers call cache.mark_dirty(), and the cache forces
    a full rebuild at least every MAX_AGE seconds.)
    """
    parts = []
    try:
        from console.infra.connections import eto_connection
        c = eto_connection()
        try:
            cur = c.cursor()
            cur.execute("SELECT (SELECT MAX(TimeID) FROM dbo.tblTimecards), "
                        "(SELECT MAX(PurchaseDetailID) FROM dbo.tblPurchaseOrderDetails)")
            r = cur.fetchone()
            parts.append("eto:%s/%s" % (r[0], r[1]))
        finally:
            c.close()
    except Exception:
        parts.append("eto:?")
    try:
        from console.infra.connections import console_connection
        c = console_connection()
        try:
            cur = c.cursor()
            cur.execute(
                "SELECT (SELECT MAX(CapturedAt) FROM Reporting.tblProjectPMEntry), "
                "(SELECT MAX(CreatedAt) FROM Reporting.tblProjectBudget), "
                "(SELECT MAX(UpdatedAt) FROM Reporting.tlkpDisciplineCrosswalk)")
            r = cur.fetchone()
            parts.append("store:%s/%s/%s" % (r[0], r[1], r[2]))
        finally:
            c.close()
    except Exception:
        parts.append("store:?")
    return "|".join(parts)
