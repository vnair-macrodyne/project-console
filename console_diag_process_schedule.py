"""
console_diag_process_schedule.py — is ETO's process schedule the "activity"? (read-only)

Follow-up to console_diag_plan_activity.py. The process-schedule module exists
(tblProcessScheduleHeader → tblProcessScheduleDetail, operations with estimate/total hours,
quantities, a process-type lookup and a completed-log). It's the "units of work with
duration" candidate for the plan's activity. This probe answers: is it POPULATED for live
projects, what does a task row look like, does it carry sequence/dependency, and how is
progress tracked (completed-log / quantities / status)? Pure SELECT.

Detail has no ProjectID — it keys through the header (→ spec → project). We dump the real
columns first, then scope via the header. Run:
    python console_diag_process_schedule.py [projid ...]
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


def show(cur, label, sql, cap=40):
    print("\n" + "-" * 78 + f"\n{label}\n" + "-" * 78)
    try:
        cur.execute(sql)
        cols = [d[0] for d in cur.description]
        rows = cur.fetchall()
        print("  " + " | ".join(cols))
        for r in rows[:cap]:
            print("  " + " | ".join("" if v is None else str(v)[:40] for v in r))
        if len(rows) > cap:
            print(f"  ... (+{len(rows) - cap} more rows)")
        if not rows:
            print("  (0 rows)")
    except Exception as e:
        print(f"  [ERROR] {type(e).__name__}: {e}")


def cols_of(cur, table):
    show(cur, f"columns of {table}",
         "SELECT COLUMN_NAME, DATA_TYPE, IS_NULLABLE FROM INFORMATION_SCHEMA.COLUMNS "
         f"WHERE TABLE_NAME = '{table}' ORDER BY ORDINAL_POSITION", cap=80)


def main():
    pids = [int(a) for a in sys.argv[1:] if a.strip().isdigit()] or DEFAULT_PROJECTS
    ids = ",".join(str(p) for p in pids)
    conn = connect()
    cur = conn.cursor()
    try:
        # 1. Real schema of header + detail (look here for SpecID/ProjectID, Sequence, Predecessor).
        cols_of(cur, "tblProcessScheduleHeader")
        cols_of(cur, "tblProcessScheduleDetail")

        # 2. The process-type catalogue (the "activity type" list a step is an instance of).
        show(cur, "2. tlkpProcess — process/operation types", "SELECT * FROM dbo.tlkpProcess")

        # 3. Population per project — headers (scoped via the header's own Project/Spec keys).
        show(cur, f"3. Process-schedule HEADERS per project {ids} (is it maintained?)",
             "SELECT h.ProjectID, COUNT(*) AS Headers, COUNT(DISTINCT h.SpecID) AS Specs "
             f"FROM dbo.tblProcessScheduleHeader h WHERE h.ProjectID IN ({ids}) "
             "GROUP BY h.ProjectID ORDER BY h.ProjectID")

        # 4. Detail (operations) per project — the count of task-rows a plan would use.
        show(cur, "4. Process-schedule DETAIL rows per project (the operations / units of work)",
             "SELECT h.ProjectID, COUNT(*) AS Operations, "
             "CAST(SUM(d.TotalHours) AS decimal(18,1)) AS TotalHours, "
             "CAST(SUM(d.EstimateHours) AS decimal(18,1)) AS EstimateHours "
             "FROM dbo.tblProcessScheduleDetail d "
             "JOIN dbo.tblProcessScheduleHeader h ON h.ProcessScheduleHeaderID = d.ProcessScheduleHeaderID "
             f"WHERE h.ProjectID IN ({ids}) GROUP BY h.ProjectID ORDER BY h.ProjectID")

        # 5. What a task row looks like — sample operations for the first project.
        show(cur, f"5. Sample operations for project {pids[0]} (spec, process, hours, qty, status)",
             "SELECT TOP 25 h.ProjectID, h.SpecID, pr.Process AS ProcessName, "
             "d.EstimateHours, d.SetupHours, d.TotalHours, d.QuantityOrdered, d.QuantityReceived "
             "FROM dbo.tblProcessScheduleDetail d "
             "JOIN dbo.tblProcessScheduleHeader h ON h.ProcessScheduleHeaderID = d.ProcessScheduleHeaderID "
             "LEFT JOIN dbo.tlkpProcess pr ON pr.ProcessID = d.ProcessID "
             f"WHERE h.ProjectID = {pids[0]} ORDER BY h.SpecID")

        # 6. Progress tracking — is the completed-log used? (labour link was empty)
        cols_of(cur, "tblPSCompletedLog")
        show(cur, "6. Completed-log rows for the sample projects (is step completion recorded?)",
             "SELECT COUNT(*) AS CompletedLogRows FROM dbo.tblPSCompletedLog cl "
             "JOIN dbo.tblProcessScheduleDetail d ON d.ProcessScheduleDetailID = cl.ProcessScheduleDetailID "
             "JOIN dbo.tblProcessScheduleHeader h ON h.ProcessScheduleHeaderID = d.ProcessScheduleHeaderID "
             f"WHERE h.ProjectID IN ({ids})")
    finally:
        conn.close()
    print("\nDone. Paste the output back — populated + progress-trackable ⇒ the activity is a "
          "process-schedule operation (granular, matches the plan vision); sparse ⇒ use spec.")


if __name__ == "__main__":
    main()
