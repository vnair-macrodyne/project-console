"""
console_diag_jobdetail.py — find the ETO "Job Detail" field (read-only).

The Labour reports carry a "Job Detail" column (per eto_config COLS_*). In the naive
eto-reporting query it was tblHours.JobDetailNameLevel2. On vwTimecards we inferred it
= ProcessSummary, but that comes back blank — so it's the wrong column. This probe finds
the column that actually holds job-detail text so we map it correctly (no more guessing).

Run on the box:  python console_diag_jobdetail.py --project 230219
(use a project you KNOW has job-detail values in ETO). Paste the whole output back.
"""
import argparse

# vwTimecards columns worth checking for job-detail-like content
CANDIDATES = ["ProcessSummary", "HourDrawing", "Comments", "SComments", "SDescription",
              "MachineInternal", "MachineTypeName", "ProcessScheduleDetailID",
              "HourDescription", "SubDeptName"]


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


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--project", required=True, help="a ProjectID that has job-detail data in ETO")
    args = ap.parse_args()
    pid = int(args.project.split(",")[0])
    conn = connect()
    cur = conn.cursor()

    # 1. Where does a 'JobDetail'-named column live at all (any table/view)?
    print("=" * 74)
    print("1. Columns named like '%JobDetail%' anywhere in the database:")
    cur.execute("""SELECT TABLE_NAME, COLUMN_NAME FROM INFORMATION_SCHEMA.COLUMNS
                   WHERE COLUMN_NAME LIKE '%JobDetail%' OR COLUMN_NAME LIKE '%Job_Detail%'
                   ORDER BY TABLE_NAME, COLUMN_NAME""")
    hits = cur.fetchall()
    for t, c in hits:
        print(f"   {t}.{c}")
    if not hits:
        print("   (none — 'Job Detail' isn't a JobDetail-named column)")

    # 2. vwTimecards columns whose NAME hints at job/detail/level/process/task/operation
    print("\n" + "=" * 74)
    print("2. Name-hinted columns on vwTimecards:")
    cur.execute("""SELECT COLUMN_NAME, DATA_TYPE FROM INFORMATION_SCHEMA.COLUMNS
                   WHERE TABLE_NAME='vwTimecards' AND (
                     COLUMN_NAME LIKE '%job%' OR COLUMN_NAME LIKE '%detail%' OR
                     COLUMN_NAME LIKE '%level%' OR COLUMN_NAME LIKE '%process%' OR
                     COLUMN_NAME LIKE '%task%' OR COLUMN_NAME LIKE '%operation%' OR
                     COLUMN_NAME LIKE '%oper%' OR COLUMN_NAME LIKE '%drawing%')
                   ORDER BY COLUMN_NAME""")
    rows = cur.fetchall()
    for n, t in rows:
        print(f"   {n} ({t})")
    if not rows:
        print("   (no obvious name matches)")

    # 3. For the project, how populated is each candidate + sample distinct values
    print("\n" + "=" * 74)
    print(f"3. Project {pid}: non-blank count and sample values per candidate column")
    print("   (the column that carries the job-detail text is the one to map)\n")
    for col in CANDIDATES:
        try:
            cur.execute(f"SELECT COUNT(*), "
                        f"COUNT(NULLIF(LTRIM(RTRIM(CAST([{col}] AS nvarchar(400)))),'')) "
                        f"FROM dbo.vwTimecards WHERE ProjectID = ?", pid)
            total, nonblank = cur.fetchone()
            cur.execute(f"SELECT DISTINCT TOP 6 CAST([{col}] AS nvarchar(90)) "
                        f"FROM dbo.vwTimecards WHERE ProjectID = ? "
                        f"AND LTRIM(RTRIM(CAST([{col}] AS nvarchar(400)))) <> ''", pid)
            samples = [r[0] for r in cur.fetchall()]
            print(f"   {col:24} non-blank {nonblank}/{total}   e.g. {samples}")
        except Exception as ex:
            print(f"   {col:24} !! {ex}")

    conn.close()
    print("\nDone. Paste the whole output back.")


if __name__ == "__main__":
    main()
