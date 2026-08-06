"""
console_diag_inventory_value2.py — on-hand inventory VALUE that reconciles with MATERIAL COSTS
(round 3, 2026-08-06).

DECISION (Vijay): do NOT value inventory from a PO-price average. On-hand value must use ETO's own
inventory costing so it reconciles with the material-cost figures Console already reports
(Resource Consumption = ActTotalMaterials; the pulls carry a CostingValue). This finds the on-hand
LAYER cost and checks that it ties out.

Round 2 showed: no cost on vwInventory; `tblInventoryDetails` / `vwInventoryDetails` are the
per-layer detail; the price log carries InventoryDetailQty + NewPurchasePrice +
PurchasePriceChangeExtendedValue; `vwCostingInventoryPullsDetailed` carries CostingValue /
InventoryCostingValue / PullPrice. So on-hand value should = SUM over on-hand layers of
(layer qty × layer unit cost) — the same basis that becomes the pull CostingValue when consumed.

This maps and reconciles:
  (A) vwInventoryDetails / tblInventoryDetails columns (find the qty + unit-cost/value cols);
  (B) sample layers for on-hand items;
  (C) does SUM(layer qty) per item tie to vwInventory.QtyOnHand? (layers ↔ snapshot check);
  (D) on-hand VALUE per sample project = SUM(layer qty × unit cost), scoped like item_location;
  (E) reconciliation context: the project's consumed inventory value
      (vwCostingInventoryPullsSummed_ByProjectID) and total material cost
      (vwCostingSummed_ByProjectID) so we confirm the SAME costing basis.

READ-ONLY. Run:
    python console_diag_inventory_value2.py                 # projects 192085, 220154
    python console_diag_inventory_value2.py 210065
Paste the WHOLE output.
"""

import sys

NUMERIC = {"money", "smallmoney", "decimal", "numeric", "float", "real", "int", "bigint",
           "smallint", "tinyint"}
QTY_HINTS = ("qtyonhand", "onhand", "qty", "quantity", "remaining", "balance")
COST_HINTS = ("cost", "price", "value")
COST_ANTI = ("date", "changeid", "detailid", "logid", "id", "percent", "pct", "qty", "quantity",
             "location", "employee", "flag")


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


def pick(cols, hints, anti=()):
    for n, t in cols:
        nl = n.lower()
        if t.lower() in NUMERIC and any(h in nl for h in hints) \
                and not any(a in nl for a in anti):
            return n
    return None


def main():
    args = [a for a in sys.argv[1:] if a.isdigit()]
    samples = [int(a) for a in args] if args else [192085, 220154]
    conn = eto_connect()
    cur = conn.cursor()
    print(f"Sample projects: {samples}")
    try:
        # ── A. inventory-detail (layer) objects ───────────────────────────────
        rule("A. INVENTORY-DETAIL (LAYER) COLUMNS — find qty + unit-cost/value")
        detail_obj, qcol, ccol = None, None, None
        for name in ("vwInventoryDetails", "tblInventoryDetails"):
            cols = columns_of(cur, name)
            if not cols:
                print(f"\n  {name}: (not found)")
                continue
            q = pick(cols, QTY_HINTS)
            c = pick(cols, COST_HINTS, COST_ANTI)
            print(f"\n  {name} ({len(cols)} cols) — qty≈{q or '?'}  cost≈{c or '?'}")
            for n, t in cols:
                nl = n.lower()
                mark = ""
                if t.lower() in NUMERIC and any(h in nl for h in QTY_HINTS):
                    mark += " >"
                if t.lower() in NUMERIC and any(h in nl for h in COST_HINTS) \
                        and not any(a in nl for a in COST_ANTI):
                    mark += " $"
                print(f"    {n} : {t}{mark}")
            if detail_obj is None and has_col(cols, "ItemID") and q:
                detail_obj, qcol, ccol = name, q, c

        if not detail_obj:
            print("\n  [stop] no usable inventory-detail object with ItemID + a qty column — "
                  "inspect A output and adjust.")
            return
        print(f"\n  → using {detail_obj}  (qty={qcol}, cost={ccol})")

        # ── B. sample layers for on-hand items ────────────────────────────────
        rule(f"B. SAMPLE LAYERS from {detail_obj} (item + location + qty + cost)")
        idc = "ItemCompanyID" if has_col(columns_of(cur, detail_obj), "ItemCompanyID") else "ItemID"
        sel = [c for c in (idc, "ItemDescription", "InventoryLocation", "LocationName", qcol, ccol)
               if c and has_col(columns_of(cur, detail_obj), c)]
        run(cur, f"B1. {detail_obj} rows with qty > 0",
            f"SELECT TOP 15 {', '.join('['+c+']' for c in sel)} FROM dbo.{detail_obj} "
            f"WHERE [{qcol}] > 0 ORDER BY [{qcol}] DESC")

        # ── C. layers ↔ snapshot: does SUM(layer qty) tie to vwInventory.QtyOnHand? ──
        rule("C. LAYER vs SNAPSHOT — SUM(layer qty) per item vs vwInventory.QtyOnHand")
        run(cur, "C1. items where layer-sum differs from snapshot on-hand (want few/none)",
            f"SELECT TOP 20 v.ItemCompanyID, v.QtyOnHand AS snapshot_onhand, "
            f"d.layer_qty, v.QtyOnHand - d.layer_qty AS diff "
            f"FROM dbo.vwInventory v JOIN (SELECT ItemID, SUM(CAST([{qcol}] AS float)) AS layer_qty "
            f"FROM dbo.{detail_obj} GROUP BY ItemID) d ON d.ItemID = v.ItemID "
            f"WHERE ABS(v.QtyOnHand - d.layer_qty) > 0.01 ORDER BY ABS(v.QtyOnHand - d.layer_qty) DESC")

        # ── D. on-hand VALUE per project (layer qty × unit cost) ──────────────
        rule("D. ON-HAND VALUE per project = SUM(layer qty × unit cost), scoped like item_location")
        if ccol:
            val_expr = f"d.[{qcol}] * d.[{ccol}]"
        else:
            val_expr = "NULL"   # no per-layer cost → will show NULL, adjust after A
        for proj in samples:
            run(cur, f"D/{proj}: on-hand value via {detail_obj} layers",
                "SELECT COUNT(*) AS layers, COUNT(DISTINCT d.ItemID) AS items, "
                f"SUM({val_expr}) AS onhand_value "
                "FROM (SELECT DISTINCT ProjectID, ItemID FROM dbo.vwPurchaseOrderDetails "
                "      WHERE ProjectID = ?) p "
                f"JOIN dbo.{detail_obj} d ON d.ItemID = p.ItemID "
                f"WHERE d.[{qcol}] > 0", (proj,), max_rows=5)

        # ── E. reconciliation context — consumed inventory value & material total ──
        rule("E. RECONCILIATION CONTEXT — consumed inventory value + material total per project")
        for proj in samples:
            run(cur, f"E1/{proj}: consumed inventory-pull value (vwCostingInventoryPullsSummed_ByProjectID)",
                "SELECT * FROM dbo.vwCostingInventoryPullsSummed_ByProjectID WHERE ProjectID = ?",
                (proj,), max_rows=5)
            run(cur, f"E2/{proj}: total material cost (vwCostingSummed_ByProjectID)",
                "SELECT * FROM dbo.vwCostingSummed_ByProjectID WHERE ProjectID = ?",
                (proj,), max_rows=5)

    finally:
        conn.close()
    print("\nDone. Decision it drives:")
    print("  • A/B: the layer qty + unit-cost columns (the on-hand costing basis).")
    print("  • C: layer-sum should match vwInventory.QtyOnHand (few/no diffs) — confirms we can")
    print("    value the SAME on-hand the Item Location report shows.")
    print("  • D: on-hand $ per project from ETO's own layer cost — this is what the report uses.")
    print("  • E: confirms the basis matches the material-cost/pull costing so it reconciles.")


if __name__ == "__main__":
    main()
