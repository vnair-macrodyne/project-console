"""
console_diag_ncr_cost_source.py — confirm the NC cost SOURCE + build path (2026-07-26).

The NC costing SP definitions are now in hand (ETO_NC_COSTING_SPS.sql). They all roll up
through ONE vendor view:

    vwCostingSummed_ByNC  (per NonConformanceID):
        LaborCostingValue, ExtraCostingValue, InventoryCostingValue,
        PurchasedCostingValue, TotalNCCostingValue,
        AdminHours/EngHours/MFGHours/TotalHours, AdminLabor/EngLabor/MFGLabor

    urpNonConformancesWithCosts  ==  vwNonConformances NC
                                     INNER JOIN vwCostingSummed_ByNC C
                                     ON NC.NonConformanceID = C.NonConformanceID
                                     WHERE SActive = 1  (+ project/date/origin/etc filters)

So the console NC-Costs report is a straight TRANSCRIPTION of that join, project/date-scoped —
exactly how we transcribed urpPurchasingLateVendors. The only thing to verify is whether the
reporting account has direct SELECT on the costing views (fast path); if not, we fall back to
EXEC dbo.urpNonConformancesWithCosts (bounded by the same params).

This probe: (A) dumps + SELECT-tests the costing views, (B) runs the TRANSCRIBED scoped query
for project 230219 with per-dimension totals + INNER-vs-LEFT coverage, (C) runs the Origin-
grouped cost compare, (D) EXECs the proc as the fallback cross-check. Pure read; nothing written.

Run on the box:  python console_diag_ncr_cost_source.py
Paste the WHOLE output back.
"""

TEST_PROJECT = 230219

# The vendor costing views the SPs read from (per-NC rollup + the detail/summed dimensions).
COSTING_VIEWS = [
    "vwCostingSummed_ByNC",                    # master per-NC rollup (the one we transcribe)
    "vwCostingTimecardsSummed_ByNC",           # labour by NC
    "vwCostingPurchasedMaterialsSummed_ByNC",  # PO'd material by NC
    "vwCostingInventoryPullsSummed_ByNC",      # inventory pulls by NC
    "vwCostingExtraCostsSummed_ByNC",          # extra costs / payables by NC
    "vwCostingTimecardsDetailed",              # labour detail (urpCosting_LabourByNC source)
    "vwCostingInventoryPullsDetailed",         # inventory detail
    "vwCostingExtraCostsDetailed",             # extra-cost detail
]


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


def run(cur, label, sql, params=(), max_rows=15):
    print("\n" + "-" * 78 + f"\n{label}\n" + "-" * 78)
    try:
        cur.execute(sql, params)
        while cur.description is None and cur.nextset():
            pass
        if cur.description is None:
            print("  (executed OK, no result set)")
            return
        cols = [d[0] for d in cur.description]
        rows = cur.fetchall()
        print("  " + " | ".join(cols))
        for r in rows[:max_rows]:
            print("  " + " | ".join("" if v is None else str(v) for v in r))
        if len(rows) > max_rows:
            print(f"  ... (+{len(rows) - max_rows} more rows)")
        if not rows:
            print("  (0 rows)")
    except Exception as e:
        print(f"  [ERROR] {type(e).__name__}: {e}")


def main():
    conn = connect()
    cur = conn.cursor()
    try:
        # A. Do we have SELECT on the costing views, and what columns do they carry?
        rule("A. COSTING VIEWS — columns + SELECT-rights test")
        for v in COSTING_VIEWS:
            run(cur, f"A/{v} — columns",
                "SELECT COLUMN_NAME, DATA_TYPE FROM INFORMATION_SCHEMA.COLUMNS "
                "WHERE TABLE_NAME = ? ORDER BY ORDINAL_POSITION", (v,))
            run(cur, f"A/{v} — SELECT TOP 1 (rights + shape)",
                f"SELECT TOP 1 * FROM dbo.{v}")

        # B. THE BUILD PATH — transcription of urpNonConformancesWithCosts, scoped.
        rule(f"B. TRANSCRIBED scoped NC-costs query — project {TEST_PROJECT}")
        run(cur, "B1. per-NC cost rows (the report)",
            "SELECT NC.NonConformanceID, NC.NonConformanceBarcode, NC.Resolved, "
            "NC.SourceDescription, NC.NonConformanceOriginDescription, "
            "C.LaborCostingValue, C.PurchasedCostingValue, C.InventoryCostingValue, "
            "C.ExtraCostingValue, C.TotalNCCostingValue "
            "FROM dbo.vwNonConformances NC "
            "INNER JOIN dbo.vwCostingSummed_ByNC C ON NC.NonConformanceID = C.NonConformanceID "
            "WHERE NC.SActive = 1 AND NC.ProjectID = ? "
            "ORDER BY C.TotalNCCostingValue DESC", (TEST_PROJECT,))
        run(cur, "B2. project totals by dimension (labour expected ~0; material carries)",
            "SELECT COUNT(*) AS NCsWithCost, "
            "SUM(C.LaborCostingValue) AS Labour, SUM(C.PurchasedCostingValue) AS PurchasedMat, "
            "SUM(C.InventoryCostingValue) AS InventoryMat, SUM(C.ExtraCostingValue) AS ExtraPayables, "
            "SUM(C.TotalNCCostingValue) AS TotalNCCost "
            "FROM dbo.vwNonConformances NC "
            "INNER JOIN dbo.vwCostingSummed_ByNC C ON NC.NonConformanceID = C.NonConformanceID "
            "WHERE NC.SActive = 1 AND NC.ProjectID = ?", (TEST_PROJECT,))
        run(cur, "B3. INNER-vs-LEFT coverage — do zero-cost NCs drop out of the INNER JOIN?",
            "SELECT "
            "(SELECT COUNT(*) FROM dbo.vwNonConformances WHERE SActive=1 AND ProjectID=?) AS AllNCs, "
            "(SELECT COUNT(*) FROM dbo.vwNonConformances NC "
            "  INNER JOIN dbo.vwCostingSummed_ByNC C ON NC.NonConformanceID=C.NonConformanceID "
            "  WHERE NC.SActive=1 AND NC.ProjectID=?) AS NCsWithCostingRow",
            (TEST_PROJECT, TEST_PROJECT))

        # C. Origin-grouped cost summary (transcription of urpNonConformanceCostingCompared).
        rule(f"C. Cost by Origin — project {TEST_PROJECT} (NC Summary-with-cost shape)")
        run(cur, "C1.",
            "SELECT NC.NonConformanceOriginDescription AS Origin, "
            "CAST(SUM(C.LaborCostingValue) AS decimal(20,2)) AS LabourCost, "
            "CAST(SUM(C.PurchasedCostingValue + C.InventoryCostingValue + C.ExtraCostingValue) "
            "     AS decimal(20,2)) AS MaterialCost, "
            "CAST(SUM(C.TotalNCCostingValue) AS decimal(20,2)) AS TotalCost, COUNT(*) AS NCs "
            "FROM dbo.vwNonConformances NC "
            "INNER JOIN dbo.vwCostingSummed_ByNC C ON NC.NonConformanceID = C.NonConformanceID "
            "WHERE NC.SActive = 1 AND NC.ProjectID = ? "
            "GROUP BY NC.NonConformanceOriginDescription ORDER BY TotalCost DESC", (TEST_PROJECT,))

        # D. EXEC fallback cross-check — same proc, should match B's totals.
        rule("D. EXEC fallback cross-check — urpNonConformancesWithCosts")
        run(cur, "D1. EXEC project-scoped (compare row count/costs to B)",
            f"EXEC dbo.urpNonConformancesWithCosts @intProjectID = {TEST_PROJECT}")

    finally:
        conn.close()
    print("\nDone. Paste the whole output back. If section A/B SELECTs succeed we build the "
          "NC-Costs report as a direct transcription; if denied, we use the section-D EXEC path.")


if __name__ == "__main__":
    main()