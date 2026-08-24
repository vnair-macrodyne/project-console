"""
console_diag_jobdetail_discrepancy.py — why does a job-detail total differ between the
Employee Job Detail (lab_d) and Job Detail Summary (lab_dsum) reports? (2026-08-18)

A PM saw "M00 - General Concept" total more in Employee Job Detail than in the (machine-split)
Job Detail Summary. Both reports foot to the same grand total, so this is a GROUPING question:
  (a) machine split      — lab_dsum splits by SpecID (machine); lab_d does not. The same job detail
                           spreads across machine bands.
  (b) job-detail variants — free-text TimecardCustom1: trailing spaces / en-dash vs hyphen / double
                           spaces make "the same" detail group into separate rows.
  (c) category/discipline — the labour category (HourDescription) drives the discipline; if M00 rows
                           carry more than one category, they land under different disciplines.

This probe dumps the raw timecard rows for one project + job-detail search, then aggregates the same
data three ways so the cause is obvious. READ-ONLY.

Run:  python console_diag_jobdetail_discrepancy.py [projectID] [search]
      e.g.  python console_diag_jobdetail_discrepancy.py 250005 "General Concept"
Defaults: 250005 / "General Concept".  Paste the whole output.
"""
import sys


def eto_connect():
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


def rule(t):
    print("\n" + "=" * 78 + f"\n{t}\n" + "=" * 78)


def run(cur, label, sql, params=(), max_rows=60):
    print("\n" + "-" * 78 + f"\n{label}\n" + "-" * 78)
    try:
        cur.execute(sql, params)
        while cur.description is None and cur.nextset():
            pass
        if cur.description is None:
            print("  (no result set)")
            return
        cols = [d[0] for d in cur.description]
        rows = cur.fetchall()
        print("  " + " | ".join(cols))
        for r in rows[:max_rows]:
            print("  " + " | ".join("" if v is None else str(v) for v in r))
        if len(rows) > max_rows:
            print(f"  ... (+{len(rows) - max_rows} more)")
        if not rows:
            print("  (0 rows)")
    except Exception as e:
        print(f"  [ERROR] {type(e).__name__}: {e}")


def main():
    pid = 250005
    term = "General Concept"
    if len(sys.argv) > 1:
        try:
            pid = int(sys.argv[1])
        except ValueError:
            pass
    if len(sys.argv) > 2:
        term = sys.argv[2]
    like = f"%{term}%"
    conn = eto_connect()
    cur = conn.cursor()
    print(f"Project {pid}  ·  job-detail search: '{term}'")

    base_from = (
        "FROM tblTimecards tc "
        "JOIN tblProjects p ON p.ProjectID = tc.ProjectID "
        "LEFT JOIN tlkpHourTypes ht ON ht.HourType = tc.HourType "
        "LEFT JOIN tblEmployee e ON e.EmployeeID = tc.EmployeeID "
        "WHERE tc.ProjectID = ? AND tc.TimecardCustom1 LIKE ?"
    )
    try:
        # ── A. raw rows — machine (SpecID), category, employee, EXACT job detail + length ────
        rule("A. RAW timecard rows (machine=SpecID, category=HourDescription, exact job detail)")
        run(cur, "A1.",
            "SELECT tc.SpecID AS Machine, ht.HourDescription AS Category, "
            "  tc.EmpNumber AS Emp, "
            "  '[' + ISNULL(tc.TimecardCustom1,'') + ']' AS JobDetail_bracketed, "
            "  LEN(ISNULL(tc.TimecardCustom1,'')) AS JD_Len, "
            "  CAST(tc.HourTime AS decimal(9,2)) AS Hours "
            f"{base_from} ORDER BY JobDetail_bracketed, tc.SpecID, tc.EmpNumber",
            (pid, like), max_rows=80)

        # ── B. group by EXACT job-detail string — reveals whitespace / dash variants ─────────
        rule("B. by EXACT job-detail string (variants show as separate rows → the (b) cause)")
        run(cur, "B1.  bracketed so trailing/leading spaces are visible",
            "SELECT '[' + ISNULL(tc.TimecardCustom1,'') + ']' AS JobDetail_bracketed, "
            "  LEN(ISNULL(tc.TimecardCustom1,'')) AS JD_Len, COUNT(*) AS Entries, "
            "  CAST(SUM(tc.HourTime) AS decimal(10,2)) AS Hours "
            f"{base_from} GROUP BY tc.TimecardCustom1 "
            "ORDER BY JobDetail_bracketed", (pid, like))

        # ── C. group by MACHINE × job detail — what lab_dsum does (the (a) cause) ────────────
        rule("C. by MACHINE (SpecID) × job detail — mirrors the Job Detail Summary split")
        run(cur, "C1.",
            "SELECT tc.SpecID AS Machine, "
            "  '[' + ISNULL(tc.TimecardCustom1,'') + ']' AS JobDetail_bracketed, "
            "  COUNT(*) AS Entries, CAST(SUM(tc.HourTime) AS decimal(10,2)) AS Hours "
            f"{base_from} GROUP BY tc.SpecID, tc.TimecardCustom1 "
            "ORDER BY tc.SpecID, JobDetail_bracketed", (pid, like))

        # ── D. group by CATEGORY (drives discipline) × job detail ────────────────────────────
        rule("D. by CATEGORY (HourDescription → discipline) × job detail")
        run(cur, "D1.",
            "SELECT ht.HourDescription AS Category, "
            "  '[' + ISNULL(tc.TimecardCustom1,'') + ']' AS JobDetail_bracketed, "
            "  COUNT(*) AS Entries, CAST(SUM(tc.HourTime) AS decimal(10,2)) AS Hours "
            f"{base_from} GROUP BY ht.HourDescription, tc.TimecardCustom1 "
            "ORDER BY ht.HourDescription, JobDetail_bracketed", (pid, like))

        # ── E. grand total for the search (single source of truth) ───────────────────────────
        rule("E. GRAND TOTAL for the search (what all three groupings must add up to)")
        run(cur, "E1.",
            "SELECT COUNT(*) AS Entries, CAST(SUM(tc.HourTime) AS decimal(10,2)) AS Hours, "
            "  COUNT(DISTINCT tc.SpecID) AS Machines, "
            "  COUNT(DISTINCT tc.TimecardCustom1) AS DistinctJobDetailStrings "
            f"{base_from}", (pid, like))
    finally:
        conn.close()
    print("\nDone. Paste the whole output. Reading it:\n"
          "  • E = the real total for these job details.\n"
          "  • C splits it by machine (that's what the Summary does). If the M00 total is spread\n"
          "    across several SpecIDs, the 1.25 the PM saw was just ONE machine's slice → working\n"
          "    as designed, reconciles when you add the machine bands.\n"
          "  • B shows the EXACT strings bracketed. If '[M00 - General Concept]' and\n"
          "    '[M00 - General Concept ]' (trailing space) or an en-dash both appear, the same task\n"
          "    is splitting into separate rows → we normalise the job-detail text before grouping.\n"
          "  • D shows whether M00 carries more than one category (→ different disciplines).\n"
          "  Between B/C/D the cause is unambiguous, and I'll fix or explain accordingly.")


if __name__ == "__main__":
    main()
