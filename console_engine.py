"""
console_engine.py — Project Console LAYER 1 (automate the actuals).
(Verbatim project module + 2026-07-24 addition: query_two_week_labour_hours, a
lean cursor-based 2-week labour aggregate for the Executive Dashboard, kept here
in the query module per suite convention.)
"""
import datetime as _dt
import pandas as pd

from console_feed import DISCIPLINE_MAP, DISCIPLINES, UNMAPPED_DISCIPLINE


def _id_list(project_ids):
    return "(" + ",".join(str(int(p)) for p in project_ids) + ")"


def _run(cursor, sql):
    cursor.execute(sql)
    return pd.DataFrame.from_records(cursor.fetchall(),
                                     columns=[d[0] for d in cursor.description])


def _pct(actual, estimate):
    try:
        actual = float(actual); estimate = float(estimate)
    except (TypeError, ValueError):
        return None
    return (actual / estimate) if estimate else None


def q_estimate_vs_actual(project_ids):
    return f"""
    SELECT ProjectID, PDescription,
           EstAdminHours, EstEngHours, EstMfgHours,
           ActAdminHours, ActEngHours, ActMfgHours,
           EstTotalMaterials, ActTotalMaterials,
           ExtendedEstimate, ActTotalCost, SalesPrice,
           BudgetMargin, ActualMargin
    FROM dbo.vwProjectActualsVSEstimates
    WHERE ProjectID IN {_id_list(project_ids)}
    """


def q_totals(project_ids):
    return f"""
    SELECT ProjectID, TotalBudget, ActTotalCost,
           TotalBudgetLabor, TotalActualLabor,
           EstTotalMaterials, ActTotalMaterials
    FROM dbo.vwProjectActualsVSEstimates_LaborAndMaterials
    WHERE ProjectID IN {_id_list(project_ids)}
    """


def q_labour_by_hourtype(project_ids):
    return f"""
    SELECT h.ProjectID,
           h.HourType,
           ht.HourDescription,
           h.TotalBudgetLabor AS EstLabor,
           h.TotalActualLabor AS ActLabor
    FROM dbo.vwProjectLaborActualsVSEstimatesByHourType h
    LEFT JOIN dbo.tlkpHourTypes ht ON ht.HourType = h.HourType
    WHERE h.ProjectID IN {_id_list(project_ids)}
    """


def q_material_by_category(project_ids):
    return f"""
    SELECT ProjectID, Category, TotalMaterialEstimate, TotalMaterialActual
    FROM dbo.vwProjectMaterialActualVsEstimatesByItemCategory
    WHERE ProjectID IN {_id_list(project_ids)}
    """


def q_actual_hours_by_hourtype(project_ids):
    """
    Actual labour HOURS per project per HourDescription, straight from timecards.
    HourDescription re-codes to the 6 Project Console disciplines (same crosswalk as the
    Labor Data feed), giving fully-automated actual hours at discipline grain — the
    NUMERATOR of the hours-based discipline block. (Budget hours per discipline are
    a manual PM input on the Budgets tab — not in ETO at 6-discipline grain.)
    """
    return f"""
    SELECT t.ProjectID AS ProjectID,
           t.HourDescription AS HourDescription,
           SUM(t.HourTime) AS ActHours
    FROM dbo.vwTimecards t
    WHERE t.ProjectID IN {_id_list(project_ids)}
    GROUP BY t.ProjectID, t.HourDescription
    """


def build_discipline_hours(actual_by_hd, crosswalk=None):
    """Project × discipline: ACTUAL labour hours (from timecards).
    `crosswalk` (HourDescription→discipline) comes from the Console store
    (console_store.load_crosswalk) so budget and actual share one source of truth;
    falls back to the in-code DISCIPLINE_MAP when not supplied."""
    xwalk = crosswalk or DISCIPLINE_MAP
    df = actual_by_hd.copy()
    df["Discipline"] = (df["HourDescription"].map(xwalk).fillna(UNMAPPED_DISCIPLINE))
    g = (df.groupby(["ProjectID", "Discipline"], dropna=False)["ActHours"]
           .sum().reset_index())
    order = {d: i for i, d in enumerate(DISCIPLINES)}
    g["_o"] = g["Discipline"].map(order).fillna(99)
    return g.sort_values(["ProjectID", "_o"]).drop(columns="_o").reset_index(drop=True)


def q_two_week_labour(project_ids, start, end):
    """
    Lean labour-hours aggregate for the dashboard's '2-Week Delta / Labour Hrs' cell.
    Aggregates in SQL over vwTimecards; touches only ProjectID, HourTime, TimeDate
    (the same columns the production labour queries rely on) — no employee/spec joins,
    so it can't trip the Labor-Data-feed TODO(verify) columns.
    """
    return f"""
    SELECT t.ProjectID AS ProjectID, SUM(t.HourTime) AS Hours
    FROM dbo.vwTimecards t
    WHERE t.ProjectID IN {_id_list(project_ids)}
      AND t.TimeDate >= '{start.strftime('%Y-%m-%d')}'
      AND t.TimeDate <= '{end.strftime('%Y-%m-%d')}'
    GROUP BY t.ProjectID
    """


def query_two_week_labour_hours(cursor, project_ids, as_of=None, days=14):
    """Return {ProjectID(str): trailing-`days` labour hours} for the given projects."""
    as_of = as_of or _dt.date.today()
    start = as_of - _dt.timedelta(days=days - 1)
    df = _run(cursor, q_two_week_labour(project_ids, start, as_of))
    return {str(int(r.ProjectID)): round(float(r.Hours or 0), 1)
            for _, r in df.iterrows()}


def build_project_summary(estvsact, totals):
    ev = estvsact.set_index("ProjectID")
    tt = totals.set_index("ProjectID")
    rows = []
    for pid in ev.index:
        e = ev.loc[pid]
        t = tt.loc[pid] if pid in tt.index else None
        lab_est_hrs = float(e.EstAdminHours or 0) + float(e.EstEngHours or 0) + float(e.EstMfgHours or 0)
        lab_act_hrs = float(e.ActAdminHours or 0) + float(e.ActEngHours or 0) + float(e.ActMfgHours or 0)
        lab_est_cost = float(t.TotalBudgetLabor) if t is not None else None
        lab_act_cost = float(t.TotalActualLabor) if t is not None else None
        mat_est = float(e.EstTotalMaterials or 0)
        mat_act = float(e.ActTotalMaterials or 0)
        rows.append({
            "ProjectID": pid, "Project": e.PDescription,
            # ETO 3-bucket estimate hours — used to SEED the Budgets input form
            # (Admin→PM, Mfg→Manufacturing pre-filled; Eng is the bucket the PM splits).
            "EstAdminHours": float(e.EstAdminHours or 0),
            "EstEngHours": float(e.EstEngHours or 0),
            "EstMfgHours": float(e.EstMfgHours or 0),
            "LabEstHrs": round(lab_est_hrs, 2), "LabActHrs": round(lab_act_hrs, 2),
            "LabPctHrs": _pct(lab_act_hrs, lab_est_hrs),
            "LabEstCost": lab_est_cost, "LabActCost": lab_act_cost,
            "LabPctCost": _pct(lab_act_cost, lab_est_cost),
            "MatEst": round(mat_est, 2), "MatAct": round(mat_act, 2),
            "MatPct": _pct(mat_act, mat_est),
            "TotalBudget": float(e.ExtendedEstimate or 0),
            "ActTotalCost": float(e.ActTotalCost or 0),
            "TotalPct": _pct(e.ActTotalCost, e.ExtendedEstimate),
            "SalesPrice": float(e.SalesPrice or 0),
            "BudgetMargin": float(e.BudgetMargin) if e.BudgetMargin is not None else None,
            "ActualMargin": float(e.ActualMargin) if e.ActualMargin is not None else None,
        })
    return pd.DataFrame(rows)


def build_discipline_labour(labour_by_hourtype):
    df = labour_by_hourtype.copy()
    df["Discipline"] = (df["HourDescription"].map(DISCIPLINE_MAP).fillna(UNMAPPED_DISCIPLINE))
    g = (df.groupby(["ProjectID", "Discipline"], dropna=False)[["EstLabor", "ActLabor"]]
           .sum().reset_index())
    g["PctConsumed"] = g.apply(lambda r: _pct(r.ActLabor, r.EstLabor), axis=1)
    order = {d: i for i, d in enumerate(DISCIPLINES)}
    g["_o"] = g["Discipline"].map(order).fillna(99)
    return g.sort_values(["ProjectID", "_o"]).drop(columns="_o").reset_index(drop=True)


def project_scorecard(cursor, project_ids, crosswalk=None):
    """Returns (summary_df, discipline_hours_df).
    discipline_hours_df = ACTUAL labour hours per project × discipline (ETO).
    `crosswalk` (from the Console store) is applied to the ETO actuals so budget and
    actual share one source of truth; falls back to the in-code map. Budget hours per
    discipline come from the manual overlay, merged in the dashboard layer.
    """
    estvsact = _run(cursor, q_estimate_vs_actual(project_ids))
    totals   = _run(cursor, q_totals(project_ids))
    act_hrs  = _run(cursor, q_actual_hours_by_hourtype(project_ids))
    summary  = build_project_summary(estvsact, totals)
    disc     = build_discipline_hours(act_hrs, crosswalk=crosswalk)
    return summary, disc


VALIDATION_PROJECTS = [230219, 240033, 220154, 240148, 240040,
                       250250, 240218, 250217, 240154, 240088]


def _connect():
    try:
        from eto_reports import get_db_connection
        return get_db_connection()
    except Exception:
        import eto_config as C, pyodbc
        if getattr(C, "USE_WINDOWS_AUTH", False):
            cs = (f"Driver={{ODBC Driver 17 for SQL Server}};Server={C.DB_SERVER};"
                  f"Database={C.DB_NAME};Trusted_Connection=yes;")
        else:
            cs = (f"Driver={{ODBC Driver 17 for SQL Server}};Server={C.DB_SERVER};"
                  f"Database={C.DB_NAME};UID={C.DB_USER};PWD={C.DB_PASSWORD};")
        return pyodbc.connect(cs)


if __name__ == "__main__":
    conn = _connect()
    try:
        summary, disc = project_scorecard(conn.cursor(), VALIDATION_PROJECTS)
    finally:
        conn.close()
    pd.set_option("display.width", 200, "display.max_columns", 30)
    print("\n=== PROJECT SUMMARY ===")
    print(summary[["ProjectID", "Project", "LabPctHrs", "LabPctCost", "MatPct", "TotalPct"]].to_string(index=False))
