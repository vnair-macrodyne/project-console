"""
console_diag_ncr_costs.py — read-only probe of ETO's NATIVE NC costing layer (2026-07-26).

The first probe (console_diag_ncr.py) surfaced a native cost-of-non-conformance
subsystem in ETO — its own stored procs and the real rework-labour link:

  * urpNonConformancesWithCosts       - NCR list WITH costs (the headline report)
  * urpNonConformanceCostingCompared  - costing comparison
  * urpNonConformanceSupplierImpact   - supplier $ impact
  * urpCosting_LabourByNC             - labour cost attributed to an NC
  * urpCosting_MaterialsInventoryByNC - material/inventory cost by NC
  * urpCosting_PayablesByNC           - AP/payables by NC
  * FK_tblTimecardPunchIns_tblNonConformance - rework labour is on PUNCH-INS,
    NOT the summarised tblTimecards (that link came back 0-populated).

This probe reads each proc's PARAMETERS + DEFINITION so we can mirror ETO's own
cost math (same approach we took with urpPurchasingLateVendors), checks whether the
reporting account can even see/EXEC them, and measures the real rework-labour link on
tblTimecardPunchIns. Pure read: parameter metadata, object definitions, counts. No EXEC,
nothing written.

Run on the box:  python console_diag_ncr_costs.py
Paste the WHOLE output back.
"""


def connect():
    """Read-only ETO connection — identical idiom to the other diag probes."""
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


# The native NC costing/report procs found by console_diag_ncr.py block 1.
COST_PROCS = [
    "urpNonConformances",
    "urpNonConformancesWithCosts",
    "urpNonConformanceCostingCompared",
    "urpNonConformanceSupplierImpact",
    "urpNonConformanceAssignmentRetrieveByNC",
    "urpCosting_LabourByNC",
    "urpCosting_MaterialsInventoryByNC",
    "urpCosting_PayablesByNC",
]

# Additional NC views to inventory (surfaced by the first probe).
NC_VIEWS = ["vwNonConformanceList", "vwNonConformanceFilter"]


def rule(t):
    print("\n" + "=" * 78 + f"\n{t}\n" + "=" * 78)


def show(cur, label, sql, params=()):
    print("\n" + "-" * 78 + f"\n{label}\n" + "-" * 78)
    try:
        cur.execute(sql, params)
        if cur.description is None:
            print("  (no result set)")
            return
        cols = [d[0] for d in cur.description]
        rows = cur.fetchall()
        if not rows:
            print("  (0 rows)")
            return
        print("  " + " | ".join(cols))
        for r in rows[:80]:
            print("  " + " | ".join("" if v is None else str(v) for v in r))
        if len(rows) > 80:
            print(f"  ... (+{len(rows) - 80} more rows)")
    except Exception as e:
        print(f"  [ERROR] {type(e).__name__}: {e}")


def proc_signature(cur, name):
    """Parameters (name, type, length) + can we read the definition?"""
    rule(f"PROC: dbo.{name}")
    show(cur, "  parameters",
         "SELECT p.parameter_id AS ord, p.name, t.name AS type, "
         "p.max_length, p.is_output "
         "FROM sys.parameters p JOIN sys.types t ON t.user_type_id = p.user_type_id "
         "WHERE p.object_id = OBJECT_ID(?) ORDER BY p.parameter_id", (f"dbo.{name}",))
    # OBJECT_DEFINITION needs VIEW DEFINITION; may be NULL for the read-only account.
    print("\n  definition (NULL = account lacks VIEW DEFINITION; grantable if so):")
    try:
        cur.execute("SELECT OBJECT_DEFINITION(OBJECT_ID(?))", (f"dbo.{name}",))
        row = cur.fetchone()
        body = row[0] if row else None
        if not body:
            print("    (definition not visible to this account)")
        else:
            for line in body.splitlines():
                print("    " + line.rstrip())
    except Exception as e:
        print(f"    [ERROR] {type(e).__name__}: {e}")


def main():
    conn = connect()
    cur = conn.cursor()
    try:
        # 0. Full proc inventory (block 1 was truncated at +27 rows last time).
        show(cur, "0. Every stored proc whose name mentions NonConformance / NC costing",
             "SELECT name FROM sys.procedures "
             "WHERE name LIKE '%NonConf%' OR name LIKE '%ByNC' "
             "   OR name LIKE '%NC%Cost%' OR name LIKE '%NCCost%' "
             "ORDER BY name")

        # 1. Signature + definition of each costing/report proc — this is the mirror source.
        for p in COST_PROCS:
            proc_signature(cur, p)

        # 2. The REAL rework-labour link: tblTimecardPunchIns (tblTimecards came back 0).
        rule("REWORK LABOUR — tblTimecardPunchIns (the populated NC link)")
        show(cur, "  2a. columns of tblTimecardPunchIns",
             "SELECT COLUMN_NAME, DATA_TYPE, IS_NULLABLE FROM INFORMATION_SCHEMA.COLUMNS "
             "WHERE TABLE_NAME = 'tblTimecardPunchIns' ORDER BY ORDINAL_POSITION")
        show(cur, "  2b. how many punch-ins carry a NonConformanceID + distinct NCRs",
             "SELECT COUNT(*) AS PunchIns, COUNT(DISTINCT NonConformanceID) AS DistinctNCRs "
             "FROM dbo.tblTimecardPunchIns WHERE NonConformanceID IS NOT NULL")

        # 3. Corrective-action tracking child table (assignment) — for the Detail/aging design.
        rule("CORRECTIVE ACTION — tblNonConformanceAssignment")
        show(cur, "  3a. columns",
             "SELECT COLUMN_NAME, DATA_TYPE, IS_NULLABLE FROM INFORMATION_SCHEMA.COLUMNS "
             "WHERE TABLE_NAME = 'tblNonConformanceAssignment' ORDER BY ORDINAL_POSITION")
        show(cur, "  3b. counts: total assignments, complete vs open, NCRs with an assignment",
             "SELECT COUNT(*) AS Assignments, "
             "SUM(CASE WHEN Complete = 1 THEN 1 ELSE 0 END) AS CompleteCnt, "
             "SUM(CASE WHEN Complete = 0 THEN 1 ELSE 0 END) AS OpenCnt, "
             "COUNT(DISTINCT NonConformanceID) AS NCRsWithAssignment "
             "FROM dbo.tblNonConformanceAssignment")

        # 4. Inventory the two extra NC views so we can pick the best Detail source.
        for v in NC_VIEWS:
            rule(f"VIEW: dbo.{v}")
            show(cur, "  columns",
                 "SELECT COLUMN_NAME, DATA_TYPE, IS_NULLABLE FROM INFORMATION_SCHEMA.COLUMNS "
                 "WHERE TABLE_NAME = ? ORDER BY ORDINAL_POSITION", (v,))

    finally:
        conn.close()
    print("\nDone. Paste the whole output back — this locks the cost-of-NC approach to "
          "ETO's own costing procs (mirror, don't reinvent).")


if __name__ == "__main__":
    main()