"""
console_diag_ncr.py — read-only Non-Conformance (NCR) discovery probe (2026-07-26).

Single-pass probe to scope the Non-Conformance module the same way we scoped PO
lateness and budgets: verify the REAL columns and the REAL data population before
writing any console query. Nothing here writes; it reads metadata + aggregates only.

Run on the domain-joined box (same folder as the suite):
    python console_diag_ncr.py
Copy the WHOLE output back and the NCR views can be locked to real columns + real
definitions in one pass instead of one 42S22 error at a time.

Uses the suite's proven read-only ETO connector (console_store.eto_connection) —
the same one console_diag_eto_views.py / console_diag_po_late.py use, which falls
back to console_config.TENANT + ETO_USER/ETO_PWD when the eto_reports/eto_config
modules aren't present in this repo.
Every block is wrapped so one failure (missing column/object) never aborts the run —
a failed block prints its error and the probe keeps going.
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

# Canonical test project reused across the suite (Reg/OT + PO discovery used it too).
TEST_PROJECT = 230219


def show(cur, label, sql, params=()):
    """Run one labelled query; print rows or the error. Never raises."""
    print("\n" + "-" * 78)
    print(label)
    print("-" * 78)
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
        for r in rows[:60]:
            print("  " + " | ".join("" if v is None else str(v) for v in r))
        if len(rows) > 60:
            print(f"  ... (+{len(rows) - 60} more rows)")
    except Exception as e:  # tolerant: keep probing
        print(f"  [ERROR] {type(e).__name__}: {e}")


def dump_columns(cur, obj):
    """Full column list of a table/view via INFORMATION_SCHEMA (always safe)."""
    print("\n" + "=" * 78)
    print(f"COLUMNS OF: {obj}")
    print("=" * 78)
    try:
        cur.execute(
            "SELECT COLUMN_NAME, DATA_TYPE, IS_NULLABLE "
            "FROM INFORMATION_SCHEMA.COLUMNS WHERE TABLE_NAME = ? "
            "ORDER BY ORDINAL_POSITION", obj)
        rows = cur.fetchall()
        if not rows:
            print("  (object not found under this name — check schema/prefix)")
            return
        for name, dt, nullable in rows:
            print(f"    {name:<34} {dt:<16} {'NULL' if nullable == 'YES' else 'NOT NULL'}")
    except Exception as e:
        print(f"  [ERROR] {type(e).__name__}: {e}")


def main():
    conn = connect()
    cur = conn.cursor()
    try:
        # 1. Which NCR-related objects even exist (tables, views, procs, functions)?
        show(cur, "1. All objects whose name mentions NonConformance / NC / NCR",
             "SELECT o.name, o.type_desc "
             "FROM sys.objects o "
             "WHERE o.name LIKE '%NonConformance%' OR o.name LIKE '%NonConf%' "
             "   OR o.name LIKE '%NCR%' OR o.name LIKE 'urp%NC%' "
             "ORDER BY o.type_desc, o.name")

        # 2. Full column inventory of the core objects (verified vs. inferred).
        for obj in ("tblNonConformance", "vwNonConformances",
                    "tlkpNonConformanceSource", "tlkpNonConformanceOrigin"):
            dump_columns(cur, obj)

        # 2b. Any OTHER lookup/column that might carry root-cause / type / disposition /
        #     responsible dept / corrective-action fields the Function Map wants.
        show(cur, "2b. Columns across the DB that look NCR-semantic "
                  "(rootcause/disposition/type/severity/corrective/responsible/duedate)",
             "SELECT TABLE_NAME, COLUMN_NAME, DATA_TYPE "
             "FROM INFORMATION_SCHEMA.COLUMNS "
             "WHERE TABLE_NAME LIKE '%NonConf%' "
             "   OR COLUMN_NAME LIKE '%RootCause%' OR COLUMN_NAME LIKE '%Disposition%' "
             "   OR COLUMN_NAME LIKE '%Severity%'  OR COLUMN_NAME LIKE '%Corrective%' "
             "   OR COLUMN_NAME LIKE '%Responsible%' "
             "ORDER BY TABLE_NAME, ORDINAL_POSITION")

        # 3. Headline counts — total, open/closed, PO-linked, date completeness.
        show(cur, "3. tblNonConformance headline counts",
             "SELECT COUNT(*) AS Total, "
             "SUM(CASE WHEN Resolved = 1 THEN 1 ELSE 0 END) AS Closed, "
             "SUM(CASE WHEN Resolved = 0 THEN 1 ELSE 0 END) AS [Open], "
             "SUM(CASE WHEN PurchaseOrderID IS NOT NULL THEN 1 ELSE 0 END) AS WithPO, "
             "SUM(CASE WHEN CreationDate IS NULL THEN 1 ELSE 0 END) AS NullCreationDate, "
             "MIN(CreationDate) AS FirstCreated, MAX(CreationDate) AS LastCreated "
             "FROM dbo.tblNonConformance")

        # 4. Distribution by Source and Origin (IDs always present; join names if we can).
        show(cur, "4a. NCR count by NonConformanceSourceID (raw)",
             "SELECT NonConformanceSourceID, COUNT(*) AS n "
             "FROM dbo.tblNonConformance GROUP BY NonConformanceSourceID ORDER BY n DESC")
        show(cur, "4b. NCR count by NonConformanceOriginID (raw)",
             "SELECT NonConformanceOriginID, COUNT(*) AS n "
             "FROM dbo.tblNonConformance GROUP BY NonConformanceOriginID ORDER BY n DESC")
        show(cur, "4c. NCR count by Source/Origin DESCRIPTION via vwNonConformances "
                  "(confirms the view exposes readable names)",
             "SELECT SourceDescription, NonConformanceOriginDescription, COUNT(*) AS n "
             "FROM dbo.vwNonConformances "
             "GROUP BY SourceDescription, NonConformanceOriginDescription ORDER BY n DESC")

        # 5. Aging of OPEN NCRs (today - CreationDate). Drives an NC Aging report.
        show(cur, "5. Open-NCR aging buckets (days since CreationDate)",
             "SELECT CASE "
             "  WHEN DATEDIFF(day, CreationDate, GETDATE()) <= 30  THEN '0-30' "
             "  WHEN DATEDIFF(day, CreationDate, GETDATE()) <= 60  THEN '31-60' "
             "  WHEN DATEDIFF(day, CreationDate, GETDATE()) <= 90  THEN '61-90' "
             "  WHEN DATEDIFF(day, CreationDate, GETDATE()) <= 180 THEN '91-180' "
             "  ELSE '180+' END AS AgeBucket, COUNT(*) AS OpenNCRs "
             "FROM dbo.tblNonConformance WHERE Resolved = 0 AND CreationDate IS NOT NULL "
             "GROUP BY CASE "
             "  WHEN DATEDIFF(day, CreationDate, GETDATE()) <= 30  THEN '0-30' "
             "  WHEN DATEDIFF(day, CreationDate, GETDATE()) <= 60  THEN '31-60' "
             "  WHEN DATEDIFF(day, CreationDate, GETDATE()) <= 90  THEN '61-90' "
             "  WHEN DATEDIFF(day, CreationDate, GETDATE()) <= 180 THEN '91-180' "
             "  ELSE '180+' END")

        # 6. THE COST-OF-NON-CONFORMANCE CHECK — is the link data actually populated?
        #    (Learned from PO lateness: EstimatedLeadTime looked available but was EMPTY.)
        # 6a. Rework labour: timecards that carry a NonConformanceID.
        show(cur, "6a. Rework LABOUR via tblTimecards.NonConformanceID "
                  "(applied-rate cost = HourTime*HourRate*HourFactor)",
             "SELECT COUNT(*) AS ReworkTimecards, "
             "COUNT(DISTINCT NonConformanceID) AS DistinctNCRsWithRework, "
             "SUM(HourTime) AS ReworkHours, "
             "SUM(HourTime * HourRate * HourFactor) AS ReworkCost "
             "FROM dbo.tblTimecards WHERE NonConformanceID IS NOT NULL")
        # 6b. Remedy material: PO detail lines that carry a NonConformanceID.
        show(cur, "6b. Remedy MATERIAL via tblPurchaseOrderDetails.NonConformanceID",
             "SELECT COUNT(*) AS RemedyPOLines, "
             "COUNT(DISTINCT NonConformanceID) AS DistinctNCRsWithRemedyPO, "
             "SUM(PurchaseQty * PurchasePrice) AS RemedyExtValue "
             "FROM dbo.tblPurchaseOrderDetails WHERE NonConformanceID IS NOT NULL")

        # 7. Project-scoped sanity check on the canonical test project.
        show(cur, f"7. NCRs for the canonical test project {TEST_PROJECT}",
             "SELECT COUNT(*) AS Total, "
             "SUM(CASE WHEN Resolved = 0 THEN 1 ELSE 0 END) AS [Open], "
             "SUM(CASE WHEN Resolved = 1 THEN 1 ELSE 0 END) AS [Closed] "
             "FROM dbo.tblNonConformance WHERE ProjectID = ?", (TEST_PROJECT,))

        # 8. One sample open + one sample closed NCR (redact nothing; small, read-only).
        show(cur, "8a. Sample OPEN NCR (top 1, all view columns)",
             "SELECT TOP 1 * FROM dbo.vwNonConformances "
             "WHERE Resolved = 0 ORDER BY NonConformanceID DESC")
        show(cur, "8b. Sample CLOSED NCR (top 1, all view columns)",
             "SELECT TOP 1 * FROM dbo.vwNonConformances "
             "WHERE Resolved = 1 ORDER BY NonConformanceID DESC")

    finally:
        conn.close()
    print("\nDone. Paste the whole output back to lock the NCR module to real columns.")


if __name__ == "__main__":
    main()