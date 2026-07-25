"""
console_store.py — persistence layer for Project Console.

Two connections, cleanly separated. The Console store has NO link to ETO — Python is
the only bridge, so the store technology is swappable (SQL Server today; Postgres/cloud
for a future SaaS by reimplementing this module — the engine and dashboard don't change).

  * eto_connection()      — READ-ONLY to the vendor ETO SQL Server (actuals).
  * console_connection()  — read/write to the Console store (budgets/PM/crosswalk/history).

Repository reads used by the engine + dashboard:
  * load_crosswalk(conn)      -> {HourDescription: discipline}       (tlkpDisciplineCrosswalk)
  * read_manual_overlay(conn) -> overlay DataFrame (same shape as console_pack.read_pack_overlay)

This module is the seam. Everything ETO stays behind eto_connection(); everything
Console stays behind console_connection().
"""
import os

import pandas as pd

from console_config import TENANT

# vw_Console_ManualOverlay column -> dashboard overlay key (mirrors console_pack output)
_OVERLAY_MAP = {
    "POShipDate": "POShipDate",
    "CustAgreedShipDate": "CustAgreedDate",
    "PMHours": "BudgetHrs::Project Management",
    "MechanicalHours": "BudgetHrs::Mechanical Engineering",
    "ElectricalHours": "BudgetHrs::Electrical Engineering",
    "HydraulicHours": "BudgetHrs::Hydraulic Engineering",
    "ManufacturingHours": "BudgetHrs::Manufacturing",
    "PlannedShipDate": "PlannedShipDate",
    "PercentComplete": "PctDone",
    "LabourRunout": "RunoutLabour",
    "MaterialRunout": "RunoutMaterial",
    "MaterialActual": "MatActual",
    "TotalLineItems": "TotalLineItems",
    "LLTPOrdered": "LLTPOrdered",
    "LLTPReleasedLate": "LLTPRelLate",
    "LLTPOrderedLate": "LLTPOrdLate",
    "LLTPDeliveredLate": "LLTPDelLate",
    "PartsReleasedLate": "PartsRelLate",
    "PartsOrderedLate": "PartsOrdLate",
    "Delta1WkPercentDone": "PctDoneDelta",
    "Delta1WkMaterial": "MatSpend2wk",
    "ReRank": "Rank",
}


# ─────────────────────────────────────────────────────────────────────────────
# Connections
# ─────────────────────────────────────────────────────────────────────────────
def eto_connection():
    """Read-only connection to the vendor ETO SQL Server (reuses the proven connector)."""
    try:
        from console_engine import _connect
        return _connect()
    except Exception:
        import pyodbc
        cs = (f"Driver={{ODBC Driver 17 for SQL Server}};Server={TENANT.eto_server};"
              f"Database={TENANT.eto_database};")
        if TENANT.use_windows_auth:
            cs += "Trusted_Connection=yes;"
        else:
            cs += f"UID={os.environ.get('ETO_USER')};PWD={os.environ.get('ETO_PWD')};"
        return pyodbc.connect(cs)


def console_connection():
    """Read/write connection to the Console store (Macrodyne_Reporting today)."""
    import pyodbc
    return pyodbc.connect(TENANT.reporting_conn_str())


# ─────────────────────────────────────────────────────────────────────────────
# Repository reads
# ─────────────────────────────────────────────────────────────────────────────
def load_crosswalk(conn):
    """HourDescription → discipline, from the Console store (source of truth)."""
    cur = conn.cursor()
    cur.execute("SELECT HourDescription, Discipline FROM Reporting.tlkpDisciplineCrosswalk")
    return {r[0]: r[1] for r in cur.fetchall()}


def _shape_overlay(records, columns):
    """Map vw_Console_ManualOverlay rows to the dashboard's overlay column names."""
    raw = pd.DataFrame.from_records(records, columns=columns)
    if raw.empty:
        return raw
    out = pd.DataFrame()
    out["ProjectID"] = raw["ProjectID"].astype(str)
    for src, key in _OVERLAY_MAP.items():
        if src in raw.columns:
            out[key] = raw[src]
    return out


def read_manual_overlay(conn):
    """Overlay frame from the Console store — drop-in for console_pack.read_pack_overlay."""
    cur = conn.cursor()
    cur.execute("SELECT * FROM Reporting.vw_Console_ManualOverlay")
    cols = [d[0] for d in cur.description]
    return _shape_overlay(cur.fetchall(), cols)
