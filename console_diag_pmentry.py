"""
console_diag_pmentry.py — confirm the plan form's write target (read-only, Console store).

Closes assumptions A14 / A15 / A17 before the Project Plan form's first live save:
  * does Reporting.tblProjectPMEntry exist, and what are its real columns?
  * what does its YearWeekKey look like (so the web form's key — Excel WEEKNUM, year*100+week —
    lands on the SAME row the spreadsheet sync writes)?
  * what does the dashboard's manual overlay expose?

This talks to the CONSOLE store (Macrodyne_Reporting), not ETO. Pure SELECT.
Run on the box:  python console_diag_pmentry.py   ·   paste the output back.
"""


def connect_console():
    try:
        from console_store import console_connection
        return console_connection()
    except Exception:
        import pyodbc
        from console_config import TENANT
        return pyodbc.connect(TENANT.reporting_conn_str())


def show(cur, label, sql, params=()):
    print("\n" + "-" * 78 + f"\n{label}\n" + "-" * 78)
    try:
        cur.execute(sql, params)
        if cur.description is None:
            print("  (no result set)")
            return
        cols = [d[0] for d in cur.description]
        rows = cur.fetchall()
        print("  " + " | ".join(cols))
        for r in rows[:40]:
            print("  " + " | ".join("" if v is None else str(v) for v in r))
        if not rows:
            print("  (0 rows)")
    except Exception as e:
        print(f"  [ERROR] {type(e).__name__}: {e}")


def main():
    conn = connect_console()
    cur = conn.cursor()
    try:
        # A14 — does the table exist, and with which columns?
        show(cur, "1. tblProjectPMEntry columns (A14 — the plan form's write target)",
             "SELECT COLUMN_NAME, DATA_TYPE, IS_NULLABLE FROM INFORMATION_SCHEMA.COLUMNS "
             "WHERE TABLE_SCHEMA = 'Reporting' AND TABLE_NAME = 'tblProjectPMEntry' "
             "ORDER BY ORDINAL_POSITION")

        # A15/A17 — the key format the sync writes (compare to plan.week_key: year*100 + WEEKNUM)
        show(cur, "2. Latest PM-entry keys (A15/A17 — reconcile YearWeekKey / FiscalYear / WeekNo)",
             "SELECT TOP 12 ProjectID, FiscalYear, WeekNo, YearWeekKey, "
             "PercentComplete, PlannedShipDate, LabourRunout, MaterialRunout "
             "FROM Reporting.tblProjectPMEntry ORDER BY YearWeekKey DESC, ProjectID")

        # what the dashboard actually reads (manual overlay)
        show(cur, "3. vw_Console_ManualOverlay columns (what the dashboard reads for the manual side)",
             "SELECT COLUMN_NAME, DATA_TYPE FROM INFORMATION_SCHEMA.COLUMNS "
             "WHERE TABLE_SCHEMA = 'Reporting' AND TABLE_NAME = 'vw_Console_ManualOverlay' "
             "ORDER BY ORDINAL_POSITION")

        # sanity: how many PM-entry rows / projects / weeks are banked
        show(cur, "4. PM-entry coverage",
             "SELECT COUNT(*) AS Rows, COUNT(DISTINCT ProjectID) AS Projects, "
             "COUNT(DISTINCT YearWeekKey) AS Weeks, MIN(YearWeekKey) AS FirstWk, "
             "MAX(YearWeekKey) AS LastWk FROM Reporting.tblProjectPMEntry")
    finally:
        conn.close()
    print("\nDone. Paste the output back — confirms the table/columns exist and whether the "
          "web week key matches the sync's before the first live save.")


if __name__ == "__main__":
    main()
