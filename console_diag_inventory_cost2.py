"""
console_diag_inventory_cost2.py — nail the ON-HAND cost basis (round 2, 2026-08-06).

Round 1 found: vwInventory/tblInventory carry NO cost; no item-master table under the usual
names; vwPurchaseOrderDetails has PurchasePrice + ExtendedPrice (but r1's unit math was wrong —
it divided a likely-unit price by qty). ETO also has a dedicated inventory price log
(tblInventoryDetailsPurchasePriceChangeLog) that implies a per-item carrying cost.

This round pins the cost basis three ways and sanity-checks extended value:
  (A) find the item master (whatever table actually carries ItemCompanyID) + any cost column;
  (B) profile the inventory purchase-price / pull-price logs and pull LATEST price per item;
  (C) disambiguate PurchasePrice vs ExtendedPrice (unit or line total?) and derive a CORRECT
      per-item unit cost — last price and weighted-average;
  (D) extended-value sanity (QtyOnHand x cost) + by-location, project-scoped, for each candidate.

READ-ONLY. Run:
    python console_diag_inventory_cost2.py                 # projects 192085, 220154
    python console_diag_inventory_cost2.py 210065
Paste the WHOLE output.
"""

import sys

NUMERIC = {"money", "smallmoney", "decimal", "numeric", "float", "real", "int", "bigint",
           "smallint", "tinyint"}
COST_HINTS = ("cost", "price", "value", "unit")
COST_ANTI = ("date", "qty", "quantity", "percent", "pct", "flag", "code", "name", "id",
             "pricebook", "pricelist", "log", "changelog")


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


def cost_cols(cols):
    out = []
    for n, t in cols:
        nl = n.lower()
        if t.lower() in NUMERIC and any(h in nl for h in COST_HINTS) \
                and not any(a in nl for a in COST_ANTI):
            out.append(n)
    return out


def main():
    args = [a for a in sys.argv[1:] if a.isdigit()]
    samples = [int(a) for a in args] if args else [192085, 220154]
    conn = eto_connect()
    cur = conn.cursor()
    print(f"Sample projects: {samples}")
    try:
        # ── A. locate the item master (whatever carries ItemCompanyID) + cost ──
        rule("A. ITEM MASTER — every table/view that carries ItemCompanyID, flag cost cols")
        run(cur, "A1. objects with an ItemCompanyID column",
            "SELECT TABLE_NAME FROM INFORMATION_SCHEMA.COLUMNS "
            "WHERE COLUMN_NAME = 'ItemCompanyID' ORDER BY TABLE_NAME", max_rows=60)
        # for a base item table if present, show cost-ish columns
        for cand in ("tblItems", "tblItem", "tblCompanyItems", "tblInventoryItems",
                     "tblItemMaster", "tblItemDetail", "tblItemDetails", "vwItems"):
            cols = columns_of(cur, cand)
            if not cols:
                continue
            ccs = cost_cols(cols)
            print(f"\n  {cand}: cost candidates = {ccs or '(none)'}  ; has ItemCompanyID="
                  f"{has_col(cols, 'ItemCompanyID')}")
            if ccs and has_col(cols, "ItemCompanyID"):
                sel = ", ".join(f"[{c}]" for c in (["ItemCompanyID", "ItemID"] + ccs
                                                   if has_col(cols, "ItemID")
                                                   else ["ItemCompanyID"] + ccs))
                run(cur, f"A/{cand} sample (item + cost cols)",
                    f"SELECT TOP 15 {sel} FROM dbo.{cand} WHERE {ccs[0]} > 0 ORDER BY {ccs[0]} DESC")

        # ── B. inventory price logs (carrying cost) ───────────────────────────
        rule("B. INVENTORY PRICE LOGS — purchase-price / pull-price per item (latest = carrying cost)")
        for t in ("tblInventoryDetailsPurchasePriceChangeLog",
                  "tblInventoryPullDetailsPullPriceChangeLog"):
            cols = columns_of(cur, t)
            if not cols:
                print(f"\n  {t}: (not found)")
                continue
            print(f"\n  {t} ({len(cols)} cols):")
            for n, ty in cols:
                print(f"    {n} : {ty}")
            # try a latest-per-item sample if it has an item + price + date
            idc = next((c for c in ("ItemID", "InventoryID", "InventoryDetailID")
                        if has_col(cols, c)), None)
            prc = next((c for c, _ in cols if any(h in c.lower() for h in ("price", "cost"))
                        and c.lower() not in ("pricechangelogid",)), None)
            dtc = next((c for c, ty in cols if ty.lower() in ("datetime", "date")), None)
            if idc and prc:
                order = f"ORDER BY {dtc} DESC" if dtc else ""
                run(cur, f"B/{t} — sample rows ({idc}, {prc}{', '+dtc if dtc else ''})",
                    f"SELECT TOP 15 [{idc}], [{prc}]" + (f", [{dtc}]" if dtc else "") +
                    f" FROM dbo.{t} {order}")

        # also: base tables named like inventory-detail / inventory-pull that may hold a unit cost
        rule("B2. tables named like InventoryDetail / InventoryPull — any that carry a unit cost")
        run(cur, "B2a. catalogue",
            "SELECT TABLE_NAME, TABLE_TYPE FROM INFORMATION_SCHEMA.TABLES "
            "WHERE TABLE_NAME LIKE '%InventoryDetail%' OR TABLE_NAME LIKE '%InventoryPull%' "
            "OR TABLE_NAME LIKE '%InventoryDetails%' ORDER BY TABLE_NAME", max_rows=40)

        # ── C. disambiguate PurchasePrice vs ExtendedPrice, derive correct unit ─
        rule("C. PO PRICE — is PurchasePrice unit or line-total? then a CORRECT per-item unit cost")
        pod = columns_of(cur, "vwPurchaseOrderDetails")
        datec = next((c for c, ty in pod if ty.lower() in ("datetime", "date")
                      and any(h in c.lower() for h in ("date", "order", "po"))), None)
        run(cur, "C1. raw sample — see if ExtendedPrice ≈ PurchasePrice × PurchaseQty",
            "SELECT TOP 15 ItemID, PurchaseQty, PurchasePrice, ExtendedPrice "
            "FROM dbo.vwPurchaseOrderDetails WHERE PurchaseQty > 0 AND ExtendedPrice > 0 "
            "ORDER BY ExtendedPrice DESC")
        run(cur, "C2. weighted-avg unit = SUM(ExtendedPrice)/SUM(PurchaseQty) per item (sample)",
            "SELECT TOP 20 ItemID, "
            "SUM(CAST(ExtendedPrice AS float)) / NULLIF(SUM(CAST(PurchaseQty AS float)),0) AS wavg_unit, "
            "AVG(CAST(PurchasePrice AS float)) AS avg_purchaseprice, COUNT(*) AS lines "
            "FROM dbo.vwPurchaseOrderDetails WHERE PurchaseQty > 0 GROUP BY ItemID "
            "ORDER BY lines DESC")
        if datec:
            print(f"\n  (PO date column detected for 'last price': {datec})")

        # ── D. extended-value sanity per project (weighted-avg PO unit cost) ──
        rule("D. EXTENDED-VALUE SANITY — QtyOnHand × weighted-avg PO unit cost, project-scoped")
        cost_cte = ("(SELECT ItemID, SUM(CAST(ExtendedPrice AS float)) / "
                    "NULLIF(SUM(CAST(PurchaseQty AS float)),0) AS unit "
                    "FROM dbo.vwPurchaseOrderDetails WHERE PurchaseQty > 0 GROUP BY ItemID) c")
        for proj in samples:
            run(cur, f"D/{proj}: total on-hand value (weighted-avg PO cost)",
                "SELECT COUNT(*) AS lines, COUNT(DISTINCT v.ItemID) AS items, "
                "SUM(v.QtyOnHand * c.unit) AS ext_value, "
                "SUM(CASE WHEN c.unit IS NULL THEN 1 ELSE 0 END) AS lines_missing_cost "
                "FROM (SELECT DISTINCT ProjectID, ItemID FROM dbo.vwPurchaseOrderDetails "
                "      WHERE ProjectID = ?) p "
                "JOIN dbo.vwInventory v ON v.ItemID = p.ItemID "
                f"LEFT JOIN {cost_cte} ON c.ItemID = v.ItemID "
                "WHERE v.QtyOnHand > 0", (proj,), max_rows=5)
            run(cur, f"D/{proj}: top lines by ext value",
                "SELECT TOP 12 v.ItemCompanyID, v.ItemDescription, v.LocationName, "
                "v.QtyOnHand, c.unit, v.QtyOnHand * c.unit AS ext "
                "FROM (SELECT DISTINCT ProjectID, ItemID FROM dbo.vwPurchaseOrderDetails "
                "      WHERE ProjectID = ?) p "
                "JOIN dbo.vwInventory v ON v.ItemID = p.ItemID "
                f"LEFT JOIN {cost_cte} ON c.ItemID = v.ItemID "
                "WHERE v.QtyOnHand > 0 ORDER BY ext DESC", (proj,))
        run(cur, f"D/{samples[0]}: by-location rollup (weighted-avg PO cost)",
            "SELECT v.LocationName, COUNT(*) AS lines, COUNT(DISTINCT v.ItemID) AS items, "
            "SUM(v.QtyOnHand * c.unit) AS value "
            "FROM (SELECT DISTINCT ProjectID, ItemID FROM dbo.vwPurchaseOrderDetails "
            "      WHERE ProjectID = ?) p "
            "JOIN dbo.vwInventory v ON v.ItemID = p.ItemID "
            f"LEFT JOIN {cost_cte} ON c.ItemID = v.ItemID "
            "WHERE v.QtyOnHand > 0 GROUP BY v.LocationName ORDER BY value DESC", (samples[0],))

    finally:
        conn.close()
    print("\nDone. Decision it drives:")
    print("  • A: is there an item master with a stored unit cost? If yes → simplest, use it.")
    print("  • B: does the inventory price log give a clean latest carrying cost per item?")
    print("  • C1: if ExtendedPrice ≈ PurchasePrice×PurchaseQty, PurchasePrice is UNIT — use it")
    print("    directly (r1's /qty was the bug). C2 weighted-avg is the robust basis.")
    print("  • D: which basis yields believable on-hand $ (and how many lines lack a cost).")


if __name__ == "__main__":
    main()
