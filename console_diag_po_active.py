"""
console_diag_po_active.py — does PurchaseActive=1 undercount committed material? (read-only)

Closes assumption A1. Material Actual sums active PO lines (poh.PurchaseActive = 1). If
completed/received POs flip PurchaseActive to 0, committed material is understated. This
prints, per project, committed CAD WITH vs WITHOUT the filter, and shows what PurchaseActive
actually marks (are inactive POs fully received, or cancelled?). Pure SELECT.

Run on the box:  python console_diag_po_active.py [projid ...]   ·   paste the output back.
"""
import sys

DEFAULT_PROJECTS = [230219, 230312, 240087]
RATE = "CASE WHEN poh.PurchaseCurrRate > 0 THEN poh.PurchaseCurrRate ELSE 1 END"


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


def show(cur, label, sql):
    print("\n" + "-" * 78 + f"\n{label}\n" + "-" * 78)
    try:
        cur.execute(sql)
        cols = [d[0] for d in cur.description]
        rows = cur.fetchall()
        print("  " + " | ".join(cols))
        for r in rows[:80]:
            print("  " + " | ".join("" if v is None else str(v) for v in r))
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
        # 1. Committed CAD with the active filter vs without — the size of any undercount.
        show(cur, "1. Committed material (CAD): PurchaseActive=1 vs ALL POs, per project",
             "SELECT pod.ProjectID AS ProjectID, "
             f"CAST(SUM(CASE WHEN poh.PurchaseActive = 1 THEN pod.ExtendedPrice * {RATE} ELSE 0 END) AS decimal(20,2)) AS Committed_Active, "
             f"CAST(SUM(pod.ExtendedPrice * {RATE}) AS decimal(20,2)) AS Committed_All "
             "FROM dbo.vwPurchaseOrderDetails pod "
             "JOIN dbo.vwPurchaseOrderHeader poh ON poh.PurchaseOrderID = pod.PurchaseOrderID "
             f"WHERE pod.ProjectID IN ({ids}) GROUP BY pod.ProjectID ORDER BY pod.ProjectID")

        # 2. What does PurchaseActive mark? counts of active vs inactive POs (whole DB sample).
        show(cur, "2. PurchaseActive distribution across POs (is 0 rare = cancelled, or common = closed?)",
             "SELECT PurchaseActive, COUNT(*) AS POs FROM dbo.vwPurchaseOrderHeader "
             "GROUP BY PurchaseActive ORDER BY PurchaseActive")

        # 3. For the sample projects: are INACTIVE POs fully received (closed) or not (cancelled)?
        show(cur, "3. For selected projects: inactive-PO lines — received vs not (closed vs cancelled?)",
             "SELECT poh.PurchaseActive AS PurchaseActive, "
             "SUM(CASE WHEN pod.Received >= pod.PurchaseQty THEN 1 ELSE 0 END) AS FullyReceivedLines, "
             "SUM(CASE WHEN pod.Received IS NULL OR pod.Received < pod.PurchaseQty THEN 1 ELSE 0 END) AS OpenLines, "
             "COUNT(*) AS Lines "
             "FROM dbo.vwPurchaseOrderDetails pod "
             "JOIN dbo.vwPurchaseOrderHeader poh ON poh.PurchaseOrderID = pod.PurchaseOrderID "
             f"WHERE pod.ProjectID IN ({ids}) GROUP BY poh.PurchaseActive ORDER BY poh.PurchaseActive")
    finally:
        conn.close()
    print("\nDone. If Committed_All >> Committed_Active and inactive POs are mostly fully "
          "received, the active filter undercounts — we'd drop it (or count received separately).")


if __name__ == "__main__":
    main()
