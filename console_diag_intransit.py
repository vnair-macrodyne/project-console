"""
console_diag_intransit.py — confirm the IN-TRANSIT inventory view before building (2026-08-06).

Report 3 = stock currently in the In-Transit locations (InventoryLocation 5 = In Transit to Racco,
6 = In Transit to Connie), valued from tblInventoryDetails layers (same basis as Inventory Value).
This checks: is there anything in transit now, what's its value, and do the items intersect tracked
projects' POs (→ project-scoped like the others) or not (→ portfolio-wide).

READ-ONLY. Run:  python console_diag_intransit.py
Paste the WHOLE output.
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


def rule(t):
    print("\n" + "=" * 78 + f"\n{t}\n" + "=" * 78)


def run(cur, label, sql, params=(), max_rows=30):
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


# In-transit location ids from the master (5 = In Transit to Racco, 6 = In Transit to Connie)
INTRANSIT = "(5, 6)"


def main():
    conn = eto_connect()
    cur = conn.cursor()
    try:
        rule("A. IS THERE STOCK IN TRANSIT NOW? (vwInventory, by in-transit location)")
        run(cur, "A1. lines / items / total qty in in-transit locations (QtyOnHand > 0)",
            "SELECT v.LocationName, COUNT(*) AS lines, COUNT(DISTINCT v.ItemID) AS items, "
            "SUM(v.QtyOnHand) AS total_qty "
            f"FROM dbo.vwInventory v WHERE v.InventoryLocation IN {INTRANSIT} AND v.QtyOnHand > 0 "
            "GROUP BY v.LocationName")

        rule("B. SAMPLE in-transit lines")
        run(cur, "B1. rows",
            "SELECT TOP 25 v.ItemCompanyID, v.ItemDescription, v.LocationName, v.BinLabel, v.QtyOnHand "
            f"FROM dbo.vwInventory v WHERE v.InventoryLocation IN {INTRANSIT} AND v.QtyOnHand > 0 "
            "ORDER BY v.QtyOnHand DESC")

        rule("C. VALUE of in-transit stock (tblInventoryDetails layers — same basis as Inventory Value)")
        run(cur, "C1. total in-transit value + how many lines have a costed layer",
            "SELECT COUNT(*) AS lines, "
            "SUM(lay.ExtValue) AS intransit_value, "
            "SUM(CASE WHEN lay.ExtValue IS NULL THEN 1 ELSE 0 END) AS lines_uncosted "
            "FROM dbo.vwInventory v "
            "LEFT JOIN (SELECT ItemID, InventoryLocation, "
            "                  SUM(CAST(InventoryDetailQty AS float)*CAST(PurchasePrice AS float)) AS ExtValue "
            "           FROM dbo.tblInventoryDetails GROUP BY ItemID, InventoryLocation) lay "
            "  ON lay.ItemID = v.ItemID AND lay.InventoryLocation = v.InventoryLocation "
            f"WHERE v.InventoryLocation IN {INTRANSIT} AND v.QtyOnHand > 0")

        rule("D. SCOPE CHECK — do in-transit items appear on tracked projects' POs?")
        run(cur, "D1. in-transit items that ARE on some project's PO vs not",
            "SELECT SUM(CASE WHEN pod.ItemID IS NOT NULL THEN 1 ELSE 0 END) AS on_a_project_po, "
            "SUM(CASE WHEN pod.ItemID IS NULL THEN 1 ELSE 0 END) AS not_on_any_po "
            "FROM (SELECT DISTINCT ItemID FROM dbo.vwInventory "
            f"      WHERE InventoryLocation IN {INTRANSIT} AND QtyOnHand > 0) v "
            "LEFT JOIN (SELECT DISTINCT ItemID FROM dbo.vwPurchaseOrderDetails) pod "
            "  ON pod.ItemID = v.ItemID")
        run(cur, "D2. which projects have in-transit material (top by line count)",
            "SELECT TOP 20 pod.ProjectID, COUNT(DISTINCT v.ItemID) AS intransit_items "
            "FROM (SELECT DISTINCT ItemID FROM dbo.vwInventory "
            f"      WHERE InventoryLocation IN {INTRANSIT} AND QtyOnHand > 0) v "
            "JOIN (SELECT DISTINCT ProjectID, ItemID FROM dbo.vwPurchaseOrderDetails) pod "
            "  ON pod.ItemID = v.ItemID GROUP BY pod.ProjectID ORDER BY intransit_items DESC")

    finally:
        conn.close()
    print("\nDone. Decision it drives:")
    print("  • A/B: is there stock in transit right now, and how much.")
    print("  • C: its value (uses the Inventory Value layer basis).")
    print("  • D1: if most in-transit items ARE on project POs → project-scoped report (consistent);")
    print("    if many are not → portfolio-wide report so nothing's hidden. D2 shows which projects.")


if __name__ == "__main__":
    main()
