"""
console_diag_inventory_value3.py — LOCK the on-hand costing basis on tblInventoryDetails
(round 4, 2026-08-06).

value2 mistakenly used vwInventoryDetails.ItemLastCost, which is NOT UOM-consistent with QtyOnHand
(cable tie E05416: ItemLastCost 110 = per BAG-of-1000 while on-hand 4000 = EACH → 440k nonsense).
The correct basis is the per-receipt LAYER table tblInventoryDetails:
    InventoryDetailQty (stock UOM)  ×  PurchasePrice (that layer's actual price)  = layer value,
UOM-consistent and the SAME basis ETO consumes (vwCostingSummed_ByProjectID.TotalInventoryPulls).

This confirms:
  (A) grain tie-out — SUM(layer qty) per item+location == vwInventory.QtyOnHand (few/no diffs);
  (B) UOM proof — cable tie & friends now value sanely via layers vs the bogus ItemLastCost way;
  (C) on-hand VALUE per project via layers, TWO scopes:
        (C1) items on the project's POs  (shared-pool, matches Item Location), and
        (C2) layers RECEIVED on the project's POs (project-attributed, ties to material cost);
  (D) reconciliation: on-hand(C2) vs consumed TotalInventoryPulls vs TotalPurchasedMaterials.

READ-ONLY. Run:
    python console_diag_inventory_value3.py                 # projects 192085, 220154
    python console_diag_inventory_value3.py 210065
Paste the WHOLE output.
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


def run(cur, label, sql, params=(), max_rows=25):
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


def columns_of(cur, name):
    try:
        cur.execute("SELECT COLUMN_NAME, DATA_TYPE FROM INFORMATION_SCHEMA.COLUMNS "
                    "WHERE TABLE_NAME = ? ORDER BY ORDINAL_POSITION", (name,))
        return [(r[0], r[1]) for r in cur.fetchall()]
    except Exception:
        return []


def has_col(cols, name):
    return any(c[0].lower() == name.lower() for c in cols)


def main():
    args = [a for a in sys.argv[1:] if a.isdigit()]
    samples = [int(a) for a in args] if args else [192085, 220154]
    conn = eto_connect()
    cur = conn.cursor()
    print(f"Sample projects: {samples}")

    # detect the PO→project join key on vwPurchaseOrderDetails
    pod = columns_of(cur, "vwPurchaseOrderDetails")
    join_key = "PurchaseDetailID" if has_col(pod, "PurchaseDetailID") else "PurchaseOrderID"
    print(f"Layer→PO join key: tblInventoryDetails.{join_key} → vwPurchaseOrderDetails.{join_key}")

    try:
        # ── A. grain tie-out: layer qty vs snapshot, at item+location ─────────
        rule("A. GRAIN TIE-OUT — SUM(layer qty) vs vwInventory.QtyOnHand at ITEM+LOCATION")
        run(cur, "A1. rows where they differ by > 0.01 (want few/none)",
            "SELECT TOP 20 v.ItemCompanyID, v.LocationName, v.QtyOnHand AS snapshot, "
            "l.qty AS layer_qty, v.QtyOnHand - l.qty AS diff "
            "FROM dbo.vwInventory v "
            "JOIN (SELECT ItemID, InventoryLocation, SUM(CAST(InventoryDetailQty AS float)) AS qty "
            "      FROM dbo.tblInventoryDetails GROUP BY ItemID, InventoryLocation) l "
            "  ON l.ItemID = v.ItemID AND l.InventoryLocation = v.InventoryLocation "
            "WHERE ABS(v.QtyOnHand - l.qty) > 0.01 ORDER BY ABS(v.QtyOnHand - l.qty) DESC")
        run(cur, "A2. how many item+location rows tie vs differ",
            "SELECT SUM(CASE WHEN ABS(v.QtyOnHand - l.qty) <= 0.01 THEN 1 ELSE 0 END) AS tie, "
            "SUM(CASE WHEN ABS(v.QtyOnHand - l.qty) > 0.01 THEN 1 ELSE 0 END) AS differ "
            "FROM dbo.vwInventory v "
            "JOIN (SELECT ItemID, InventoryLocation, SUM(CAST(InventoryDetailQty AS float)) AS qty "
            "      FROM dbo.tblInventoryDetails GROUP BY ItemID, InventoryLocation) l "
            "  ON l.ItemID = v.ItemID AND l.InventoryLocation = v.InventoryLocation")

        # ── B. UOM proof — layer value vs the bogus ItemLastCost way ──────────
        rule("B. UOM PROOF — cable tie & friends: layer value (correct) vs ItemLastCost (wrong)")
        run(cur, "B1. E05416 and a few: on-hand, layer value, vs QtyOnHand×ItemLastCost",
            "SELECT v.ItemCompanyID, v.LocationName, v.QtyOnHand, "
            "lay.layer_value, v.QtyOnHand * vd.ItemLastCost AS bogus_lastcost_value "
            "FROM dbo.vwInventory v "
            "JOIN dbo.vwInventoryDetails vd ON vd.ItemID = v.ItemID "
            "  AND vd.InventoryLocation = v.InventoryLocation "
            "JOIN (SELECT ItemID, InventoryLocation, "
            "      SUM(CAST(InventoryDetailQty AS float) * CAST(PurchasePrice AS float)) AS layer_value "
            "      FROM dbo.tblInventoryDetails GROUP BY ItemID, InventoryLocation) lay "
            "  ON lay.ItemID = v.ItemID AND lay.InventoryLocation = v.InventoryLocation "
            "WHERE v.ItemCompanyID IN ('E05416','E05413','E09050','E03308') "
            "ORDER BY v.ItemCompanyID")

        # ── C. on-hand VALUE per project via layers — two scopes ──────────────
        rule("C. ON-HAND VALUE per project via tblInventoryDetails layers")
        for proj in samples:
            run(cur, f"C1/{proj}: SHARED-POOL scope (items on the project's POs) — matches Item Location",
                "SELECT COUNT(DISTINCT l.ItemID) AS items, "
                "SUM(CAST(l.InventoryDetailQty AS float) * CAST(l.PurchasePrice AS float)) AS onhand_value "
                "FROM (SELECT DISTINCT ItemID FROM dbo.vwPurchaseOrderDetails WHERE ProjectID = ?) p "
                "JOIN dbo.tblInventoryDetails l ON l.ItemID = p.ItemID", (proj,), max_rows=5)
            run(cur, f"C2/{proj}: PROJECT-ATTRIBUTED scope (layers received on the project's POs)",
                "SELECT COUNT(*) AS layers, COUNT(DISTINCT l.ItemID) AS items, "
                "SUM(CAST(l.InventoryDetailQty AS float) * CAST(l.PurchasePrice AS float)) AS onhand_value "
                "FROM dbo.tblInventoryDetails l "
                f"JOIN (SELECT DISTINCT {join_key}, ProjectID FROM dbo.vwPurchaseOrderDetails) pod "
                f"  ON pod.{join_key} = l.{join_key} "
                "WHERE pod.ProjectID = ?", (proj,), max_rows=5)

        # ── D. reconciliation context ─────────────────────────────────────────
        rule("D. RECONCILIATION — on-hand(C2) vs consumed pulls vs purchased materials")
        for proj in samples:
            run(cur, f"D/{proj}: TotalPurchasedMaterials, TotalInventoryPulls (consumed) for context",
                "SELECT ProjectID, TotalPurchasedMaterials, TotalInventoryPulls, TotalMaterials "
                "FROM dbo.vwCostingSummed_ByProjectID WHERE ProjectID = ?", (proj,), max_rows=5)

    finally:
        conn.close()
    print("\nDone. Decision it drives:")
    print("  • A2: layers should tie to the snapshot at item+location (mostly tie) → we can value")
    print("    the SAME on-hand Item Location shows, from the layer PurchasePrice.")
    print("  • B1: layer_value sane; bogus_lastcost_value inflated (UOM) — confirms we use layers.")
    print("  • C1 vs C2: shared-pool total vs project-attributed total (pick the report's scope).")
    print("  • D: same costing basis as TotalInventoryPulls → reconciles with material costs.")


if __name__ == "__main__":
    main()
