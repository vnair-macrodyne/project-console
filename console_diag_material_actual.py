"""
console_diag_material_actual.py — validate derived Material Actual from purchases (read-only).

The dashboard's Material Actual is now derived from ETO purchase orders as the COMMITTED
(ordered) value per project, in Canadian dollars:
    committed = SUM( ExtendedPrice × PurchaseCurrRate )  over active PO lines
(an invalid/zero rate is treated as 1.0). This probe prints, per project, the line count,
the native total, the committed CAD total (what the dashboard now shows), and an approximate
RECEIVED-to-date CAD total — so you can reconcile the numbers and decide whether "actual"
should be committed (ordered) or received. Pure SELECT; nothing written.

Run on the box:
    python console_diag_material_actual.py                 (a few sample projects)
    python console_diag_material_actual.py 230219 230312   (specific projects)
Paste the output back.
"""
import sys

DEFAULT_PROJECTS = [230219, 230312, 240087, 240033, 240148]


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
    args = [a for a in sys.argv[1:] if a.strip().isdigit()]
    pids = [int(a) for a in args] or DEFAULT_PROJECTS
    ids = ",".join(str(p) for p in pids)
    rate = "CASE WHEN poh.PurchaseCurrRate > 0 THEN poh.PurchaseCurrRate ELSE 1 END"
    recv_ratio = "CASE WHEN pod.PurchaseQty > 0 THEN " \
                 "CASE WHEN pod.Received > pod.PurchaseQty THEN 1 ELSE pod.Received/pod.PurchaseQty END " \
                 "ELSE 0 END"
    sql = f"""
    SELECT pod.ProjectID                                   AS ProjectID,
           COUNT(*)                                        AS Lines,
           CAST(SUM(pod.ExtendedPrice) AS decimal(20,2))   AS NativeTotal,
           CAST(SUM(pod.ExtendedPrice * {rate}) AS decimal(20,2))            AS CommittedCAD,
           CAST(SUM(pod.ExtendedPrice * {rate} * ({recv_ratio})) AS decimal(20,2)) AS ReceivedCAD
    FROM dbo.vwPurchaseOrderDetails pod
    JOIN dbo.vwPurchaseOrderHeader poh ON poh.PurchaseOrderID = pod.PurchaseOrderID
    WHERE pod.ProjectID IN ({ids}) AND poh.PurchaseActive = 1
    GROUP BY pod.ProjectID
    ORDER BY pod.ProjectID
    """
    conn = connect()
    cur = conn.cursor()
    try:
        cur.execute(sql)
        cols = [d[0] for d in cur.description]
        print("  " + " | ".join(cols))
        gc = gr = 0.0
        for r in cur.fetchall():
            print("  " + " | ".join("" if v is None else str(v) for v in r))
            gc += float(r[3] or 0)
            gr += float(r[4] or 0)
        print(f"\n  Portfolio (selected): committed CAD = {gc:,.2f}   received CAD = {gr:,.2f}")
        print("  The dashboard's Material Actual = CommittedCAD (ordered). ReceivedCAD is shown "
              "only so you can compare; switching the dashboard to received is a one-line change.")
    except Exception as e:
        print(f"  [ERROR] {type(e).__name__}: {e}")
    finally:
        conn.close()
    print("\nDone. Paste the output back.")


if __name__ == "__main__":
    main()
