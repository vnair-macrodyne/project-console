"""
console_sync.py
================
ETL: spreadsheet (Budgets + PM Entries)  →  Macrodyne_Reporting.

Banks the manual half of the Project Console dashboards into the governed Reporting DB so
the dashboard can read stable views instead of parsing cells, and so budgets/PM
entries are versioned. The spreadsheet stays the PM entry point — this just captures
it each week (schedule: weekly, before the executive report).

  * Budgets    → Reporting.tblProjectBudget (SCD-2: new version only when values
                 change) + tblProjectBudgetDetail (fine-grain hours).
  * Crosswalk  → Reporting.tlkpDisciplineCrosswalk (from the Budgets tab grouping).
  * PM entries → Reporting.tblProjectPMEntry (upsert by ProjectID+YearWeekKey;
                 --all-weeks backfills the full history on first run).

Record-builders are pure (no DB) so `--dry-run` validates extraction anywhere.
Connection: env CONSOLE_STORE_SERVER / _DB / _USER / _PWD (or _TRUSTED=1).
"""
from __future__ import annotations

import argparse
import datetime as _dt
import os

import pandas as pd

import console_config  # noqa: F401 — importing loads .env (python-dotenv) into os.environ
import console_pack as cp

_DISC_COLS = {  # budget header column -> Budgets 'Helpers' discipline key
    "PMHours": "BudgetHrs::Project Management",
    "MechanicalHours": "BudgetHrs::Mechanical Engineering",
    "ElectricalHours": "BudgetHrs::Electrical Engineering",
    "HydraulicHours": "BudgetHrs::Hydraulic Engineering",
    "ManufacturingHours": "BudgetHrs::Manufacturing",
}
# fields that define a budget "version" (a change in any → new SCD-2 row)
_BUDGET_COMPARE = ["POShipDate", "CustAgreedShipDate", "MaterialBudget",
                   "LabourBudgetHours", "PMHours", "MechanicalHours",
                   "ElectricalHours", "HydraulicHours", "ManufacturingHours"]


def _d(x):
    try:
        if x is None or pd.isna(x):          # None, NaN, NaT, pd.NA
            return None
    except (TypeError, ValueError):
        pass
    if isinstance(x, _dt.datetime):
        x = x.date()
    if isinstance(x, _dt.date):
        return None if x.year >= 2099 else x
    return None


def _n(x):
    try:
        if x is None or (isinstance(x, float) and pd.isna(x)):
            return None
        return round(float(x), 2)
    except (TypeError, ValueError):
        return None


def _i(x):
    """Coerce to int or None — handles the pack's '-'/blank placeholders."""
    try:
        if x is None or (isinstance(x, float) and pd.isna(x)):
            return None
        if isinstance(x, str) and not x.strip().lstrip("-").isdigit():
            return None
        return int(float(x))
    except (TypeError, ValueError):
        return None


import numpy as _np


def _scrub(x):
    """Make ANY value pyodbc-safe: numpy scalar → native python; NaN/NaT/NA → None.
    This is the single guard that stops DataFrame values (which turn None into NaN,
    and dates into NaT) from ever reaching the SQL driver as an invalid type."""
    if isinstance(x, _np.generic):
        x = x.item()
    try:
        if x is None or pd.isna(x):
            return None
    except (TypeError, ValueError):
        pass
    return x


def _ex(cur, sql, *params):
    """Execute with every bound parameter scrubbed. Use for ALL parameterised writes."""
    return cur.execute(sql, *[_scrub(p) for p in params])


# ─────────────────────────────────────────────────────────────────────────────
# Pure record builders (testable without a DB)
# ─────────────────────────────────────────────────────────────────────────────
def build_budget_records(pack_path):
    """Return (headers_df, detail_df). headers = one row per project (current state)."""
    b = cp.read_budgets_tab(pack_path)
    rows = []
    for _, r in b.iterrows():
        row = {
            "ProjectID": int(r["ProjectID"]),
            "POShipDate": _d(r.get("POShipDate")),
            "CustAgreedShipDate": _d(r.get("CustAgreedDate")),
            "MaterialBudget": _n(r.get("MatBudgetTotal")),
            "LabourBudgetHours": _n(r.get("LabBudgetTotal")),
        }
        for col, key in _DISC_COLS.items():
            row[col] = _n(r.get(key))
        row["OtherHours"] = None
        rows.append(row)
    headers = pd.DataFrame(rows)
    detail = cp.read_budgets_detail(pack_path)
    return headers, detail


def build_pm_records(pack_path, all_weeks=True):
    p = cp.read_pm_entries(pack_path, all_weeks=all_weeks)
    out = []
    for _, r in p.iterrows():
        out.append({
            "ProjectID": int(r["ProjectID"]),
            "FiscalYear": _i(r.get("Year")),
            "WeekNo": _i(r.get("WeekNo")),
            "YearWeekKey": _i(r.get("YearWeekKey")),
            "PlannedShipDate": _d(r.get("PlannedShipDate")),
            "PercentComplete": _n(r.get("PctDone")),
            "LabourRunout": _n(r.get("RunoutLabour")),
            "MaterialRunout": _n(r.get("RunoutMaterial")),
            "MaterialActual": _n(r.get("MatActual")),
            "MaterialBudget": _n(r.get("MatBudget")),
            "TotalLineItems": _i(r.get("TotalLineItems")),
            "LLTPOrdered": _i(r.get("LLTPOrdered")),
            "LLTPReleasedLate": _i(r.get("LLTPRelLate")),
            "LLTPOrderedLate": _i(r.get("LLTPOrdLate")),
            "LLTPDeliveredLate": _i(r.get("LLTPDelLate")),
            "PartsReleasedLate": _i(r.get("PartsRelLate")),
            "PartsOrderedLate": _i(r.get("PartsOrdLate")),
            "Delta1WkPercentDone": _n(r.get("PctDoneDelta")),
            "Delta1WkMaterial": _n(r.get("MatSpend2wk")),
            "IncludeFlag": 1 if str(r.get("Include")).strip().upper() in ("Y", "1", "TRUE") else 0,
            "ReRank": _i(r.get("Rank")),
        })
    return pd.DataFrame(out).dropna(subset=["YearWeekKey"])


def build_crosswalk(pack_path):
    xw = cp.derive_crosswalk_from_budgets(pack_path)
    return pd.DataFrame([{"HourDescription": k, "Discipline": v} for k, v in xw.items()])


# ─────────────────────────────────────────────────────────────────────────────
# DB connection + sync
# ─────────────────────────────────────────────────────────────────────────────
def get_reporting_connection():
    import pyodbc
    server = os.environ.get("CONSOLE_STORE_SERVER", r"MACRO-ETO-SVR\SQLEXPRESS")
    db = os.environ.get("CONSOLE_STORE_DB", "Macrodyne_Reporting")
    if os.environ.get("CONSOLE_STORE_TRUSTED") == "1":
        cs = (f"Driver={{ODBC Driver 17 for SQL Server}};Server={server};"
              f"Database={db};Trusted_Connection=yes;")
    else:
        u = os.environ["CONSOLE_STORE_USER"]
        p = os.environ["CONSOLE_STORE_PWD"]
        cs = (f"Driver={{ODBC Driver 17 for SQL Server}};Server={server};"
              f"Database={db};UID={u};PWD={p};")
    return pyodbc.connect(cs)


def _changed(cur_row, new_row):
    for f in _BUDGET_COMPARE:
        a, b = cur_row.get(f), new_row.get(f)
        if isinstance(a, float) or isinstance(b, float):
            a = None if a is None else round(float(a), 2)
            b = None if b is None else round(float(b), 2)
        if a != b:
            return True
    return False


def sync(conn, pack_path, all_weeks=True, effective=None, by="console_sync"):
    cur = conn.cursor()
    effective = effective or _dt.date.today()
    headers, detail = build_budget_records(pack_path)
    pm = build_pm_records(pack_path, all_weeks=all_weeks)
    xw = build_crosswalk(pack_path)
    stats = {"budget_new": 0, "budget_unchanged": 0, "pm_upserted": 0, "xwalk": len(xw)}

    # crosswalk (delete+insert; tiny table)
    cur.execute("DELETE FROM Reporting.tlkpDisciplineCrosswalk;")
    for _, r in xw.iterrows():
        _ex(cur, "INSERT INTO Reporting.tlkpDisciplineCrosswalk(HourDescription,Discipline) VALUES(?,?)",
            r["HourDescription"], r["Discipline"])

    # budgets — SCD-2.  Every parameterised write goes through _ex → scrubbed binds.
    detail_by_pid = {pid: g for pid, g in detail.groupby(detail["ProjectID"])} if not detail.empty else {}
    for _, new in headers.iterrows():
        pid = int(new["ProjectID"])
        _ex(cur, f"SELECT BudgetVersionID,{','.join(_BUDGET_COMPARE)} "
                 f"FROM Reporting.tblProjectBudget WHERE ProjectID=? AND IsCurrent=1", pid)
        row = cur.fetchone()
        cur_row = dict(zip(["BudgetVersionID"] + _BUDGET_COMPARE, row)) if row else None
        if cur_row and not _changed(cur_row, new):
            stats["budget_unchanged"] += 1
            continue
        if cur_row:
            _ex(cur, "UPDATE Reporting.tblProjectBudget SET IsCurrent=0,EffectiveTo=? "
                     "WHERE BudgetVersionID=?", effective, cur_row["BudgetVersionID"])
        _ex(cur,
            "INSERT INTO Reporting.tblProjectBudget(ProjectID,EffectiveFrom,IsCurrent,Source,"
            "POShipDate,CustAgreedShipDate,MaterialBudget,LabourBudgetHours,PMHours,"
            "MechanicalHours,ElectricalHours,HydraulicHours,ManufacturingHours,OtherHours,CreatedBy) "
            "OUTPUT INSERTED.BudgetVersionID VALUES(?,?,1,?,?,?,?,?,?,?,?,?,?,?,?)",
            pid, effective, f"Budgets.xlsx@{effective}",
            _d(new["POShipDate"]), _d(new["CustAgreedShipDate"]),
            _n(new["MaterialBudget"]), _n(new["LabourBudgetHours"]), _n(new["PMHours"]),
            _n(new["MechanicalHours"]), _n(new["ElectricalHours"]), _n(new["HydraulicHours"]),
            _n(new["ManufacturingHours"]), _n(new["OtherHours"]), by)
        vid = cur.fetchone()[0]
        for _, dr in detail_by_pid.get(str(pid), pd.DataFrame()).iterrows():
            _ex(cur, "INSERT INTO Reporting.tblProjectBudgetDetail(BudgetVersionID,HourDescription,BudgetHours) "
                     "VALUES(?,?,?)", vid, dr["HourDescription"], _n(dr["BudgetHours"]))
        stats["budget_new"] += 1

    # PM entries — upsert by (ProjectID, YearWeekKey)
    for _, r in pm.iterrows():
        _ex(cur, "DELETE FROM Reporting.tblProjectPMEntry WHERE ProjectID=? AND YearWeekKey=?",
            int(r["ProjectID"]), int(r["YearWeekKey"]))
        _ex(cur,
            "INSERT INTO Reporting.tblProjectPMEntry(ProjectID,FiscalYear,WeekNo,YearWeekKey,"
            "PlannedShipDate,PercentComplete,LabourRunout,MaterialRunout,MaterialActual,MaterialBudget,"
            "TotalLineItems,LLTPOrdered,LLTPReleasedLate,LLTPOrderedLate,LLTPDeliveredLate,"
            "PartsReleasedLate,PartsOrderedLate,Delta1WkPercentDone,Delta1WkMaterial,IncludeFlag,ReRank) "
            "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            int(r["ProjectID"]), _i(r["FiscalYear"]), _i(r["WeekNo"]), int(r["YearWeekKey"]),
            _d(r["PlannedShipDate"]), _n(r["PercentComplete"]), _n(r["LabourRunout"]), _n(r["MaterialRunout"]),
            _n(r["MaterialActual"]), _n(r["MaterialBudget"]), _i(r["TotalLineItems"]), _i(r["LLTPOrdered"]),
            _i(r["LLTPReleasedLate"]), _i(r["LLTPOrderedLate"]), _i(r["LLTPDeliveredLate"]), _i(r["PartsReleasedLate"]),
            _i(r["PartsOrderedLate"]), _n(r["Delta1WkPercentDone"]), _n(r["Delta1WkMaterial"]),
            _i(r["IncludeFlag"]), _i(r["ReRank"]))
        stats["pm_upserted"] += 1

    conn.commit()
    return stats


def dry_run(pack_path, all_weeks=True):
    headers, detail = build_budget_records(pack_path)
    pm = build_pm_records(pack_path, all_weeks=all_weeks)
    xw = build_crosswalk(pack_path)
    print(f"BUDGETS:   {len(headers)} projects, {len(detail)} detail rows")
    print(f"PM ENTRIES:{len(pm)} rows across {pm['YearWeekKey'].nunique()} weeks "
          f"({sorted(pm['YearWeekKey'].dropna().astype(int).unique())[:6]}...)")
    print(f"CROSSWALK: {len(xw)} HourDescription→discipline entries")
    print("\nSample budget header (first 3):")
    print(headers.head(3).to_string(index=False))
    print("\nSample PM rows (first 3):")
    cols = ["ProjectID", "YearWeekKey", "PercentComplete", "LabourRunout", "MaterialActual", "ReRank"]
    print(pm[cols].head(3).to_string(index=False))
    return headers, detail, pm, xw


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Sync the Project Console pack into Macrodyne_Reporting.")
    ap.add_argument("--pack", required=True, help="Path to the management workbook (.xlsx)")
    ap.add_argument("--dry-run", action="store_true", help="Show extracted records; no DB writes")
    ap.add_argument("--current-week-only", action="store_true",
                    help="Only sync the pack's Front-Page week (default backfills all weeks)")
    args = ap.parse_args()
    all_weeks = not args.current_week_only
    if args.dry_run:
        dry_run(args.pack, all_weeks=all_weeks)
    else:
        conn = get_reporting_connection()
        try:
            s = sync(conn, args.pack, all_weeks=all_weeks)
        finally:
            conn.close()
        print(f"Sync complete: {s}")