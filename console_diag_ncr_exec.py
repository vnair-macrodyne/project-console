"""
console_diag_ncr_exec.py — can the reporting account EXEC ETO's NC costing procs? (2026-07-26)

Probe 2 showed the NC costing procs exist and are project/date-scoped, but their
DEFINITIONS are not visible to TotalETOReportWriter (no VIEW DEFINITION grant), and
BOTH timecard NC links are 0-populated (no rework labour is booked to NCs here).

This probe answers the last open question before we design views: can the read-only
account EXECUTE these report procs, and what COST columns do they return? That decides
whether we drive NC costs by EXEC (like the urpPurchasingLateVendors fallback) or need a
VIEW DEFINITION grant to transcribe them.

These are ETO 'urp' USER-REPORT procs (SELECT-only by design — same family as
urpPurchasingLateVendors, which we already EXEC safely). Nothing is written.

Run on the box:  python console_diag_ncr_exec.py
Paste the WHOLE output back.
"""

TEST_PROJECT = 230219
WIDE_LOWER = "2019-01-01"
WIDE_UPPER = "2027-01-01"


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


def rule(t):
    print("\n" + "=" * 78 + f"\n{t}\n" + "=" * 78)


def run(cur, label, sql, max_rows=12):
    """EXEC/SELECT and print the first result set's columns + a few rows. Tolerant."""
    print("\n" + "-" * 78 + f"\n{label}\n" + "-" * 78)
    print(f"  SQL: {sql}")
    try:
        cur.execute(sql)
        # skip past empty result sets some procs emit before the data set
        while cur.description is None and cur.nextset():
            pass
        if cur.description is None:
            print("  (proc executed OK but returned no result set)")
            return
        cols = [d[0] for d in cur.description]
        rows = cur.fetchall()
        print(f"  RETURNED {len(cols)} columns: {', '.join(cols)}")
        for r in rows[:max_rows]:
            print("  " + " | ".join("" if v is None else str(v) for v in r))
        if len(rows) > max_rows:
            print(f"  ... (+{len(rows) - max_rows} more rows)")
        if not rows:
            print("  (0 rows for this scope)")
    except Exception as e:
        print(f"  [ERROR] {type(e).__name__}: {e}")


def find_sample_nc(cur):
    """An NC on the test project that HAS a remedy PO line (so costs should be non-zero)."""
    for sql in (
        "SELECT TOP 1 NonConformanceID FROM dbo.tblPurchaseOrderDetails "
        f"WHERE NonConformanceID IS NOT NULL AND ProjectID = {TEST_PROJECT} "
        "ORDER BY NonConformanceID DESC",
        # fallback: any NC on the project
        "SELECT TOP 1 NonConformanceID FROM dbo.tblNonConformance "
        f"WHERE ProjectID = {TEST_PROJECT} ORDER BY NonConformanceID DESC",
    ):
        try:
            cur.execute(sql)
            row = cur.fetchone()
            if row and row[0] is not None:
                return int(row[0])
        except Exception as e:
            print(f"  [sample-NC lookup error] {e}")
    return None


def main():
    conn = connect()
    cur = conn.cursor()
    try:
        # 1. The headline report proc — project-scoped. Two attempts (project-only, then
        #    project + wide date window) in case a NULL date param isn't treated as "all".
        rule("1. EXEC urpNonConformancesWithCosts — scoped to the test project")
        run(cur, "1a. project only",
            f"EXEC dbo.urpNonConformancesWithCosts @intProjectID = {TEST_PROJECT}")
        run(cur, "1b. project + wide created-date window",
            "EXEC dbo.urpNonConformancesWithCosts "
            f"@intProjectID = {TEST_PROJECT}, "
            f"@datCreatedLower = '{WIDE_LOWER}', @datCreatedUpper = '{WIDE_UPPER}'")

        # 2. Plain list proc (no costs) — is it a cheaper list source than the view?
        rule("2. EXEC urpNonConformances — project-scoped list (no costs)")
        run(cur, "2a. project only",
            f"EXEC dbo.urpNonConformances @intProjectID = {TEST_PROJECT}")

        # 3. Costing comparison proc — project + date window.
        rule("3. EXEC urpNonConformanceCostingCompared — project + wide window")
        run(cur, "3a.",
            "EXEC dbo.urpNonConformanceCostingCompared "
            f"@intProjectID = {TEST_PROJECT}, "
            f"@datCreatedLower = '{WIDE_LOWER}', @datCreatedUpper = '{WIDE_UPPER}'")

        # 4. Per-NC cost breakdown — pick a real NC that has a remedy PO on the project.
        rule("4. Per-NC cost procs — labour / material+inventory / payables")
        nc = find_sample_nc(cur)
        print(f"  sample NonConformanceID on project {TEST_PROJECT}: {nc}")
        if nc is not None:
            run(cur, "4a. urpCosting_LabourByNC (expected ~empty — no time booked to NCs)",
                f"EXEC dbo.urpCosting_LabourByNC @intNonConformanceID = {nc}")
            run(cur, "4b. urpCosting_MaterialsInventoryByNC (expected populated)",
                f"EXEC dbo.urpCosting_MaterialsInventoryByNC @intNonConformanceID = {nc}")
            run(cur, "4c. urpCosting_PayablesByNC",
                f"EXEC dbo.urpCosting_PayablesByNC @intNonConformanceID = {nc}")
            run(cur, "4d. urpNonConformanceAssignmentRetrieveByNC (corrective actions)",
                f"EXEC dbo.urpNonConformanceAssignmentRetrieveByNC @intNonConformanceID = {nc}")

    finally:
        conn.close()
    print("\nDone. Paste the whole output back — this settles EXEC rights + the cost-column "
          "shape, the last thing needed before designing the NC views.")


if __name__ == "__main__":
    main()
