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
            "rows": self.rows,
            "cards": [asdict(c) for c in self.cards],
            "note": self.note,
        }


# ─────────────────────────────────────────────────────────────────────────────
# Query catalogue (drives the UI dropdown)
# ─────────────────────────────────────────────────────────────────────────────
_QUERY_IDS = {"exec", "scorecard", "discipline", "budget_actual", "crosswalk",
              "lab_a", "lab_b", "lab_c", "lab_d", "lab_e",
              "po_status", "po_exceptions", "po_late", "po_delivered",
              "nc_summary", "nc_costs", "nc_impact", "nc_cause", "nc_discipline",
              "nc_supplier", "nc_detail"}

# reports that read ETO live and honour the optional date range / view
ETO_REPORT_IDS = {"lab_a", "lab_b", "lab_c", "lab_d", "lab_e",
                  "po_status", "po_exceptions", "po_late", "po_delivered",
                  "nc_summary", "nc_costs", "nc_impact", "nc_cause", "nc_discipline",
                  "nc_supplier", "nc_detail"}

# labour reports carry the two-view toggle (This Pay Period / Project Lifetime)
LABOUR_VIEW_IDS = {"lab_a", "lab_b", "lab_c", "lab_d", "lab_e"}


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
        # ── Purchasing (the deployed PO reports) ───────────────────────────
        {"id": "po_status", "menu": "Purchasing", "label": "PO Status",
         "desc": f"Open purchase-order lines — On Order and Overdue — grouped by {proj.lower()} "
                 "and machine, with an overdue-aging summary.",
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

    def _financials(self, project_ids):
        from console.domain.budget import BudgetDAO
        from console.domain.discipline_actuals import DisciplineActualsDAO
        from console.domain.project_financials import ProjectFinancialsService
        bdao = BudgetDAO(self._console_conn())
        adao = DisciplineActualsDAO(self._eto_conn(), self._crosswalk())
        svc = ProjectFinancialsService(bdao, adao)
        mats = self._material_actuals(project_ids)     # committed PO value, live from ETO
        pids = [int(p) for p in project_ids]
        return svc.for_projects(pids, material_actuals=mats)

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
        rows = []
        for pid in fin:
            f = fin[pid]
            rec = dict(ov.get(str(pid), {}))       # copy — we augment with live actuals
            g = nc.get(pid, {})
            rec["NCOpen"], rec["NCCost"] = g.get("open"), g.get("cost")
            rec.update(proc.get(pid, {}))          # calculated Line Items / LLTP Del. Late
            rec.update(tw.get(pid, {}))            # calculated 2-week labour hrs / material $
            name, client = meta.get(pid, (None, None))
            disc_pct = {d.discipline: d.consumed_pct for d in (f.disciplines if f else [])}
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
        rows = []
        for pid in sorted(fin):
            f = fin[pid]
            rec = dict(ov.get(str(pid), {}))
            g = nc.get(pid, {})
            rec["NCOpen"], rec["NCCost"] = g.get("open"), g.get("cost")
            rows.append(_scorecard_row(pid, f, rec))
        return _scorecard_result(rows)

    def _q_discipline(self, project_ids, **kw):
        fin = self._financials(project_ids)
        rows = []
        for pid in sorted(fin):
            for d in fin[pid].disciplines:
                rows.append({"ProjectID": pid, "Discipline": d.discipline,
                             "BudgetHours": d.budget_hours, "ActualHours": d.actual_hours,
                             "ConsumedPct": d.consumed_pct, "RemainingHours": d.remaining_hours})
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
        return _spec_labour_result(report_id, df, _window_label(dfrom, dto))

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

    def _q_po_status(self, project_ids, date_from=None, date_to=None, **kw):
        import datetime as _dt
        pids = [int(p) for p in project_ids] if project_ids else None
        raw = self._df(etospec.query_po_status_open(pids))
        as_of = _dt.date.today()
        pdf = etospec.po_prep(raw, today=as_of)
        return _spec_po_status_result(pdf, f"As at {as_of:%b %d, %Y}")

    def _q_po_exceptions(self, project_ids, date_from=None, date_to=None, **kw):
        import datetime as _dt
        pids = [int(p) for p in project_ids] if project_ids else None
        enriched = True
        try:
            raw = self._df(etospec.query_po_exceptions(True, pids))
        except Exception:
            enriched = False
            raw = self._df(etospec.query_po_exceptions(False, pids))
        as_of = _dt.date.today()
        items = etospec.exc_aggregate(etospec.exc_classify(raw, today=as_of))
        return _spec_po_exc_result(items, f"As at {as_of:%b %d, %Y}", enriched)

    def _q_po_late(self, project_ids, date_from=None, date_to=None, **kw):
        import datetime as _dt
        pids = [int(p) for p in project_ids] if project_ids else None
        df = self._df(etospec.query_late_vendors(pids))
        return _spec_late_result(df, f"As at {_dt.date.today():%b %d, %Y}")

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

    def _nc_by_project(self, project_ids):
        """{pid: {'open': n, 'cost': $}} for the dashboard NC-actuals columns."""
        if not project_ids:
            return {}
        try:
            rows = _live_nc_cost_rows(self._eto_conn().cursor(), project_ids, None, None)
            return ncspec.by_project_totals(rows)
        except Exception:
            return {}

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
        QueryColumn("MaterialBudget", f"{material} Budget", "money", "right"),
        QueryColumn("MaterialActual", f"{material} Actual", "money", "right", calc=True),
        QueryColumn("MaterialPct", f"{material} %", "pct", "right"),
        QueryColumn("NCOpen", "Open NCRs", "int", "right", calc=True),
        QueryColumn("NCCost", "Cost of NC", "money", "right", calc=True),
        QueryColumn("PctDone", "% Done", "pct", "right"),
        QueryColumn("CustAgreedDate", "Cust Agreed Ship", "date", "left"),
        QueryColumn("RunoutLabour", f"{labour} Runout", "hours", "right"),
        QueryColumn("Rank", "Rank", "int", "right"),
    ]
    over = [r for r in rows if (r.get("LabourPct") or 0) > 1.0]
    cards = [
        Card(L("projects"), str(len(rows))),
        Card(f"Over {labour.lower()} budget", str(len(over)), "bad" if over else "good"),
        Card(f"Total {material.lower()} budget",
             _fmt_money(sum(r.get("MaterialBudget") or 0 for r in rows))),
    ]
    note = (f"Italic figures are live actuals: {labour.lower()} from timecards, {material.lower()} "
            f"is the committed (ordered) purchase value in Canadian dollars, and NCR figures from "
            f"the costing data. Budgets and % Done are the PM plan.")
    return QueryResult("scorecard", f"{proj} {L('scorecard')}", cols, rows, cards, note)


def _discipline_result(rows):
    proj, disc = L("project"), L("discipline")
    cols = [
        QueryColumn("ProjectID", proj, "id", "left"),
        QueryColumn("Discipline", disc, "text", "left"),
        QueryColumn("BudgetHours", "Budget (hrs)", "hours", "right"),
        QueryColumn("ActualHours", "Actual (hrs)", "hours", "right", calc=True),
        QueryColumn("ConsumedPct", "Consumed %", "pct", "right"),
        QueryColumn("RemainingHours", "Remaining (hrs)", "hours", "right"),
    ]
    over = [r for r in rows if (r.get("ConsumedPct") or 0) > 1.0]
    cards = [
        Card(f"{disc} lines", str(len(rows))),
        Card("Over budget", str(len(over)), "bad" if over else "good"),
    ]
    return QueryResult("discipline", f"{disc} Financials", cols, rows, cards)


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
            f"{material.lower()} as the committed (ordered) purchase value in Canadian dollars. "
            "Budgets are the PM plan; variance = budget − actual.")
    return QueryResult("budget_actual", "Budget vs Actual", cols, rows, cards, note)


def _crosswalk_result(rows):
    disc = L("discipline")
    cols = [
        QueryColumn("HourDescription", L("hour_description"), "text", "left", wrap=True),
        QueryColumn("Discipline", disc, "text", "left"),
    ]
    cards = [Card("Mappings", str(len(rows)))]
    return QueryResult("crosswalk", L("crosswalk"), cols, rows, cards)


def _scorecard_row(pid, f, rec):
    return {
        "ProjectID": pid,
        "LabourBudget": f.labour_budget_hours,
        "LabourActual": f.labour_actual_hours,
        "LabourPct": f.labour_consumed_pct,
        "MaterialBudget": f.material_budget,
        "MaterialActual": f.material_actual,
        "MaterialPct": f.material_consumed_pct,
        "NCOpen": _int(rec.get("NCOpen")),
        "NCCost": _num(rec.get("NCCost")),
        "PctDone": _num(rec.get("PctDone")),
        "CustAgreedDate": _iso(rec.get("CustAgreedDate") or rec.get("POShipDate")),
        "RunoutLabour": _num(rec.get("RunoutLabour")),
        "Rank": _int(rec.get("Rank")),
    }


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
        QueryColumn("RunoutLabour", f"Run-out {labour}", "pct", "right", "Budget"),
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
            "Non-Conformance figures. Schedule, % Done (incl. its 2-week delta), run-outs and the "
            f"remaining procurement counts are PM entries. Ranked by {L('labour').lower()} % of "
            "budget (hours).")
    return QueryResult("exec", "Executive Dashboard", cols, rows, cards, note)


def _exec_row(pid, name, client, f, rec, disc_pct):
    """Assemble one ranked row from financials (ETO) + overlay (manual)."""
    planned = rec.get("PlannedShipDate")
    agreed = rec.get("CustAgreedDate")
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
        "RunoutLabour": _num(rec.get("RunoutLabour")),
        "MatPct": f.material_consumed_pct if f else None,
        "RunoutMaterial": _num(rec.get("RunoutMaterial")),
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
    return ",".join(str(int(p)) for p in project_ids)


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
    """items = exc_aggregate output (one row per project-item)."""
    grouped = etospec.exc_build_rows(items)
    qcols = [QueryColumn(k, l, t, a, "", w) for (k, l, t, a, w) in etospec.web_columns(etospec.COLS_FLAT)]
    rows = etospec.web_rows(etospec.COLS_FLAT, grouped)
    n = 0 if items is None or items.empty else len(items)
    val = 0.0 if not n else float(items["ExtValue"].sum())
    cards = [Card("Exception items", "{:,}".format(n), "bad" if n else "good"),
             Card("At-risk value", _fmt_money2(val), "bad" if val else "good")]
    note = ("Open purchase-order lines that are past their need-by date, one row per item, "
            "grouped by buyer. LLT and Oversize are flags maintained on the item."
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
             Card("Open actions", str(outstanding), "bad" if outstanding else "good"),
             Card("Cost of NC", _fmt_money2(ncspec.totals(rows)["Total"]))]
    return QueryResult("nc_detail", "Non-Conformance — Detail", cols, ordered, cards,
                       "Not every NCR is linked to a purchase order. Open Actions = corrective "
                       "actions still outstanding. " + _NC_COST_NOTE)


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
             "done": 0.93, "runout": 1.25, "rank": 1, "ship": "2026-09-18",
             "disc": {"Project Management": (642.0, 588.0),
                      "Mechanical Engineering": (2140.0, 2760.0),
                      "Electrical Engineering": (1180.0, 1395.0),
                      "Hydraulic Engineering": (960.0, 1004.0),
                      "Manufacturing": (3200.0, 4471.0),
                      "Other": (307.0, 310.0)}},
    230312: {"lb": 6120.0, "la": 5488.0, "mb": 1840000.0, "ma": 1502233.10,
             "done": 0.78, "runout": 0.91, "rank": 3, "ship": "2026-11-06",
             "disc": {"Project Management": (410.0, 366.0),
                      "Mechanical Engineering": (1680.0, 1512.0),
                      "Electrical Engineering": (900.0, 848.0),
                      "Hydraulic Engineering": (720.0, 690.0),
                      "Manufacturing": (2210.0, 1876.0),
                      "Other": (200.0, 196.0)}},
    240087: {"lb": 4980.0, "la": 2210.0, "mb": 1310000.0, "ma": 402881.55,
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
            disc_pct = {disc: (round(a / b, 4) if b else None)
                        for disc, (b, a) in d["disc"].items()}
            rec = {"Rank": d["rank"], "POShipDate": e["po"], "CustAgreedDate": d["ship"],
                   "PlannedShipDate": e["planned"], "PctDone": d["done"],
                   "RunoutLabour": d["runout"], "RunoutMaterial": e["mat_runout"],
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
            rec = {"PctDone": d["done"], "RunoutLabour": d["runout"], "Rank": d["rank"],
                   "CustAgreedDate": d["ship"]}
            g = _demo_nc_by_project().get(pid, {})
            rec["NCOpen"], rec["NCCost"] = g.get("open"), g.get("cost")
            rows.append(_scorecard_row(pid, f, rec))
        return _scorecard_result(rows)

    def _q_discipline(self, project_ids, **kw):
        rows = []
        for pid in self._sel(project_ids):
            for disc, (b, a) in sorted(_DEMO[pid]["disc"].items()):
                pct = round(a / b, 4) if b else None
                rows.append({"ProjectID": pid, "Discipline": disc,
                             "BudgetHours": b, "ActualHours": a, "ConsumedPct": pct,
                             "RemainingHours": round(b - a, 2)})
        return _discipline_result(rows)

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
        label = ("from project start through Jul 25, 2026 (demo)" if lifetime
                 else "selected window (demo)")
        return _spec_labour_result(report_id, df, label)

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
        items = etospec.exc_aggregate(etospec.exc_classify(raw, today=_dt.date(2026, 7, 22)))
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

# Procurement Exceptions — query_po_exceptions output shape
_DEMO_EXC_COLS = ["Buyer", "ProjectID", "JobName", "Item", "Description", "PO", "Vendor",
                  "Qty", "Received", "ExtValue", "DateRequired", "DateRevised", "Ordered",
                  "LeadDays", "LLTFlag", "OverFlag", "EngReleaseDate"]
_DEMO_EXC_RAW = [
    {"Buyer": "Nolan, Pat", "ProjectID": 230219, "JobName": _D19[0], "Item": "48255",
     "Description": "Spherical roller bearings (lot)", "PO": "48255", "Vendor": "SKF Canada",
     "Qty": 40, "Received": 0, "ExtValue": 28800.0, "DateRequired": "2026-06-30",
     "DateRevised": None, "Ordered": "2026-05-02", "LeadDays": 62, "LLTFlag": 1,
     "OverFlag": 0, "EngReleaseDate": "2026-04-15"},
    {"Buyer": "Nolan, Pat", "ProjectID": 230219, "JobName": _D19[0], "Item": "48260",
     "Description": "Cylinder seals & glands", "PO": "48260", "Vendor": "Bosch Rexroth",
     "Qty": 12, "Received": 0, "ExtValue": 15400.0, "DateRequired": "2026-07-10",
     "DateRevised": None, "Ordered": "2026-07-08", "LeadDays": 30, "LLTFlag": 0,
     "OverFlag": 0, "EngReleaseDate": None},
    {"Buyer": "Ferreira, Sam", "ProjectID": 230312, "JobName": _D12[0], "Item": "48120",
     "Description": "S7-1500 PLC + IO", "PO": "48120", "Vendor": "Siemens",
     "Qty": 1, "Received": 0, "ExtValue": 47600.0, "DateRequired": "2026-07-01",
     "DateRevised": None, "Ordered": "2026-06-22", "LeadDays": 120, "LLTFlag": 1,
     "OverFlag": 1, "EngReleaseDate": "2026-05-30"},
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
        self.material_actual = d["ma"]
        self.labour_consumed_pct = round(d["la"] / d["lb"], 4) if d["lb"] else None
        self.material_consumed_pct = round(d["ma"] / d["mb"], 4) if d["mb"] else None


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
    return "${:,.0f}".format(v or 0)


def make_service(demo=False) -> QueryService:
    return DemoQueryService() if demo else LiveQueryService()


def branding():
    return {"product": TENANT.product_name, "company": TENANT.company_name,
            "color": TENANT.header_color, "lexicon": dict(TENANT.lexicon),
            "fiscal_year_start_month": getattr(TENANT, "fiscal_year_start_month", 1),
            "pay_period_anchor": getattr(TENANT, "pay_period_anchor", None),
            "pay_period_days": getattr(TENANT, "pay_period_days", 14)}
