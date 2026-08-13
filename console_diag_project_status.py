"""
console_diag_project_status.py — how ETO marks a project active vs closed (2026-08-12).

Console currently shows every project that has a budget row in vw_Console_BudgetCurrent, with NO
status/active filter — so finished projects still appear. This probe surfaces ETO's authoritative
close signals so we can define "closed" the way Macrodyne means it, then filter the board on it:
  A. the status vocabulary (tlkpProjectStatus) + how many projects sit in each PStatus
  B. PActive distribution
  C. for the projects CURRENTLY ON THE BOARD (vw_Console_BudgetCurrent), their PStatus + PActive +
     last-charge date — so we can see which shown projects are really closed/dormant

READ-ONLY. Run:  python console_diag_project_status.py   → paste the whole output.
"""


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


def console_connect():
    try:
        from console.infra.connections import console_connection
        return console_connection()
    except Exception:
        try:
            from console_store import console_connection
            return console_connection()
        except Exception:
            return None


def rule(t):
    print("\n" + "=" * 78 + f"\n{t}\n" + "=" * 78)


def run(cur, label, sql, params=(), max_rows=80):
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


def budgeted_ids():
    c = console_connect()
    if not c:
        return []
    try:
        cur = c.cursor()
        cur.execute("SELECT DISTINCT ProjectID FROM Reporting.vw_Console_BudgetCurrent")
        ids = [int(r[0]) for r in cur.fetchall()]
        c.close()
        return ids
    except Exception as e:
        print(f"  [note] budgeted ids failed ({type(e).__name__}: {e})")
        return []


def main():
    conn = eto_connect()
    cur = conn.cursor()
    ids = budgeted_ids()
    idl = ",".join(str(i) for i in ids) if ids else ""
    try:
        # ── A. the status vocabulary + population ────────────────────────────────
        rule("A. PROJECT STATUS VOCABULARY (tlkpProjectStatus) + how many projects per PStatus")
        run(cur, "A1. the status lookup (all possible statuses)",
            "SELECT * FROM dbo.tlkpProjectStatus ORDER BY 1")
        run(cur, "A2. project count by PStatus (whole ETO)",
            "SELECT PStatus, COUNT(*) AS projects, SUM(CAST(PActive AS int)) AS active_flag_1 "
            "FROM dbo.tblProjects GROUP BY PStatus ORDER BY projects DESC")

        # ── B. PActive distribution ──────────────────────────────────────────────
        rule("B. PActive DISTRIBUTION")
        run(cur, "B1. active-flag counts",
            "SELECT PActive, COUNT(*) AS projects FROM dbo.tblProjects GROUP BY PActive")
        run(cur, "B2. PStatus × PActive matrix",
            "SELECT PStatus, PActive, COUNT(*) AS projects FROM dbo.tblProjects "
            "GROUP BY PStatus, PActive ORDER BY PStatus, PActive")

        # ── C. the projects ON THE BOARD today — are any actually closed? ────────
        rule("C. PROJECTS CURRENTLY ON THE BOARD (vw_Console_BudgetCurrent) — status + last charge")
        if idl:
            run(cur, "C1. board projects with ETO status/active + most recent timecard",
                "SELECT p.ProjectID, p.PStatus, p.PActive, p.PDescription, "
                "       MAX(tc.DateWorked) AS LastCharge "
                "FROM dbo.tblProjects p "
                "LEFT JOIN dbo.vwTimecards tc ON tc.ProjectID = p.ProjectID "
                f"WHERE p.ProjectID IN ({idl}) "
                "GROUP BY p.ProjectID, p.PStatus, p.PActive, p.PDescription "
                "ORDER BY LastCharge", max_rows=200)
            run(cur, "C2. of the board set, how many are PActive=0 or non-'Sold'",
                "SELECT SUM(CASE WHEN PActive = 0 THEN 1 ELSE 0 END) AS inactive_flag, "
                "       SUM(CASE WHEN PStatus <> 'Sold' THEN 1 ELSE 0 END) AS not_sold, "
                "       COUNT(*) AS board_total "
                f"FROM dbo.tblProjects WHERE ProjectID IN ({idl})")
        else:
            print("  (couldn't read the board set from vw_Console_BudgetCurrent — check the store conn)")
    finally:
        conn.close()
    print("\nDone. Paste the whole output. Then we can define 'closed' precisely:\n"
          "  • A1 = the exact status words ETO uses (e.g. Sold / Closed / Complete / Cancelled).\n"
          "  • C1/C2 = whether closed/inactive projects are actually sitting on the board today.\n"
          "  • Likely filter: exclude PActive = 0 (or PStatus IN (<closed set>)) from the project\n"
          "    list + dashboard, with an optional 'show closed' toggle. Tell me which signal is\n"
          "    authoritative for Macrodyne and I'll wire it.")


if __name__ == "__main__":
    main()
