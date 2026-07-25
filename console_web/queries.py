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
              "labour_proj", "labour_dept", "labour_wages", "labour_detail", "labour_spend",
              "po_summary", "po_detail", "po_exception",
              "nc_summary", "nc_detail"}

# reports that read ETO live and honour the optional date range
ETO_REPORT_IDS = {"labour_proj", "labour_dept", "labour_wages", "labour_detail", "labour_spend",
                  "po_summary", "po_detail", "po_exception", "nc_summary", "nc_detail"}


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
        # ── Labour (replicates the eto-reporting labour suite) ─────────────
        {"id": "labour_proj", "menu": labour, "label": "Project Costing",
         "desc": f"{proj} → department → labour category → job detail: hours & applied-rate cost.",
         "needs_projects": True},
        {"id": "labour_dept", "menu": labour, "label": "Departmental Costing",
         "desc": f"Department → {proj.lower()} → labour category: hours & applied-rate cost.",
         "needs_projects": True},
        {"id": "labour_wages", "menu": labour, "label": "Wages Payable",
         "desc": f"Employee → {proj.lower()} → job detail by date, with rate and payable.",
         "needs_projects": True},
        {"id": "labour_detail", "menu": labour, "label": "Labour Detail",
         "desc": "Full timecard audit trail — every line, applied-rate cost.",
         "needs_projects": True},
        {"id": "labour_spend", "menu": labour, "label": "Project Labour Spend",
         "desc": f"{proj}s by department & employee — hours & applied-rate cost.",
         "needs_projects": True},
        # ── Purchasing ────────────────────────────────────────────────────
        {"id": "po_summary", "menu": "Purchasing", "label": "Summary",
         "desc": f"PO commitment by vendor for the selected {proj.lower()}s (extended value).",
         "needs_projects": True},
        {"id": "po_detail", "menu": "Purchasing", "label": "Details",
         "desc": "PO line items — order, date, vendor, item, extended value, received.",
         "needs_projects": True},
        {"id": "po_exception", "menu": "Purchasing", "label": "Exception",
         "desc": "Open PO lines delivered-late or ordered-late for lead time, by buyer.",
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

    # -- ETO report families (read from ETO, scoped to projects + date window) --
    def _q_labour_proj(self, project_ids, date_from=None, date_to=None, **kw):
        return _labour_proj_result(_live_labour_costing(self._eto_conn().cursor(), project_ids, date_from, date_to))

    def _q_labour_dept(self, project_ids, date_from=None, date_to=None, **kw):
        return _labour_dept_result(_live_labour_costing(self._eto_conn().cursor(), project_ids, date_from, date_to))

    def _q_labour_wages(self, project_ids, date_from=None, date_to=None, **kw):
        return _live_labour_wages(self._eto_conn().cursor(), project_ids, date_from, date_to)

    def _q_labour_detail(self, project_ids, date_from=None, date_to=None, **kw):
        return _live_labour_detail(self._eto_conn().cursor(), project_ids, date_from, date_to)

    def _q_labour_spend(self, project_ids, date_from=None, date_to=None, **kw):
        return _live_labour_spend(self._eto_conn().cursor(), project_ids, date_from, date_to)

    def _q_po_summary(self, project_ids, date_from=None, date_to=None, **kw):
        return _live_po_summary(self._eto_conn().cursor(), project_ids, date_from, date_to)

    def _q_po_detail(self, project_ids, date_from=None, date_to=None, **kw):
        return _live_po_detail(self._eto_conn().cursor(), project_ids, date_from, date_to)

    def _q_po_exception(self, project_ids, date_from=None, date_to=None, **kw):
        return _live_po_exception(self._eto_conn().cursor(), project_ids, date_from, date_to)

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
_DETAIL_CAP = 5000   # detail rows are capped; UI notes when truncated
_BASE_CCY = "CAD"    # reporting base currency; PO native × PurchaseCurrRate normalises to this
                     # (verified: rate=1.0 on CA rows, ~1.31 on US rows → multiply → CAD)


def _ids_sql(project_ids):
    return ",".join(str(int(p)) for p in project_ids)


def _cap_note(rows, datekey):
    """Explain the detail cap and show how far back the shown rows reach."""
    dates = [r.get(datekey) for r in rows if r.get(datekey)]
    earliest = min(dates) if dates else None
    return (f"  Capped at the most recent {_DETAIL_CAP:,} rows"
            + (f" (only back to {earliest})" if earliest else "")
            + " — scope to fewer projects or set a date range to see older records.")


def _date_clause(col, dfrom, dto):
    parts = []
    if dfrom:
        parts.append(f"{col} >= '{_as_date(dfrom)}'")
    if dto:
        parts.append(f"{col} <= '{_as_date(dto)}'")
    return (" AND " + " AND ".join(parts)) if parts else ""


# ---- Labour (eto-reporting report set — vwTimecards / applied-rate) ----------
_APPLIED = "t.HourTime * t.HourRate * t.HourFactor"
_EMP_NAME = "ISNULL(e.EmpLastName + ', ' + e.EmpFirstName, t.EmpNumber)"
_EMP_JOIN = "LEFT JOIN dbo.tblEmployee e ON e.EmployeeID = t.EmployeeID"

# Column contracts mirror eto_config.py COLS_* — (key, label, type, align, wrap)
_COLS_PROJ = [("ProjectID","Project ID","id","left",False),("JobName","Job Name","text","left",True),
    ("Department","Department","text","left",False),("LaborCategory","Labour Cat.","text","left",False),
    ("JobDetail","Job Detail","text","left",False),("Customer","Customer","text","left",False),
    ("MachineCode","Mach.Code","id","left",False),("Machine","Machine","text","left",False),
    ("RegularOT","Reg/OT","text","left",False),("Employees","Employees","int","right",False),
    ("Entries","Entries","int","right",False),("Hours","Hours","hours","right",False),
    ("LabourCost","Labour Cost","money","right",False)]
_COLS_DEPT = [("Department","Department","text","left",False),("ProjectID","Project ID","id","left",False),
    ("JobName","Job Name","text","left",True),("Customer","Customer","text","left",False),
    ("LaborCategory","Labour Cat.","text","left",False),("MachineCode","Mach.Code","id","left",False),
    ("Machine","Machine","text","left",False),("JobDetail","Job Detail","text","left",False),
    ("RegularOT","Reg/OT","text","left",False),("Employees","Employees","int","right",False),
    ("Entries","Entries","int","right",False),("Hours","Hours","hours","right",False),
    ("LabourCost","Labour Cost","money","right",False)]
_COLS_WAGES = [("EmpNo","Emp No","id","left",False),("Employee","Employee","text","left",False),
    ("Department","Department","text","left",False),("ProjectID","Project ID","id","left",False),
    ("JobName","Job Name","text","left",True),("LaborCategory","Labour Cat.","text","left",False),
    ("RegularOT","Reg/OT","text","left",False),("Machine","Machine","text","left",False),
    ("MachineCode","Mach.Code","id","left",False),("JobDetail","Job Detail","text","left",False),
    ("WorkDate","Date","date","left",False),("Entries","Entries","int","right",False),
    ("Hours","Hours","hours","right",False),("Rate","Rate","money","right",False),
    ("WagesPayable","Wages Payable","money","right",False)]
_COLS_DETAIL = [("Department","Department","text","left",False),("EmpNo","Emp No","id","left",False),
    ("Employee","Employee","text","left",False),("ProjectID","Project ID","id","left",False),
    ("JobName","Job Name","text","left",True),("LaborCategory","Labour Cat.","text","left",False),
    ("RegularOT","Reg/OT","text","left",False),("Machine","Machine","text","left",False),
    ("MachineCode","Mach.Code","id","left",False),("JobDetail","Job Detail","text","left",False),
    ("Customer","Customer","text","left",False),("Rate","Rate","money","right",False),
    ("Factor","Factor","num","right",False),("WorkDate","Date","date","left",False),
    ("Hours","Hours","hours","right",False),("Cost","Cost","money","right",False)]
_COLS_SPEND = [("ProjectID","Project ID","id","left",False),("JobName","Job Name","text","left",True),
    ("Department","Department","text","left",False),("Employee","Employee","text","left",False),
    ("EmpNo","Emp No","id","left",False),("RegularOT","Reg/OT","text","left",False),
    ("Entries","Entries","int","right",False),("Hours","Hours","hours","right",False),
    ("LabourCost","Labour Cost","money","right",False)]

_LAB_NOTE = ("Applied-rate cost (HourTime × HourRate × HourFactor), live from ETO. "
             "Labour Cat. = Hour Description · Reg/OT = Hour Class · Job Detail = spec/line-item "
             "(SDescription) · Mach.Code = SpecID · Machine = equipment type.")


def _cols(defs):
    return [QueryColumn(k, l, t, a, "", w) for (k, l, t, a, w) in defs]


def _lab_cards(rows, cost_key):
    return [Card("Rows", str(len(rows))),
            Card("Total hours", _fmt_hours(sum(r.get("Hours") or 0 for r in rows))),
            Card("Total cost", _fmt_money(sum(r.get(cost_key) or 0 for r in rows)))]


def _labour_result(qid, title, defs, rows, cost_key, capped=False):
    note = _LAB_NOTE + (_cap_note(rows, "WorkDate") if capped else "")
    return QueryResult(qid, title, _cols(defs), rows, _lab_cards(rows, cost_key), note)


def _live_labour_costing(cur, pids, dfrom, dto):
    """Finest grain shared by Project Costing + Departmental Costing."""
    cur.execute(f"""
        SELECT t.ProjectID, t.PDescription AS JobName, t.DeptName AS Department,
               t.HourDescription AS LaborCategory, t.SDescription AS JobDetail, t.Customer,
               CAST(t.SpecID AS int) AS MachineCode, t.MachineTypeName AS Machine, t.HourClass AS RegularOT,
               COUNT(DISTINCT t.EmployeeID) AS Employees, COUNT(*) AS Entries,
               SUM(t.HourTime) AS Hours, SUM({_APPLIED}) AS LabourCost
        FROM dbo.vwTimecards t
        WHERE t.ProjectID IN ({_ids_sql(pids)}){_date_clause('t.TimeDate', dfrom, dto)}
        GROUP BY t.ProjectID, t.PDescription, t.DeptName, t.HourDescription, t.SDescription,
                 t.Customer, CAST(t.SpecID AS int), t.MachineTypeName, t.HourClass
    """)
    return [{"ProjectID": _int(r[0]), "JobName": r[1], "Department": r[2], "LaborCategory": r[3],
             "JobDetail": r[4], "Customer": r[5], "MachineCode": _int(r[6]), "Machine": r[7],
             "RegularOT": r[8], "Employees": _int(r[9]), "Entries": _int(r[10]),
             "Hours": _num(r[11]), "LabourCost": _num(r[12])} for r in cur.fetchall()]


def _labour_proj_result(rows):
    rows = sorted(rows, key=lambda x: (x["ProjectID"] or 0, x["Department"] or "", x["LaborCategory"] or ""))
    return _labour_result("labour_proj", f"{L('labour')} — Project Costing", _COLS_PROJ, rows, "LabourCost")


def _labour_dept_result(rows):
    rows = sorted(rows, key=lambda x: (x["Department"] or "", x["ProjectID"] or 0, x["LaborCategory"] or ""))
    return _labour_result("labour_dept", f"{L('labour')} — Departmental Costing", _COLS_DEPT, rows, "LabourCost")


def _live_labour_wages(cur, pids, dfrom, dto):
    cur.execute(f"""
        SELECT TOP {_DETAIL_CAP + 1} t.EmpNumber AS EmpNo, {_EMP_NAME} AS Employee,
               t.DeptName AS Department, t.ProjectID, t.PDescription AS JobName,
               t.HourDescription AS LaborCategory, t.HourClass AS RegularOT, t.MachineTypeName AS Machine,
               CAST(t.SpecID AS int) AS MachineCode, t.SDescription AS JobDetail,
               CAST(t.TimeDate AS date) AS WorkDate, COUNT(*) AS Entries, SUM(t.HourTime) AS Hours,
               t.HourRate AS Rate, SUM({_APPLIED}) AS WagesPayable
        FROM dbo.vwTimecards t {_EMP_JOIN}
        WHERE t.ProjectID IN ({_ids_sql(pids)}){_date_clause('t.TimeDate', dfrom, dto)}
        GROUP BY t.EmpNumber, {_EMP_NAME}, t.DeptName, t.ProjectID, t.PDescription, t.HourDescription,
                 t.HourClass, t.MachineTypeName, CAST(t.SpecID AS int), t.SDescription,
                 CAST(t.TimeDate AS date), t.HourRate
        ORDER BY t.DeptName, {_EMP_NAME}, CAST(t.TimeDate AS date) DESC
    """)
    raw = cur.fetchall(); capped = len(raw) > _DETAIL_CAP
    rows = [{"EmpNo": r[0], "Employee": r[1], "Department": r[2], "ProjectID": _int(r[3]),
             "JobName": r[4], "LaborCategory": r[5], "RegularOT": r[6], "Machine": r[7],
             "MachineCode": _int(r[8]), "JobDetail": r[9], "WorkDate": _iso(r[10]),
             "Entries": _int(r[11]), "Hours": _num(r[12]), "Rate": _num(r[13]),
             "WagesPayable": _num(r[14])} for r in raw[:_DETAIL_CAP]]
    return _labour_result("labour_wages", f"{L('labour')} — Wages Payable", _COLS_WAGES, rows,
                          "WagesPayable", capped)


def _live_labour_detail(cur, pids, dfrom, dto):
    cur.execute(f"""
        SELECT TOP {_DETAIL_CAP + 1} t.DeptName AS Department, t.EmpNumber AS EmpNo,
               {_EMP_NAME} AS Employee, t.ProjectID, t.PDescription AS JobName,
               t.HourDescription AS LaborCategory, t.HourClass AS RegularOT, t.MachineTypeName AS Machine,
               CAST(t.SpecID AS int) AS MachineCode, t.SDescription AS JobDetail, t.Customer,
               t.HourRate AS Rate, t.HourFactor AS Factor, CAST(t.TimeDate AS date) AS WorkDate,
               t.HourTime AS Hours, {_APPLIED} AS Cost
        FROM dbo.vwTimecards t {_EMP_JOIN}
        WHERE t.ProjectID IN ({_ids_sql(pids)}){_date_clause('t.TimeDate', dfrom, dto)}
        ORDER BY t.TimeDate DESC, t.DeptName, t.EmpNumber
    """)
    raw = cur.fetchall(); capped = len(raw) > _DETAIL_CAP
    rows = [{"Department": r[0], "EmpNo": r[1], "Employee": r[2], "ProjectID": _int(r[3]),
             "JobName": r[4], "LaborCategory": r[5], "RegularOT": r[6], "Machine": r[7],
             "MachineCode": _int(r[8]), "JobDetail": r[9], "Customer": r[10], "Rate": _num(r[11]),
             "Factor": _num(r[12]), "WorkDate": _iso(r[13]), "Hours": _num(r[14]),
             "Cost": _num(r[15])} for r in raw[:_DETAIL_CAP]]
    return _labour_result("labour_detail", f"{L('labour')} Detail", _COLS_DETAIL, rows, "Cost", capped)


def _live_labour_spend(cur, pids, dfrom, dto):
    cur.execute(f"""
        SELECT t.ProjectID, t.PDescription AS JobName, t.DeptName AS Department,
               {_EMP_NAME} AS Employee, t.EmpNumber AS EmpNo, t.HourClass AS RegularOT,
               COUNT(*) AS Entries, SUM(t.HourTime) AS Hours, SUM({_APPLIED}) AS LabourCost
        FROM dbo.vwTimecards t {_EMP_JOIN}
        WHERE t.ProjectID IN ({_ids_sql(pids)}){_date_clause('t.TimeDate', dfrom, dto)}
        GROUP BY t.ProjectID, t.PDescription, t.DeptName, {_EMP_NAME}, t.EmpNumber, t.HourClass
        ORDER BY t.ProjectID, t.DeptName, {_EMP_NAME}
    """)
    rows = [{"ProjectID": _int(r[0]), "JobName": r[1], "Department": r[2], "Employee": r[3],
             "EmpNo": r[4], "RegularOT": r[5], "Entries": _int(r[6]), "Hours": _num(r[7]),
             "LabourCost": _num(r[8])} for r in cur.fetchall()]
    return _labour_result("labour_spend", f"{L('labour')} — Project Spend", _COLS_SPEND, rows, "LabourCost")


# ---- Purchase ------------------------------------------------------------
def _po_summary_result(rows):
    cols = [
        QueryColumn("Vendor", "Vendor", "text", "left"),
        QueryColumn("Curr", "Curr", "text", "left"),
        QueryColumn("POs", "# POs", "int", "right"),
        QueryColumn("Lines", "Lines", "int", "right"),
        QueryColumn("Value", "Ext. Value", "money", "right"),
        QueryColumn("BaseValue", f"Ext. Value ({_BASE_CCY})", "money", "right"),
    ]
    vendors = {r.get("Vendor") for r in rows}
    cards = [Card("Vendors", str(len(vendors))),
             Card(f"Total ({_BASE_CCY})", _fmt_money(sum(r.get("BaseValue") or 0 for r in rows))),
             Card("POs", str(sum(r.get("POs") or 0 for r in rows)))]
    return QueryResult("po_summary", "Purchase Summary", cols, rows, cards,
                       "PO commitment, active POs only, live from ETO. Ext. Value is native "
                       f"currency (see Curr); Ext. Value ({_BASE_CCY}) = native × the PO's "
                       "currency rate (PurchaseCurrRate).")


def _po_detail_result(rows, capped=False):
    cols = [
        QueryColumn("PO", "PO", "id", "left"),
        QueryColumn("PODate", "PO Date", "date", "left"),
        QueryColumn("Vendor", "Vendor", "text", "left"),
        QueryColumn("ProjectID", "Proj ID", "id", "left"),
        QueryColumn("Item", "Item", "text", "left", wrap=True),
        QueryColumn("Qty", "Qty", "num", "right"),
        QueryColumn("UOM", "UOM", "text", "left"),
        QueryColumn("Received", "Received", "num", "right"),
        QueryColumn("Value", "Ext. Value", "money", "right"),
        QueryColumn("Curr", "Curr", "text", "left"),
        QueryColumn("BaseValue", f"Ext. Value ({_BASE_CCY})", "money", "right"),
    ]
    cards = [Card("Lines", str(len(rows))),
             Card(f"Total ({_BASE_CCY})", _fmt_money(sum(r.get("BaseValue") or 0 for r in rows)))]
    note = (f"PO line items, active POs only, live from ETO, newest first. Ext. Value native "
            f"(see Curr); Ext. Value ({_BASE_CCY}) = native × PO rate."
            + (_cap_note(rows, "PODate") if capped else ""))
    return QueryResult("po_detail", "Purchase Detail", cols, rows, cards, note)


def _live_po_summary(cur, pids, dfrom, dto):
    cur.execute(f"""
        SELECT poh.CName AS Vendor, pod.PurchaseCurr AS Curr,
               COUNT(DISTINCT poh.PurchaseOrderID) AS POs, COUNT(*) AS Lines,
               SUM(pod.ExtendedPrice) AS Value,
               SUM(pod.ExtendedPrice *
                   CASE WHEN pod.PurchaseCurrRate > 0 THEN pod.PurchaseCurrRate ELSE 1 END) AS BaseValue
        FROM dbo.vwPurchaseOrderDetails pod
        JOIN dbo.vwPurchaseOrderHeader poh ON poh.PurchaseOrderID = pod.PurchaseOrderID
        WHERE pod.ProjectID IN ({_ids_sql(pids)}) AND poh.PurchaseActive = 1
              {_date_clause('poh.PurchaseDate', dfrom, dto)}
        GROUP BY poh.CName, pod.PurchaseCurr
        ORDER BY BaseValue DESC
    """)
    rows = [{"Vendor": r[0] or "(no vendor)", "Curr": r[1], "POs": _int(r[2]),
             "Lines": _int(r[3]), "Value": _num(r[4]), "BaseValue": _num(r[5])}
            for r in cur.fetchall()]
    return _po_summary_result(rows)


def _live_po_detail(cur, pids, dfrom, dto):
    cur.execute(f"""
        SELECT TOP {_DETAIL_CAP + 1} poh.PurchaseOrderID AS PO,
               CAST(poh.PurchaseDate AS date) AS PODate, poh.CName AS Vendor,
               pod.ProjectID, pod.ItemDescription AS Item,
               pod.PurchaseQty AS Qty, pod.PurchaseUOM AS UOM, pod.Received AS Received,
               pod.ExtendedPrice AS Value, pod.PurchaseCurr AS Curr, pod.PurchaseCurrRate AS Rate
        FROM dbo.vwPurchaseOrderDetails pod
        JOIN dbo.vwPurchaseOrderHeader poh ON poh.PurchaseOrderID = pod.PurchaseOrderID
        WHERE pod.ProjectID IN ({_ids_sql(pids)}) AND poh.PurchaseActive = 1
              {_date_clause('poh.PurchaseDate', dfrom, dto)}
        ORDER BY poh.PurchaseDate DESC, poh.PurchaseOrderID
    """)
    raw = cur.fetchall()
    capped = len(raw) > _DETAIL_CAP
    rows = []
    for r in raw[:_DETAIL_CAP]:
        val, rate = _num(r[8]), _num(r[10])
        if not rate or rate <= 0:      # a 0/negative FX rate is invalid data — don't zero the line
            rate = 1.0
        base = round(val * rate, 2) if val is not None else None
        rows.append({"PO": _int(r[0]), "PODate": _iso(r[1]), "Vendor": r[2],
                     "ProjectID": _int(r[3]), "Item": r[4], "Qty": _num(r[5]), "UOM": r[6],
                     "Received": _num(r[7]), "Value": val, "Curr": r[9], "BaseValue": base})
    return _po_detail_result(rows, capped)


# ---- Purchasing Exception (mirrors eto_exceptions.py) --------------------
_LLT_DAYS = 45   # lead time >= this = long-lead item (matches ETO suite)


def _po_exception_result(rows, enriched):
    cols = [
        QueryColumn("Buyer", "Buyer", "text", "left"),
        QueryColumn("ProjectID", "Proj ID", "id", "left"),
        QueryColumn("PO", "PO", "id", "left"),
        QueryColumn("Vendor", "Vendor", "text", "left"),
        QueryColumn("Item", "Item", "id", "left"),
        QueryColumn("Descr", "Description", "text", "left", wrap=True),
        QueryColumn("Qty", "Qty", "num", "right"),
        QueryColumn("Received", "Rec'd", "num", "right"),
        QueryColumn("ExtValue", "Ext. Value", "money", "right"),
        QueryColumn("NeedBy", "Need-By", "date", "left"),
        QueryColumn("Ordered", "Ordered", "date", "left"),
        QueryColumn("Lead", "Lead (d)", "int", "right"),
        QueryColumn("LLT", "LLT", "text", "left"),
        QueryColumn("OrdLate", "Ord Late", "text", "left"),
        QueryColumn("DelLate", "Del Late", "text", "left"),
        QueryColumn("DaysLate", "Days Late", "int", "right"),
    ]
    dl = sum(1 for r in rows if r.get("DelLate"))
    cards = [Card("Exception lines", str(len(rows))),
             Card("At-risk value", _fmt_money(sum(r.get("ExtValue") or 0 for r in rows)),
                  "bad" if rows else "good"),
             Card("Delivered late", str(dl), "bad" if dl else "good")]
    note = ("Open PO lines (received < ordered) that are delivered-late (need-by past) "
            + ("or ordered-late for lead time, by buyer. " if enriched
               else "— lead-time source unavailable, so Ordered-Late / LLT are blank. ")
            + "Live from ETO.")
    return QueryResult("po_exception", "Purchasing — Exception", cols, rows, cards, note)


def _classify_exceptions(recs, cols, enriched):
    import datetime as _dt
    today = _dt.date.today()
    out = []
    for r in recs:
        d = dict(zip(cols, r))
        need = d.get("DateRevised") or d.get("DateRequired")
        ordered = d.get("Ordered")
        lead = _int(d.get("LeadDays"))
        del_late = bool(need and need < today)
        days_late = (today - need).days if del_late else 0
        ord_late = bool(ordered and lead is not None and need
                        and (ordered + _dt.timedelta(days=lead)) > need)
        if not (del_late or ord_late):
            continue
        out.append({
            "Buyer": d.get("Buyer"), "ProjectID": _int(d.get("ProjectID")),
            "PO": _int(d.get("PO")), "Vendor": d.get("Vendor"), "Item": _int(d.get("Item")),
            "Descr": d.get("Descr"), "Qty": _num(d.get("Qty")), "Received": _num(d.get("Received")),
            "ExtValue": _num(d.get("ExtValue")), "NeedBy": _iso(need), "Ordered": _iso(ordered),
            "Lead": lead, "LLT": "LLT" if (lead is not None and lead >= _LLT_DAYS) else "",
            "OrdLate": "LATE" if ord_late else "", "DelLate": "LATE" if del_late else "",
            "DaysLate": days_late,
        })
    out.sort(key=lambda x: (-(x["DaysLate"] or 0), str(x.get("Buyer") or "")))
    return out


def _live_po_exception(cur, pids, dfrom, dto):
    ids, dc = _ids_sql(pids), _date_clause('poh.PurchaseDate', dfrom, dto)
    base_cols = f"""
           poh.PurchaseOrderID AS PO, pod.ProjectID AS ProjectID, pod.ItemID AS Item,
           pod.ItemDescription AS Descr, poh.CName AS Vendor,
           pod.PurchaseQty AS Qty, pod.Received AS Received, pod.ExtendedPrice AS ExtValue,
           CAST(pod.DateRequired AS date) AS DateRequired,
           CAST(pod.DateRevised AS date) AS DateRevised,
           CAST(poh.PurchaseDate AS date) AS Ordered,
           COALESCE(bu.EmpLastName + ', ' + bu.EmpFirstName, CAST(poh.BuyerID AS varchar(20))) AS Buyer"""
    frm = f"""FROM dbo.vwPurchaseOrderDetails pod
        JOIN dbo.vwPurchaseOrderHeader poh ON poh.PurchaseOrderID = pod.PurchaseOrderID
        LEFT JOIN dbo.tblEmployee bu ON bu.EmployeeID = poh.BuyerID"""
    where = (f"WHERE poh.PurchaseActive = 1 AND (pod.Received IS NULL OR pod.Received < pod.PurchaseQty) "
             f"AND pod.ProjectID IN ({ids}){dc}")
    full = f"SELECT {base_cols}, eim.EstimatedLeadTime AS LeadDays {frm} " \
           f"LEFT JOIN dbo.tblEngItemMaster eim ON eim.ItemID = pod.ItemID {where}"
    nolead = f"SELECT {base_cols}, CAST(NULL AS int) AS LeadDays {frm} {where}"
    enriched = True
    try:
        cur.execute(full)
    except Exception:
        enriched = False
        cur.execute(nolead)
    cols = [d[0] for d in cur.description]
    rows = _classify_exceptions(cur.fetchall(), cols, enriched)
    return _po_exception_result(rows, enriched)


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

    # -- ETO report families (canned; the 5 eto-reporting labour reports) -------
    def _demo_labour_rows(self, project_ids):
        out = []
        for pid in self._sel(project_ids):
            e = _DEMO_EXEC[pid]
            for d, emp, dept, hd, ot, hrs, rate in _DEMO_LABOUR_DETAIL[pid]:
                factor = 1.5 if ot == "OT" else 1.0
                out.append({"Department": dept, "EmpNo": emp, "Employee": f"Emp {emp}",
                            "ProjectID": pid, "JobName": e["name"], "LaborCategory": hd,
                            "RegularOT": ("Overtime" if ot == "OT" else "Regular"),
                            "Machine": f"Equipment - {dept.split()[0]}", "MachineCode": 1,
                            "JobDetail": e["name"],
                            "Customer": e["client"], "Rate": float(rate), "Factor": factor,
                            "WorkDate": d, "Hours": float(hrs), "Cost": round(hrs * rate * factor, 2)})
        return out

    @staticmethod
    def _agg(rows, keys, cost_out):
        agg = {}
        for r in rows:
            k = tuple(r[x] for x in keys)
            a = agg.setdefault(k, {"emps": set(), "Entries": 0, "Hours": 0.0, "cost": 0.0})
            a["emps"].add(r["EmpNo"]); a["Entries"] += 1
            a["Hours"] += r["Hours"]; a["cost"] += r["Cost"]
        out = []
        for k, a in agg.items():
            row = dict(zip(keys, k))
            row["Employees"] = len(a["emps"]); row["Entries"] = a["Entries"]
            row["Hours"] = round(a["Hours"], 2); row[cost_out] = round(a["cost"], 2)
            out.append(row)
        return out

    def _q_labour_proj(self, project_ids, date_from=None, date_to=None, **kw):
        keys = ["ProjectID","JobName","Department","LaborCategory","JobDetail","Customer",
                "MachineCode","Machine","RegularOT"]
        return _labour_proj_result(self._agg(self._demo_labour_rows(project_ids), keys, "LabourCost"))

    def _q_labour_dept(self, project_ids, date_from=None, date_to=None, **kw):
        keys = ["ProjectID","JobName","Department","LaborCategory","JobDetail","Customer",
                "MachineCode","Machine","RegularOT"]
        return _labour_dept_result(self._agg(self._demo_labour_rows(project_ids), keys, "LabourCost"))

    def _q_labour_wages(self, project_ids, date_from=None, date_to=None, **kw):
        keys = ["EmpNo","Employee","Department","ProjectID","JobName","LaborCategory","RegularOT",
                "Machine","MachineCode","JobDetail","WorkDate","Rate"]
        rows = self._agg(self._demo_labour_rows(project_ids), keys, "WagesPayable")
        rows.sort(key=lambda r: (r["Department"], r["Employee"], r["WorkDate"]))
        return _labour_result("labour_wages", f"{L('labour')} — Wages Payable", _COLS_WAGES,
                              rows, "WagesPayable")

    def _q_labour_detail(self, project_ids, date_from=None, date_to=None, **kw):
        rows = self._demo_labour_rows(project_ids)
        rows.sort(key=lambda r: r["WorkDate"], reverse=True)
        return _labour_result("labour_detail", f"{L('labour')} Detail", _COLS_DETAIL, rows, "Cost")

    def _q_labour_spend(self, project_ids, date_from=None, date_to=None, **kw):
        keys = ["ProjectID","JobName","Department","Employee","EmpNo","RegularOT"]
        rows = self._agg(self._demo_labour_rows(project_ids), keys, "LabourCost")
        return _labour_result("labour_spend", f"{L('labour')} — Project Spend", _COLS_SPEND,
                              rows, "LabourCost")

    def _q_po_summary(self, project_ids, date_from=None, date_to=None, **kw):
        agg = {}
        for pid in self._sel(project_ids):
            for po, d, vendor, item, qty, uom, value, recv, curr in _DEMO_PO[pid]:
                a = agg.setdefault((vendor, curr), {"pos": set(), "lines": 0, "value": 0.0, "base": 0.0})
                a["pos"].add(po); a["lines"] += 1
                a["value"] += value; a["base"] += value * _DEMO_FX.get(curr, 1.0)
        rows = [{"Vendor": v, "Curr": c, "POs": len(a["pos"]), "Lines": a["lines"],
                 "Value": a["value"], "BaseValue": round(a["base"], 2)}
                for (v, c), a in sorted(agg.items(), key=lambda kv: -kv[1]["base"])]
        return _po_summary_result(rows)

    def _q_po_detail(self, project_ids, date_from=None, date_to=None, **kw):
        rows = []
        for pid in self._sel(project_ids):
            for po, d, vendor, item, qty, uom, value, recv, curr in _DEMO_PO[pid]:
                rows.append({"PO": po, "PODate": d, "Vendor": vendor, "ProjectID": pid,
                             "Item": item, "Qty": float(qty), "UOM": uom,
                             "Received": float(recv), "Value": float(value), "Curr": curr,
                             "BaseValue": round(value * _DEMO_FX.get(curr, 1.0), 2)})
        rows.sort(key=lambda r: r["PODate"], reverse=True)
        return _po_detail_result(rows, capped=False)

    def _q_po_exception(self, project_ids, date_from=None, date_to=None, **kw):
        rows = [dict(r) for r in _DEMO_EXC if r["ProjectID"] in self._sel(project_ids)]
        rows.sort(key=lambda r: (-(r["DaysLate"] or 0), r["Buyer"]))
        return _po_exception_result(rows, enriched=True)

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
