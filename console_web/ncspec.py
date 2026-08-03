"""
ncspec.py — Non-Conformance (NCR) source + cost roll-ups for the web reporting suite.

Isolated the way `etospec` isolates Labour/Purchase: the SQL against ETO's verified NC
views lives here, plus PURE aggregation helpers that turn normalized NC rows into the
report shapes (costing, by-cause, by-discipline, by-supplier, project-impact, summary).
queries.py builds the QueryResult/columns/cards from these; nothing here touches the UI
or the DB driver, so the roll-ups are unit-testable with plain dicts.

Cost model (verified 2026-07-26 against ETO, see ETO_NCR_SOURCE_DISCOVERY):
  Every cost dimension is pre-summed per NCR in dbo.vwCostingSummed_ByNC:
      TotalNCCostingValue = LaborCostingValue + PurchasedCostingValue
                          + InventoryCostingValue + ExtraCostingValue
  At Macrodyne LABOUR books $0 (no rework time is attributed to NCs), so cost-of-NC is
  overwhelmingly PURCHASED material (remedy POs) + inventory + extra/payables.

Attribution axes exposed per NCR:
  * Source      — where detected  (vwNonConformances.SourceDescription)
  * Origin      — cause category  (NonConformanceOriginDescription)
  * Department  — ETO's maintained responsible dept (tlkpNonConformanceOrigin.DepartmentName)
  * Discipline  — DERIVED from the origin text (Hydraulic/Mechanical/Electrical/…); see
                  derive_discipline(). Keyword-based, deterministic, honest about "Other".
  * Supplier / Customer — vendor & customer attribution (Supplier is set on PO-linked NCRs).

Read-only. ETO stays vendor-owned; we only SELECT.
"""
from datetime import date, datetime

# ── canonical column list on the joined cost query (kept in one place) ──────────
COST_COLUMNS = (
    "NonConformanceID", "NonConformanceBarcode", "ProjectID", "Title", "Resolved",
    "CreationDate", "Released", "PurchaseOrderID", "SourceDescription",
    "NonConformanceOriginID", "NonConformanceOriginDescription",
    "NonConformanceRootCause", "NonConformanceCorrectivePreventiveAction",
    "PartNumber", "Supplier", "Customer", "OriginDepartment",
    "LaborCostingValue", "PurchasedCostingValue", "InventoryCostingValue",
    "ExtraCostingValue", "TotalNCCostingValue",
)


def sql_nc_costs(ids_csv):
    """Scoped transcription of urpNonConformancesWithCosts (LEFT JOIN keeps zero-cost NCRs).

    LEFT JOIN to the costing rollup (COALESCE handled in normalize) and to the origin
    lookup for the ETO-maintained responsible department. SActive = 1 mirrors the proc.
    An empty ids_csv means WHOLE PORTFOLIO (the vwCostingSummed_ByNC rollup is fixed-cost
    regardless of the ProjectID filter, so the dashboard caches the whole-portfolio result
    once and filters per request — see LiveQueryService._nc_by_project).
    """
    scope = f" AND NC.ProjectID IN ({ids_csv})" if ids_csv else ""
    return f"""
    SELECT NC.NonConformanceID, NC.NonConformanceBarcode, NC.ProjectID, NC.Title,
           NC.Resolved, NC.CreationDate, NC.Released, NC.PurchaseOrderID,
           NC.SourceDescription, NC.NonConformanceOriginID,
           NC.NonConformanceOriginDescription,
           NC.NonConformanceRootCause, NC.NonConformanceCorrectivePreventiveAction,
           NC.PartNumber, NC.Supplier, NC.Customer,
           O.DepartmentName AS OriginDepartment,
           C.LaborCostingValue, C.PurchasedCostingValue, C.InventoryCostingValue,
           C.ExtraCostingValue, C.TotalNCCostingValue
    FROM dbo.vwNonConformances NC
    LEFT JOIN dbo.vwCostingSummed_ByNC C ON NC.NonConformanceID = C.NonConformanceID
    LEFT JOIN dbo.tlkpNonConformanceOrigin O
           ON NC.NonConformanceOriginID = O.NonConformanceOriginID
    WHERE NC.SActive = 1{scope}
    """


def sql_nc_outstanding(ids_csv):
    """Per-NCR open corrective-action count (precomputed by ETO on vwNonConformanceList).
    Empty ids_csv = whole portfolio (see sql_nc_costs)."""
    scope = f" WHERE ProjectID IN ({ids_csv})" if ids_csv else ""
    return f"""
    SELECT NonConformanceID, Tasks, Outstanding
    FROM dbo.vwNonConformanceList{scope}
    """


# ── attribution: derive a console discipline from the origin description ────────
# Keyword → discipline. First hit wins; order matters (check specific words first).
_DISCIPLINE_RULES = (
    ("hydraulic", "Hydraulic Engineering"),
    ("electrical", "Electrical Engineering"),
    ("mechanical", "Mechanical Engineering"),
)
UNATTRIBUTED = "Other / Unattributed"


def derive_discipline(origin):
    """Map an NC origin description to a console discipline by keyword; else Other.

    Covers ETO origins like 'Hydraulic Design Error', 'Mechanical Automation Design
    Change', 'Electrical Design Error'. Generic causes (Design/Drawing Error, Supplier
    Machining Error, Part Handling, Purchasing, Specification, Audit, Quality/QA) have no
    discipline in the source, so they land in Other — surfaced honestly, not guessed.
    """
    s = (origin or "").lower()
    for kw, disc in _DISCIPLINE_RULES:
        if kw in s:
            return disc
    return UNATTRIBUTED


# ── helpers ────────────────────────────────────────────────────────────────────
def _f(x):
    """Money/number → float, treating NULL/blank as 0.0 (LEFT JOIN COALESCE)."""
    if x is None or x == "":
        return 0.0
    try:
        return float(x)
    except (TypeError, ValueError):
        return 0.0


def _as_date(x):
    if x is None or x == "":
        return None
    if isinstance(x, datetime):
        return x.date()
    if isinstance(x, date):
        return x
    s = str(x)[:10]
    try:
        return datetime.strptime(s, "%Y-%m-%d").date()
    except ValueError:
        return None


def _iso(x):
    d = _as_date(x)
    return d.isoformat() if d else None


def _clean_client(s):
    """Trim ETO decorations: 'Bosch Rexroth [Concord] (Approved)' → 'Bosch Rexroth'."""
    if not s:
        return None
    s = str(s)
    for sep in (" [", " ("):
        i = s.find(sep)
        if i != -1:
            s = s[:i]
    return s.strip() or None


def normalize(rec):
    """One raw joined record (dict, tolerant to missing keys) → one normalized NC row.

    The single row shape every roll-up and the demo backend share.
    """
    origin = rec.get("NonConformanceOriginDescription")
    resolved = rec.get("Resolved")
    return {
        "NCID": rec.get("NonConformanceID"),
        "NCR": rec.get("NonConformanceBarcode") or rec.get("NonConformanceID"),
        "ProjectID": rec.get("ProjectID"),
        "Title": rec.get("Title"),
        "Status": "Closed" if resolved in (1, True, "1") else "Open",
        "Source": rec.get("SourceDescription") or "(unspecified)",
        "Origin": origin or "(unspecified)",
        "Department": rec.get("OriginDepartment") or "(unassigned)",
        "Discipline": derive_discipline(origin),
        "Part": rec.get("PartNumber"),
        "Supplier": _clean_client(rec.get("Supplier")),
        "Customer": _clean_client(rec.get("Customer")),
        "PO": rec.get("PurchaseOrderID"),
        "Raised": _iso(rec.get("CreationDate")),
        "Closed": _iso(rec.get("Released")),
        "RootCause": rec.get("NonConformanceRootCause"),
        "CAPA": rec.get("NonConformanceCorrectivePreventiveAction"),
        "Labour": _f(rec.get("LaborCostingValue")),
        "Purchased": _f(rec.get("PurchasedCostingValue")),
        "Inventory": _f(rec.get("InventoryCostingValue")),
        "Extra": _f(rec.get("ExtraCostingValue")),
        "Total": _f(rec.get("TotalNCCostingValue")),
    }


def to_rows(records, dfrom=None, dto=None):
    """Normalize + optional CreationDate window (null-tolerant, like the labour reports)."""
    lo, hi = _as_date(dfrom), _as_date(dto)
    out = []
    for rec in records:
        row = normalize(rec)
        raised = _as_date(row.get("Raised"))
        if lo and raised and raised < lo:
            continue
        if hi and raised and raised > hi:
            continue
        out.append(row)
    return out


def attach_outstanding(rows, outstanding_by_nc):
    """Merge {NCID: outstanding_count} onto normalized rows (in place); default 0."""
    for r in rows:
        r["Outstanding"] = int(outstanding_by_nc.get(r.get("NCID"), 0) or 0)
    return rows


# ── material breakdown: purchased + inventory + extra (labour is separate) ──────
def _material(r):
    return r["Purchased"] + r["Inventory"] + r["Extra"]


def totals(rows):
    """Grand totals across the given rows."""
    t = {"NCRs": len(rows), "Open": 0, "Closed": 0,
         "Labour": 0.0, "Purchased": 0.0, "Inventory": 0.0, "Extra": 0.0,
         "Material": 0.0, "Total": 0.0}
    for r in rows:
        t["Open" if r["Status"] == "Open" else "Closed"] += 1
        for k in ("Labour", "Purchased", "Inventory", "Extra", "Total"):
            t[k] += r[k]
        t["Material"] += _material(r)
    return t


def _blank_group():
    return {"NCRs": 0, "Open": 0, "Closed": 0,
            "Labour": 0.0, "Material": 0.0, "Total": 0.0}


def _group_by(rows, keyfn):
    agg = {}
    for r in rows:
        k = keyfn(r) or "(unspecified)"
        g = agg.setdefault(k, _blank_group())
        g["NCRs"] += 1
        g["Open" if r["Status"] == "Open" else "Closed"] += 1
        g["Labour"] += r["Labour"]
        g["Material"] += _material(r)
        g["Total"] += r["Total"]
    return agg


def _rollup(rows, keyfn, keyname):
    """Generic grouped roll-up → list[dict] sorted by Total cost desc, then NCRs desc."""
    agg = _group_by(rows, keyfn)
    out = [{keyname: k, **{kk: round(vv, 2) if isinstance(vv, float) else vv
                           for kk, vv in g.items()}}
           for k, g in agg.items()]
    out.sort(key=lambda d: (-d["Total"], -d["NCRs"], str(d[keyname])))
    return out


def by_cause(rows):
    """Cost by root-cause (Origin) — mirrors urpNonConformanceCostingCompared."""
    return _rollup(rows, lambda r: r["Origin"], "Origin")


def by_discipline(rows):
    """Cost attributed to a derived discipline (Hydraulic/Mechanical/Electrical/Other)."""
    return _rollup(rows, lambda r: r["Discipline"], "Discipline")


def by_department(rows):
    """Cost by ETO's maintained responsible department (origin.DepartmentName)."""
    return _rollup(rows, lambda r: r["Department"], "Department")


def by_supplier(rows):
    """Vendor attribution — supplier is set on PO-linked NCRs; others group as (none)."""
    return _rollup(rows, lambda r: r["Supplier"] or "(no supplier / internal)", "Supplier")


def by_source(rows):
    """Detection-point summary (Source) with cost — the enriched Summary."""
    return _rollup(rows, lambda r: r["Source"], "Source")


def impact(rows, material_actual_by_pid=None):
    """One row per project: NCR counts + cost-of-NC, and NC $ as % of material actual.

    material_actual_by_pid: optional {pid: material_actual_$} to compute the share.
    """
    material_actual_by_pid = material_actual_by_pid or {}
    agg = {}
    for r in rows:
        pid = r["ProjectID"]
        g = agg.setdefault(pid, {"ProjectID": pid, "NCRs": 0, "Open": 0, "Closed": 0,
                                 "Labour": 0.0, "Material": 0.0, "NCCost": 0.0})
        g["NCRs"] += 1
        g["Open" if r["Status"] == "Open" else "Closed"] += 1
        g["Labour"] += r["Labour"]
        g["Material"] += _material(r)
        g["NCCost"] += r["Total"]
    out = []
    for pid, g in agg.items():
        ma = material_actual_by_pid.get(pid) or material_actual_by_pid.get(str(pid))
        g["MaterialActual"] = ma
        g["NCPctOfMaterial"] = (g["NCCost"] / ma) if ma else None
        for k in ("Labour", "Material", "NCCost"):
            g[k] = round(g[k], 2)
        out.append(g)
    out.sort(key=lambda d: (-d["NCCost"], -d["NCRs"], d["ProjectID"]))
    return out


def by_project_totals(rows):
    """{pid: {"open": n, "cost": $}} for the dashboard NC actuals block."""
    out = {}
    for r in rows:
        g = out.setdefault(r["ProjectID"], {"open": 0, "cost": 0.0})
        if r["Status"] == "Open":
            g["open"] += 1
        g["cost"] += r["Total"]
    for g in out.values():
        g["cost"] = round(g["cost"], 2)
    return out
