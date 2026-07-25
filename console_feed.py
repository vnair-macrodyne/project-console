"""
console_feed.py
===============
Project Console Executive/Project Dashboard — ETO data feed (Labor Data tab).
See project doc for full header. This copy carries the 2026-07-24 fix:
the "Hour Department" source is vwTimecards.DeptName (pre-resolved), NOT a
nonexistent 'HourDepartment' column on the view (ETO_SCHEMA_MAP §5/§6,
ETO_QUERIES_RECONCILIATION).
"""
from datetime import date, datetime
import pandas as pd

DISCIPLINE_MAP = {
    "Customer Support": "Project Management", "Management": "Project Management",
    "Project Coordination": "Project Management", "Training": "Project Management",
    "Electrical Engineering": "Electrical Engineering",
    "Electrical Programming": "Electrical Engineering",
    "Electrical Shop Start-Up": "Electrical Engineering",
    "Hydraulic Engineering": "Hydraulic Engineering",
    "Hydraulic Shop Start-Up": "Hydraulic Engineering",
    "Mechanical Engineering": "Mechanical Engineering",
    "Electrical Panel Building": "Manufacturing",
    "Electrical shop (NC) Non-Conformance": "Other",
    "Electrical Wiring - Machine": "Manufacturing",
    "Fabrication/Welding (IW)": "Manufacturing",
    "Field Service Start-Up/Testing": "Manufacturing",
    "Machining (IW)": "Manufacturing", "Mechanical Assembly": "Manufacturing",
    "Mechanical Field Service": "Manufacturing",
    "Hydraulic Field Service": "Manufacturing",   # added 2026-07-25 (was missing; Budgets tab → Manufacturing)
    "Mechanical shop (NC) Non-Conformance": "Other", "Painting": "Manufacturing",
    "Receiving": "Manufacturing", "Shipping/Dismantle/Prep": "Manufacturing",
    "Start-up/Testing": "Manufacturing", "Travel Field Service": "Manufacturing",
    "Tubing/Piping": "Manufacturing", "Hydraulic Unit Assembly": "Manufacturing",
    "Manuals": "Mechanical Engineering", "Boring Mill Maintenance": "Project Management",
    "Electrical Field Service": "Manufacturing",
    # 2026-07-25: aligned to the Budgets tab (source of truth) — Electrical Procurement
    # is grouped under Project Management there, so actuals must match for a consistent %.
    "Electrical Procurement": "Project Management",
    "Engineering (NC) Non-Conformance": "Other", "Housekeeping": "Project Management",
    "Hydraulic Shop (NC) Non-Conformance": "Other", "Miscellaneous": "Project Management",
    "Production Meeting": "Project Management", "Purchasing": "Project Management",
    "Quality Management / ISO": "Project Management", "Sales": "Project Management",
}
DISCIPLINES = ["Project Management", "Mechanical Engineering",
    "Hydraulic Engineering", "Electrical Engineering", "Manufacturing", "Other"]
UNMAPPED_DISCIPLINE = "Other"
LABOR_DATA_COLUMNS = ["Project", "Machine", "Hour Department", "Hour Description",
    "Employee", "Date", "Actual Hours", "Actual Cost", "Project ID", "Machine Code",
    "Asset Re-Code", "Year", "Week #", "Year-Week"]


def excel_weeknum(d):
    if isinstance(d, datetime):
        d = d.date()
    jan1 = date(d.year, 1, 1)
    jan1_offset = (jan1.weekday() + 1) % 7
    return (d.timetuple().tm_yday + jan1_offset - 1) // 7 + 1


def query_labor_data(cursor, start_date, end_date):
    """
    Regenerate the dashboard's Labor Data tab from ETO timecards for a date range.
    Returns a DataFrame with LABOR_DATA_COLUMNS (one row per timecard).

    FINALISED 2026-07-24 against live columns (console_diag_cols.py):
      * vwTimecards pre-resolves DeptName, PDescription, SDescription (spec name),
        HourDescription, EmpNumber, TimeDate, HourTime, HourRate, HourFactor — so
        the old tblSpec composite join was dropped (SDescription is on the view).
      * Only tblEmployee is still joined, for the employee's first/last name
        (the view carries EmpNumber but not the name), on EmployeeID.
      * SpecID is a FLOAT on the view — cleaned to an integer-style string below.
    No TODO(verify) columns remain.
    """
    sql = f"""
    SELECT
        t.ProjectID,
        t.PDescription      AS ProjectName,
        t.SpecID,
        t.SDescription      AS MachineName,    -- pre-resolved on the view (no tblSpec join)
        t.DeptName          AS HourDepartment,
        t.HourDescription   AS HourDescription,
        t.EmpNumber         AS EmpNumber,
        e.EmpLastName       AS EmpLastName,
        e.EmpFirstName      AS EmpFirstName,
        CAST(t.TimeDate AS DATE)               AS WorkDate,
        t.HourTime                              AS ActualHours,
        CAST(t.HourTime * t.HourRate * t.HourFactor AS DECIMAL(12,2)) AS ActualCost
    FROM dbo.vwTimecards t
    LEFT JOIN dbo.tblEmployee e ON t.EmployeeID = e.EmployeeID
    WHERE t.TimeDate >= '{start_date.strftime('%Y-%m-%d')}'
      AND t.TimeDate <= '{end_date.strftime('%Y-%m-%d')}'
    ORDER BY t.ProjectID, CAST(t.TimeDate AS DATE), t.EmpNumber
    """
    cursor.execute(sql)
    raw = pd.DataFrame(cursor.fetchall(), columns=[d[0] for d in cursor.description])
    return _shape_labor_data(raw)


def _spec_str(v):
    """SpecID is a float on the view (e.g. 10.0); render whole values as '10'."""
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return ""
    try:
        f = float(v)
        return str(int(f)) if f.is_integer() else str(f)
    except (TypeError, ValueError):
        return str(v)


def _shape_labor_data(raw):
    if raw.empty:
        return pd.DataFrame(columns=LABOR_DATA_COLUMNS)
    out = pd.DataFrame()
    spec = raw["SpecID"].map(_spec_str)
    out["Project"] = (raw["ProjectID"].astype(str) + " - "
                      + raw["ProjectName"].fillna("").astype(str)).str.strip(" -")
    out["Machine"] = (spec + " - "
                      + raw["MachineName"].fillna("").astype(str)).str.strip(" -")
    out["Hour Department"] = raw["HourDepartment"]
    out["Hour Description"] = raw["HourDescription"]
    name = (raw["EmpLastName"].fillna("").astype(str) + ", "
            + raw["EmpFirstName"].fillna("").astype(str)).str.strip(", ")
    out["Employee"] = raw["EmpNumber"].astype(str) + " - " + name
    out["Date"] = raw["WorkDate"]
    out["Actual Hours"] = raw["ActualHours"]
    out["Actual Cost"] = raw["ActualCost"]
    out["Project ID"] = raw["ProjectID"].astype(str)
    out["Machine Code"] = spec
    out["Asset Re-Code"] = (raw["HourDescription"].map(DISCIPLINE_MAP).fillna(UNMAPPED_DISCIPLINE))
    yr = raw["WorkDate"].map(lambda d: d.year if d is not None else None)
    wk = raw["WorkDate"].map(lambda d: excel_weeknum(d) if d is not None else None)
    out["Year"] = yr
    out["Week #"] = wk
    out["Year-Week"] = yr.astype("Int64").astype(str) + "-" + wk.astype("Int64").astype(str)
    return out[LABOR_DATA_COLUMNS]


def unmapped_hour_descriptions(cursor, start_date, end_date):
    sql = f"""
    SELECT DISTINCT t.HourDescription
    FROM dbo.vwTimecards t
    WHERE t.TimeDate >= '{start_date.strftime('%Y-%m-%d')}'
      AND t.TimeDate <= '{end_date.strftime('%Y-%m-%d')}'
    """
    cursor.execute(sql)
    found = [r[0] for r in cursor.fetchall()]
    return sorted(x for x in found if x and x not in DISCIPLINE_MAP)
