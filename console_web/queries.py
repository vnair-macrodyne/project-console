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
    type: str = "text"        # text | int | hours | money | pct | date | days
    align: str = "left"       # left | right
    block: str = ""           # group-band label (Executive Dashboard); "" = ungrouped


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
              "labour_summary", "labour_detail", "po_summary", "po_detail",
              "nc_summary", "nc_detail"}

# families that read ETO live and honour the optional date range
ETO_REPORT_IDS = {"labour_summary", "labour_detail", "po_summary", "po_detail",
                  "nc_summary", "nc_detail"}


def catalogue():
    """Built per call so labels reflect the current tenant lexicon.
    Each entry carries a `family` so the UI can group the suite."""
    proj, disc = L("project"), L("discipline")
    labour, material = L("labour"), L("material")
    pc = "Project Console"
    return [
        {"id": "exec", "family": pc, "label": "Executive Dashboard",
         "desc": "The full ranked board — schedule, budget, 2-week delta, labour by "
                 f"{disc.lower()} and procurement — one row per {proj.lower()}.",
         "needs_projects": True},
        {"id": "scorecard", "family": pc, "label": f"{proj} {L('scorecard')}",
         "desc": f"One row per {proj.lower()}: {labour.lower()} & {material.lower()} "
                 f"budget vs actual, schedule, progress, rank.",
         "needs_projects": True},
        {"id": "discipline", "family": pc, "label": f"{disc} Financials",
         "desc": f"Per-{disc.lower()} budgeted vs actual hours, consumed % and remaining hours.",
         "needs_projects": True},
        {"id": "budget_actual", "family": pc, "label": "Budget vs Actual",
         "desc": f"{labour}-hours and {material.lower()}-$ budget, actual, variance and "
                 f"consumed % per {proj.lower()}.",
         "needs_projects": True},
        {"id": "crosswalk", "family": pc, "label": L("crosswalk"),
         "desc": f"The {L('hour_description')} → {disc.lower()} mapping (reference).",
         "needs_projects": False},
        # ── Labour (ETO, live) ────────────────────────────────────────────
        {"id": "labour_summary", "family": labour, "label": f"{labour} Summary",
         "desc": f"Actual hours & cost (applied rate) by {proj.lower()} and department.",
         "needs_projects": True},
        {"id": "labour_detail", "family": labour, "label": f"{labour} Detail",
         "desc": "Timecard-level audit trail — date, employee, department, hours, rate, cost.",
         "needs_projects": True},
        # ── Purchase (ETO, live) ──────────────────────────────────────────
        {"id": "po_summary", "family": "Purchase", "label": "Purchase Summary",
         "desc": f"PO commitment by vendor for the selected {proj.lower()}s (extended value).",
         "needs_projects": True},
        {"id": "po_detail", "family": "Purchase", "label": "Purchase Detail",
         "desc": "PO line items — order, date, vendor, item, extended value, received.",
         "needs_projects": True},
        # ── Non-Conformance (ETO, live) ───────────────────────────────────
        {"id": "nc_summary", "family": "Non-Conformance", "label": "Non-Conformance Summary",
         "desc": "NCR counts by source, split open vs closed.",
         "needs_projects": True},
        {"id": "nc_detail", "family": "Non-Conformance", "label": "Non-Conformance Detail",
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
    def _q_labour_summary(self, project_ids, date_from=None, date_to=None, **kw):
        return _live_labour_summary(self._eto_conn().cursor(), project_ids, date_from, date_to)

    def _q_labour_detail(self, project_ids, date_from=None, date_to=None, **kw):
        return _live_labour_detail(self._eto_conn().cursor(), project_ids, date_from, date_to)

    def _q_po_summary(self, project_ids, date_from=None, date_to=None, **kw):
        return _live_po_summary(self._eto_conn().cursor(), project_ids, date_from, date_to)

    def _q_po_detail(self, project_ids, date_from=None, date_to=None, **kw):
        return _live_po_detail(self._eto_conn().cursor(), project_ids, date_from, date_to)

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
        QueryColumn("HourDescription", L("hour_description"), "text", "left"),
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
        QueryColumn("Project", L("project"), "text", "left", ""),
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


# ---- Labour --------------------------------------------------------------
def _labour_summary_result(rows):
    proj, labour = L("project"), L("labour")
    cols = [
        QueryColumn("ProjectID", "Proj ID", "id", "left"),
        QueryColumn("Project", proj, "text", "left"),
        QueryColumn("Department", "Department", "text", "left"),
        QueryColumn("Employees", "Employees", "int", "right"),
        QueryColumn("Entries", "Entries", "int", "right"),
        QueryColumn("Hours", "Hours", "hours", "right"),
        QueryColumn("Cost", "Cost", "money", "right"),
    ]
    cards = [
        Card("Total hours", _fmt_hours(sum(r.get("Hours") or 0 for r in rows))),
        Card("Total cost", _fmt_money(sum(r.get("Cost") or 0 for r in rows))),
        Card("Lines", str(len(rows))),
    ]
    note = f"{labour} — applied-rate cost (HourTime × HourRate × HourFactor), live from ETO."
    return QueryResult("labour_summary", f"{labour} Summary", cols, rows, cards, note)


def _labour_detail_result(rows, capped=False):
    labour = L("labour")
    cols = [
        QueryColumn("WorkDate", "Date", "date", "left"),
        QueryColumn("ProjectID", "Proj ID", "id", "left"),
        QueryColumn("Employee", "Employee", "text", "left"),
        QueryColumn("Department", "Department", "text", "left"),
        QueryColumn("HourDescription", L("hour_description"), "text", "left"),
        QueryColumn("HourClass", "Class", "text", "left"),
        QueryColumn("Hours", "Hours", "hours", "right"),
        QueryColumn("Rate", "Rate", "money", "right"),
        QueryColumn("Cost", "Cost", "money", "right"),
    ]
    cards = [Card("Timecards", str(len(rows))),
             Card("Total hours", _fmt_hours(sum(r.get("Hours") or 0 for r in rows))),
             Card("Total cost", _fmt_money(sum(r.get("Cost") or 0 for r in rows)))]
    note = (f"{L('labour')} detail — applied-rate cost, live from ETO, newest first."
            + (_cap_note(rows, "WorkDate") if capped else ""))
    return QueryResult("labour_detail", f"{L('labour')} Detail", cols, rows, cards, note)


def _live_labour_summary(cur, pids, dfrom, dto):
    cur.execute(f"""
        SELECT t.ProjectID, MAX(t.PDescription) AS Project, t.DeptName AS Department,
               COUNT(DISTINCT t.EmployeeID) AS Employees, COUNT(*) AS Entries,
               SUM(t.HourTime) AS Hours,
               SUM(t.HourTime * t.HourRate * t.HourFactor) AS Cost
        FROM dbo.vwTimecards t
        WHERE t.ProjectID IN ({_ids_sql(pids)}){_date_clause('t.TimeDate', dfrom, dto)}
        GROUP BY t.ProjectID, t.DeptName
        ORDER BY t.ProjectID, t.DeptName
    """)
    rows = [{"ProjectID": int(r[0]), "Project": r[1], "Department": r[2],
             "Employees": _int(r[3]), "Entries": _int(r[4]),
             "Hours": _num(r[5]), "Cost": _num(r[6])} for r in cur.fetchall()]
    return _labour_summary_result(rows)


def _live_labour_detail(cur, pids, dfrom, dto):
    cur.execute(f"""
        SELECT TOP {_DETAIL_CAP + 1} CAST(t.TimeDate AS date) AS WorkDate, t.ProjectID,
               t.EmpNumber AS Employee, t.DeptName AS Department,
               t.HourDescription, t.HourClass,
               t.HourTime AS Hours, t.HourRate AS Rate,
               t.HourTime * t.HourRate * t.HourFactor AS Cost
        FROM dbo.vwTimecards t
        WHERE t.ProjectID IN ({_ids_sql(pids)}){_date_clause('t.TimeDate', dfrom, dto)}
        ORDER BY t.TimeDate DESC, t.ProjectID
    """)
    raw = cur.fetchall()
    capped = len(raw) > _DETAIL_CAP
    rows = [{"WorkDate": _iso(r[0]), "ProjectID": int(r[1]), "Employee": str(r[2]),
             "Department": r[3], "HourDescription": r[4], "HourClass": r[5],
             "Hours": _num(r[6]), "Rate": _num(r[7]), "Cost": _num(r[8])}
            for r in raw[:_DETAIL_CAP]]
    return _labour_detail_result(rows, capped)


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
        QueryColumn("Item", "Item", "text", "left"),
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

    # -- ETO report families (canned) ------------------------------------------
    def _q_labour_summary(self, project_ids, date_from=None, date_to=None, **kw):
        rows = []
        for pid in self._sel(project_ids):
            name = _DEMO_EXEC[pid]["name"]
            for dept, emps, entries, hours, cost in _DEMO_LABOUR[pid]:
                rows.append({"ProjectID": pid, "Project": name, "Department": dept,
                             "Employees": emps, "Entries": entries,
                             "Hours": float(hours), "Cost": float(cost)})
        return _labour_summary_result(rows)

    def _q_labour_detail(self, project_ids, date_from=None, date_to=None, **kw):
        rows = []
        for pid in self._sel(project_ids):
            for d, emp, dept, hd, ot, hrs, rate in _DEMO_LABOUR_DETAIL[pid]:
                rows.append({"WorkDate": d, "ProjectID": pid, "Employee": emp,
                             "Department": dept, "HourDescription": hd,
                             "HourClass": ("Overtime" if ot == "OT" else "Regular"),
                             "Hours": float(hrs), "Rate": float(rate),
                             "Cost": round(hrs * rate * (1.5 if ot == "OT" else 1.0), 2)})
        rows.sort(key=lambda r: r["WorkDate"], reverse=True)
        return _labour_detail_result(rows, capped=False)

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
            "color": TENANT.header_color, "lexicon": dict(TENANT.lexicon)}
