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
              "po_status", "po_exceptions", "po_late",
              "nc_summary", "nc_detail"}

# reports that read ETO live and honour the optional date range / view
ETO_REPORT_IDS = {"lab_a", "lab_b", "lab_c", "lab_d", "lab_e",
                  "po_status", "po_exceptions", "po_late", "nc_summary", "nc_detail"}

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
         "needs_projects": True, "views": True},
        {"id": "lab_b", "menu": labour, "label": "Employee Summary",
         "desc": "Department → employee: entries, hours, OT and labour cost, one row per employee.",
         "needs_projects": True, "views": True},
        {"id": "lab_c", "menu": labour, "label": "Job-Category Summary",
         "desc": "Department → labour category (Hour Description) with % of department hours.",
         "needs_projects": True, "views": True},
        {"id": "lab_d", "menu": labour, "label": "Employee Job Detail",
         "desc": "Department → employee → job-detail lines (the timecard note per task).",
         "needs_projects": True, "views": True},
        {"id": "lab_e", "menu": labour, "label": "Project Labour Spend",
         "desc": f"{proj} → department → employee — entries, hours, OT and labour cost.",
         "needs_projects": True, "views": True},
        # ── Purchasing (the deployed PO reports) ───────────────────────────
        {"id": "po_status", "menu": "Purchasing", "label": "PO Status",
         "desc": f"Open PO lines On Order / Overdue, grouped {proj.lower()} → machine, with an "
                 "overdue-aging summary. Export includes the Contents & Summary sheet.",
         "needs_projects": True},
        {"id": "po_exceptions", "menu": "Purchasing", "label": "Procurement Exceptions",
         "desc": "OPEN PO lines (receiver-log based) past their need-by, one sortable row per "
                 "project-item, by buyer. Forward-looking / at-risk.",
         "needs_projects": True},
        {"id": "po_late", "menu": "Purchasing", "label": "Late Vendors",
         "desc": "Open PO lines overdue against their need-by (revised, else required — ETO's "
                 "lateness definition), by vendor. Days Late = today − need-by.",
         "needs_projects": True},
        # ── Non-Conformance ───────────────────────────────────────────────
        {"id": "nc_summary", "menu": "Non-Conformance", "label": "Summary",
         "desc": "NCR counts by source, split open vs closed.",
         "needs_projects": True},
        {"id": "nc_detail", "menu": "Non-Conformance", "label": "Details",
         "desc": "NCR list — status, source, origin, part, supplier, PO, closed date.",
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
        mats = {int(pid): _num(rec.get("MatActual"))
                for pid, rec in self._overlay_map().items() if pid.isdigit()}
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
        rows = []
        for pid in fin:
            f = fin[pid]
            rec = ov.get(str(pid), {})
            name, client = meta.get(pid, (None, None))
            disc_pct = {d.discipline: d.consumed_pct for d in (f.disciplines if f else [])}
            rows.append(_exec_row(pid, name, client, f, rec, disc_pct))
        return _finalize_exec(rows)

    def _q_scorecard(self, project_ids, **kw):
        fin = self._financials(project_ids)
        ov = self._overlay_map()
        rows = []
        for pid in sorted(fin):
            f = fin[pid]
            rec = ov.get(str(pid), {})
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

    def _labour(self, project_ids, report_id, date_from, date_to, view):
        period_df, life_df, p_label, l_label = self._labour_frames(project_ids, date_from, date_to)
        return _spec_labour_result(report_id, period_df, life_df, view, p_label, l_label)

    def _labour_frames(self, project_ids, date_from, date_to):
        import datetime as _dt
        dto = _as_date(date_to) or _dt.date.today()
        dfrom = _as_date(date_from) or etospec.period_to_date(dto)[0]
        pids = [int(p) for p in project_ids] if project_ids else None
        period_df = self._df(etospec.query_daily_labour(dfrom, dto, pids))
        active = set(period_df["ProjectID"].dropna().unique()) if not period_df.empty else set()
        life_df = (self._df(etospec.query_daily_labour(None, dto, list(active)))
                   if active else period_df.iloc[0:0])
        p_label = f"Pay-period-to-date: {dfrom:%b %d} – {dto:%b %d, %Y}"
        l_label = f"Project lifetime-to-date (through {dto:%b %d, %Y})"
        return period_df, life_df, p_label, l_label

    def _q_lab_a(self, project_ids, date_from=None, date_to=None, view="period", **kw):
        return self._labour(project_ids, "lab_a", date_from, date_to, view)

    def _q_lab_b(self, project_ids, date_from=None, date_to=None, view="period", **kw):
        return self._labour(project_ids, "lab_b", date_from, date_to, view)

    def _q_lab_c(self, project_ids, date_from=None, date_to=None, view="period", **kw):
        return self._labour(project_ids, "lab_c", date_from, date_to, view)

    def _q_lab_d(self, project_ids, date_from=None, date_to=None, view="period", **kw):
        return self._labour(project_ids, "lab_d", date_from, date_to, view)

    def _q_lab_e(self, project_ids, date_from=None, date_to=None, view="period", **kw):
        return self._labour(project_ids, "lab_e", date_from, date_to, view)

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

    def _q_nc_summary(self, project_ids, date_from=None, date_to=None, **kw):
        return _nc_summary_result(
            _live_nc_rows(self._eto_conn().cursor(), project_ids, date_from, date_to))

    def _q_nc_detail(self, project_ids, date_from=None, date_to=None, **kw):
        rows = _live_nc_rows(self._eto_conn().cursor(), project_ids, date_from, date_to)
        rows.sort(key=lambda r: (r.get("Status") != "Open", -(r.get("NCR") or 0)))
        return _nc_detail_result(rows)


# ─────────────────────────────────────────────────────────────────────────────
# Shared result builders (used by both live and demo backends)
# ─────────────────────────────────────────────────────────────────────────────
def _scorecard_result(rows):
    proj, labour, material = L("project"), L("labour"), L("material")
    cols = [
        QueryColumn("ProjectID", proj, "id", "left"),
        QueryColumn("LabourBudget", f"{labour} Budget (hrs)", "hours", "right"),
        QueryColumn("LabourActual", f"{labour} Actual (hrs)", "hours", "right"),
        QueryColumn("LabourPct", f"{labour} %", "pct", "right"),
        QueryColumn("MaterialBudget", f"{material} Budget", "money", "right"),
        QueryColumn("MaterialActual", f"{material} Actual", "money", "right"),
        QueryColumn("MaterialPct", f"{material} %", "pct", "right"),
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
    return QueryResult("scorecard", f"{proj} {L('scorecard')}", cols, rows, cards)


def _discipline_result(rows):
    proj, disc = L("project"), L("discipline")
    cols = [
        QueryColumn("ProjectID", proj, "id", "left"),
        QueryColumn("Discipline", disc, "text", "left"),
        QueryColumn("BudgetHours", "Budget (hrs)", "hours", "right"),
        QueryColumn("ActualHours", "Actual (hrs)", "hours", "right"),
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
        QueryColumn("LabourActual", f"{labour} Actual (hrs)", "hours", "right"),
        QueryColumn("LabourVar", f"{labour} Variance (hrs)", "hours", "right"),
        QueryColumn("LabourPct", f"{labour} %", "pct", "right"),
        QueryColumn("MaterialBudget", f"{material} Budget", "money", "right"),
        QueryColumn("MaterialActual", f"{material} Actual", "money", "right"),
        QueryColumn("MaterialVar", f"{material} Variance", "money", "right"),
        QueryColumn("MaterialPct", f"{material} %", "pct", "right"),
    ]
    cards = [Card(L("projects"), str(len(rows)))]
    return QueryResult("budget_actual", "Budget vs Actual", cols, rows, cards)


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
        QueryColumn("LabHrs2wk", f"Δ {labour} Hrs", "hours", "right", "2-Week Delta"),
        QueryColumn("MatSpend2wk", f"Δ {material} $", "money", "right", "2-Week Delta"),
    ]
    # Labour by discipline (block band reads as the labour word, per the workbook)
    for d in _EXEC_DISC_ORDER:
        cols.append(QueryColumn(f"disc::{d}", _EXEC_DISC_SHORT[d], "pct", "right", labour))
    # Procurement
    for key, lab in [("TotalLineItems", "Line Items"), ("LLTPOrdered", "LLTP Ord."),
                     ("LLTPRelLate", "LLTP Rel. Late"), ("LLTPOrdLate", "LLTP Ord. Late"),
                     ("LLTPDelLate", "LLTP Del. Late"), ("PartsRelLate", "Parts Rel. Late"),
                     ("PartsOrdLate", "Parts Ord. Late")]:
        cols.append(QueryColumn(key, lab, "int", "right", "Procurement"))
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
    note = (f"Budget & {L('labour')} blocks: ETO (live)  ·  Schedule & Procurement: "
            f"manual overlay  ·  lead metric = {L('labour')} % (hrs)")
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


def _spec_labour_result(report_id, period_df, life_df, view, p_label, l_label):
    """Build a labour QueryResult for the requested view, stashing BOTH views'
    grouped rows in `export` so the xlsx writer can emit the two-sheet workbook."""
    meta = etospec.LABOUR_REPORTS[report_id]
    period_rows = meta["builder"](period_df)
    life_rows = meta["builder"](life_df)
    active = life_rows if view == "life" else period_rows
    label = l_label if view == "life" else p_label
    view_name = "Project Lifetime" if view == "life" else "This Pay Period"

    qcols = [QueryColumn(k, l, t, a, "", w) for (k, l, t, a, w) in etospec.web_columns(meta["cols"])]
    rows = etospec.web_rows(meta["cols"], active)
    cards = _spec_labour_cards(meta["cols"], active)
    note = (f"{meta['title']} — {view_name} ({label}). Applied-rate cost = Hours × HourRate × "
            "HourFactor; OT Hours = HourFactor > 1. Labour Category = Hour Description; "
            "Job Detail = the timecard note (TimecardCustom1).")
    export = {"kind": "labour", "report_id": report_id,
              "period_rows": period_rows, "life_rows": life_rows,
              "p_label": p_label, "l_label": l_label}
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
    note = ("PO Status — On Order, Overdue. Open = Received < Qty; Overdue = revised/required "
            "date is past. Grouped by project → machine, with an overdue-aging summary; the "
            "Excel export adds the Contents & Summary landing sheet.")
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
    note = ("Procurement Exceptions by Buyer — OPEN PO lines (open = Received < PurchaseQty) past "
            "their need-by (Del Late; need-by = revised, else required — ETO's own definition). "
            "One sortable row per project-item. Ord Late is a DERIVED early-warning "
            "(PO cut too late for the item's lead time) — it has no equivalent in ETO's late report, "
            "so treat it as advisory, not an ETO figure."
            + ("" if enriched else " Lead-time source unavailable, so LLT / Critical / Ord Late are "
               "blank (Del Late still fully evaluated)."))
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
    note = ("Late Vendors — OPEN PO lines (Received < PurchaseQty) whose need-by (revised, else "
            "required — ETO's own lateness definition, per urpPurchasingLateVendors) is already "
            "past, grouped by vendor. Days Late = today − need-by. Uses pod.Received only (no "
            "receiver log). Historical 'received-but-late' lines are ETO's native report; they "
            "need the receiver-log receipt date and are not shown here.")
    return QueryResult("po_late", "Purchasing — Late Vendors", qcols, rows, cards, note,
                       {"kind": "late", "df": df, "label": label})


# ---- Non-Conformance -----------------------------------------------------
_NC_COLMAP = {   # tolerant lookup: our key -> candidate view column names
    "id": ["NonConformanceID", "NCRNumber", "NCNumber"],
    "source": ["SourceDescription", "NonConformanceSourceDescription"],
    "origin": ["NonConformanceOriginDescription", "OriginDescription"],
    "part": ["PartNumber", "PartNo"],
    "partdesc": ["PartDescription"],
    "supplier": ["Supplier"],
    "customer": ["Customer"],
    "resolved": ["Resolved"],
    "closed": ["Released", "ClosedDate", "DateClosed"],
    "po": ["PurchaseOrderID"],
    "raised": ["NonConformanceDate", "DateEntered", "Created", "CreatedDate"],
}


def _nc_pick(rec, key):
    for cand in _NC_COLMAP[key]:
        if cand in rec:
            return rec[cand]
    return None


def _live_nc_rows(cur, pids, dfrom, dto):
    cur.execute(f"SELECT * FROM dbo.vwNonConformances WHERE ProjectID IN ({_ids_sql(pids)})")
    cols = [d[0] for d in cur.description]
    out = []
    for raw in cur.fetchall():
        rec = dict(zip(cols, raw))
        raised = _as_date(_nc_pick(rec, "raised"))
        if dfrom and raised and raised < _as_date(dfrom):
            continue
        if dto and raised and raised > _as_date(dto):
            continue
        resolved = _nc_pick(rec, "resolved")
        out.append({
            "NCR": _nc_pick(rec, "id"),
            "ProjectID": _int(rec.get("ProjectID")),
            "Status": "Closed" if (resolved in (1, True, "1")) else "Open",
            "Source": _nc_pick(rec, "source"),
            "Origin": _nc_pick(rec, "origin"),
            "Part": _nc_pick(rec, "part"),
            "Supplier": _nc_pick(rec, "supplier"),
            "PO": _int(_nc_pick(rec, "po")),
            "Closed": _iso(_nc_pick(rec, "closed")),
        })
    return out


def _nc_summary_result(rows):
    """rows here are the detail NC dicts; roll up by source × status."""
    agg = {}
    for r in rows:
        src = r.get("Source") or "(unspecified)"
        a = agg.setdefault(src, {"Open": 0, "Closed": 0})
        a[r["Status"]] = a.get(r["Status"], 0) + 1
    out = [{"Source": s, "Open": v["Open"], "Closed": v["Closed"],
            "Total": v["Open"] + v["Closed"]} for s, v in sorted(agg.items())]
    cols = [
        QueryColumn("Source", "Source", "text", "left"),
        QueryColumn("Open", "Open", "int", "right"),
        QueryColumn("Closed", "Closed", "int", "right"),
        QueryColumn("Total", "Total", "int", "right"),
    ]
    tot_open = sum(r["Open"] for r in out)
    cards = [Card("NCRs", str(len(rows))),
             Card("Open", str(tot_open), "bad" if tot_open else "good"),
             Card("Closed", str(sum(r["Closed"] for r in out)))]
    return QueryResult("nc_summary", "Non-Conformance Summary", cols, out, cards,
                       "Open = Resolved bit is 0; live from ETO.")


def _nc_detail_result(rows):
    cols = [
        QueryColumn("NCR", "NCR", "id", "left"),
        QueryColumn("ProjectID", "Proj ID", "id", "left"),
        QueryColumn("Status", "Status", "text", "left"),
        QueryColumn("Source", "Source", "text", "left"),
        QueryColumn("Origin", "Origin", "text", "left"),
        QueryColumn("Part", "Part", "text", "left"),
        QueryColumn("Supplier", "Supplier", "text", "left"),
        QueryColumn("PO", "PO", "id", "left"),
        QueryColumn("Closed", "Closed", "date", "left"),
    ]
    openn = sum(1 for r in rows if r.get("Status") == "Open")
    cards = [Card("NCRs", str(len(rows))),
             Card("Open", str(openn), "bad" if openn else "good")]
    return QueryResult("nc_detail", "Non-Conformance Detail", cols, rows, cards,
                       "PO link is 70% null (LEFT JOIN); live from ETO.")


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

    def _labour_demo(self, project_ids, report_id, view):
        return _spec_labour_result(report_id,
                                   self._demo_labour_df(project_ids, lifetime=False),
                                   self._demo_labour_df(project_ids, lifetime=True), view,
                                   "Pay-period-to-date (demo)", "Project lifetime-to-date (demo)")

    def _q_lab_a(self, project_ids, date_from=None, date_to=None, view="period", **kw):
        return self._labour_demo(project_ids, "lab_a", view)

    def _q_lab_b(self, project_ids, date_from=None, date_to=None, view="period", **kw):
        return self._labour_demo(project_ids, "lab_b", view)

    def _q_lab_c(self, project_ids, date_from=None, date_to=None, view="period", **kw):
        return self._labour_demo(project_ids, "lab_c", view)

    def _q_lab_d(self, project_ids, date_from=None, date_to=None, view="period", **kw):
        return self._labour_demo(project_ids, "lab_d", view)

    def _q_lab_e(self, project_ids, date_from=None, date_to=None, view="period", **kw):
        return self._labour_demo(project_ids, "lab_e", view)

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
        return _spec_late_result(df, "POs created — all history (demo)")

    def _q_nc_summary(self, project_ids, date_from=None, date_to=None, **kw):
        return _nc_summary_result(self._nc_rows(project_ids))

    def _q_nc_detail(self, project_ids, date_from=None, date_to=None, **kw):
        rows = self._nc_rows(project_ids)
        rows.sort(key=lambda r: (r["Status"] != "Open", -(r["NCR"] or 0)))
        return _nc_detail_result(rows)

    def _nc_rows(self, project_ids):
        rows = []
        for pid in self._sel(project_ids):
            for ncr, status, source, origin, part, supplier, po, closed in _DEMO_NC[pid]:
                rows.append({"NCR": ncr, "ProjectID": pid, "Status": status,
                             "Source": source, "Origin": origin, "Part": part,
                             "Supplier": supplier, "PO": po, "Closed": closed})
        return rows


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
_DEMO_NC = {   # pid -> [(ncr, status, source, origin, part, supplier, po, closed)]
    230219: [(7714, "Open", "Receiving Inspection", "Supplier", "P-10231", "Bosch Rexroth", 48210, None),
             (7702, "Closed", "In-Process", "Machining", "M-5521", None, None, "2026-06-02"),
             (7688, "Closed", "Final Inspection", "Assembly", "A-3300", None, None, "2026-05-20")],
    230312: [(7731, "Open", "In-Process", "Welding", "W-2210", None, None, None)],
    240087: [(7750, "Open", "Receiving Inspection", "Supplier", "S-9001", "Nachi", 48301, None)],
}
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
