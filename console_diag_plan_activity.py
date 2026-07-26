"""
console_diag_plan_activity.py — what should an "activity" map to in ETO? (read-only)

Settles open question B3: is the plan's unit-of-work a SPEC (tblSpec), an Hour Description
(labour category), or an ETO process-schedule task? For a few live projects this prints:
  1. the SPEC list a PM would pick from (ProjectID, SpecID, name);
  2. actuals that attach per spec — timecard hours and PO lines/value — i.e. whether
     objective % (actual ÷ allocated) is computable at spec grain;
  3. whether an ETO process-schedule exists and how populated it is (the task-like option).

Pure SELECT; nothing written. Run on the box:
    python console_diag_plan_activity.py                 (sample projects)
    python console_diag_plan_activity.py 230219 240033
Paste the output back.
"""
import sys

DEFAULT_PROJECTS = [230219, 230312, 240087]


def connect():
    try:
        from console_store import eto_connection
        return eto_connection()
    except Exception:
        import os
        import pyodbc
        from console_config import TENANT
        cs = (f"Driver={{ODBC Driver 17 for SQL Server}};Server={TENANT.eto_server};"
              f"Database={TENANT.eto_database};")
        cs += ("Trusted_Connection=yes;" if TENANT.use_windows_auth
               else f"UID={os.environ.get('ETO_USER')};PWD={os.environ.get('ETO_PWD')};")
        return pyodbc.connect(cs)


def show(cur, label, sql, params=(), cap=60):
    print("\n" + "-" * 78 + f"\n{label}\n" + "-" * 78)
    try:
        cur.execute(sql, params)
        if cur.description is None:
            print("  (no result set)")
            return
        cols = [d[0] for d in cur.description]
        rows = cur.fetchall()
        print("  " + " | ".join(cols))
        for r in rows[:cap]:
            print("  " + " | ".join("" if v is None else str(v) for v in r))
        if len(rows) > cap:
            print(f"  ... (+{len(rows) - cap} more rows)")
        if not rows:
            print("  (0 rows)")
    except Exception as e:
        print(f"  [ERROR] {type(e).__name__}: {e}")


def main():
    pids = [int(a) for a in sys.argv[1:] if a.strip().isdigit()] or DEFAULT_PROJECTS
    ids = ",".join(str(p) for p in pids)
    conn = connect()
    cur = conn.cursor()
    try:
        # 1. The spec list — the per-project pick-list for "activity = spec".
        show(cur, f"1. Specs (units of work) for projects {ids}",
             "SELECT ProjectID, SpecID, SDescription FROM dbo.tblSpec "
             f"WHERE ProjectID IN ({ids}) ORDER BY ProjectID, SpecID")

        # 2a. Labour hours booked per spec (objective % numerator, labour).
        show(cur, "2a. Timecard hours per spec (can we measure labour progress per spec?)",
             "SELECT ProjectID, SpecID, COUNT(*) AS Entries, SUM(HourTime) AS Hours "
             f"FROM dbo.vwTimecards WHERE ProjectID IN ({ids}) "
             "GROUP BY ProjectID, SpecID ORDER BY ProjectID, SpecID")

        # 2b. PO lines/value per spec (objective material per spec).
        show(cur, "2b. PO lines + value per spec (material attaches per spec?)",
             "SELECT ProjectID, SpecID, COUNT(*) AS Lines, "
             "CAST(SUM(ExtendedPrice) AS decimal(20,2)) AS ExtValue "
             f"FROM dbo.vwPurchaseOrderDetails WHERE ProjectID IN ({ids}) "
             "GROUP BY ProjectID, SpecID ORDER BY ProjectID, SpecID")

        # 3. Is there an ETO process schedule (the task-like activity option)? How populated?
        show(cur, "3a. Objects mentioning ProcessSchedule",
             "SELECT name, type_desc FROM sys.objects WHERE name LIKE '%ProcessSchedule%' "
             "ORDER BY type_desc, name")
        show(cur, "3b. Process-schedule detail — row count + projects covered (if the table exists)",
             "SELECT COUNT(*) AS Rows, COUNT(DISTINCT ProjectID) AS Projects "
             "FROM dbo.tblProcessScheduleDetail")
        show(cur, "3c. Punch-ins carrying a ProcessScheduleDetailID (is the schedule link used?)",
             "SELECT COUNT(*) AS PunchIns, COUNT(DISTINCT ProcessScheduleDetailID) AS DistinctTasks "
             "FROM dbo.tblTimecardPunchIns WHERE ProcessScheduleDetailID IS NOT NULL")
    finally:
        conn.close()
    print("\nDone. Paste the output back — this settles whether the activity is a spec "
          "(objective % from spec actuals) or the process-schedule task.")


if __name__ == "__main__":
    main()
