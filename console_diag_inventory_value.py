"""
console_diag_inventory_value.py — discover ETO's item unit-cost source for on-hand VALUE (2026-08-06).

GOAL: extend the project-scoped "Item Location" report into an Inventory VALUE view =
on-hand value (QtyOnHand x unit cost) + a by-location summary, scoped to selected projects.
vwInventory carries quantities (QtyOnHand, QtyMinRequired, MaximumQuantity, RecommendedQuantity)
but NO obvious unit-cost column, so this maps WHERE ETO holds item cost:

  (1) a cost/value column on vwInventory / tblInventory itself,
  (2) a standard/average/last cost on the item master (tblItem/vwItem/...),
  (3) a PO-derived cost (weighted-avg unit price from received PO lines),

and then SANITY-CHECKS each candidate by computing QtyOnHand x cost for a couple of sample
projects' on-hand items — so we pick the source that yields sensible extended values and a
sensible by-location rollup.

READ-ONLY. No writes, no schema change. Run:

    python console_diag_inventory_value.py      # uses tracked project ids
    python console_diag_inventory_value.py 240154 230219   # or pass explicit project ids

Paste the WHOLE output back.
"""

import sys

# ── objects we look at ───────────────────────────────────────────────────────
INV_OBJECTS = ["vwInventory", "tblInventory"]
ITEM_OBJECTS = ["tblItem", "tblItems", "vwItem", "vwItems", "vwItemMaster",
                "tblInventoryItem", "vwInventoryItem", "tblPart", "vwPart", "tblParts"]
# hints
COST_HINTS = ("cost", "price", "value", "unitprice", "unitcost", "stdcost", "avgcost",
              "lastcost", "standardcost", "averagecost", "matlcost", "materialcost")
# columns to EXCLUDE from cost detection (dates/ids/qty that contain a hint substring by accident)
COST_ANTIHINTS = ("date", "id", "qty", "quantity", "percent", "pct", "flag", "code", "name",
                  "pricebook", "pricelist")
NUMERIC_TYPES = {"money", "smallmoney", "decimal", "numeric", "float", "real", "int", "bigint",
                 "smallint", "tinyint"}


def eto_connect():
    """Same connection path the other console_diag_*.py scripts use."""
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


def tracked_ids(max_n=400):
    try:
        from console.infra.connections import console_connection
        c = console_connection()
        cur = c.cursor()
        cur.execute("SELECT DISTINCT ProjectID FROM Reporting.vw_Console_BudgetCurrent "
                    "ORDER BY ProjectID")
        ids = [int(r[0]) for r in cur.fetchall()][:max_n]
        c.close()
        return ids
    except Exception as e:
        print(f"  [note] no tracked ids ({type(e).__name__}: {e})")
        return []


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


def columns_of(cur, name):
    try:
        cur.execute("SELECT COLUMN_NAME, DATA_TYPE FROM INFORMATION_SCHEMA.COLUMNS "
                    "WHERE TABLE_NAME = ? ORDER BY ORDINAL_POSITION", (name,))
        return [(r[0], r[1]) for r in cur.fetchall()]
    except Exception:
        return []


def is_cost_col(name, dtype):
    nl = name.lower()
    if dtype.lower() not in NUMERIC_TYPES:
        return False
    if not any(h in nl for h in COST_HINTS):
        return False
    if any(a in nl for a in COST_ANTIHINTS):
        return False
    return True


def cost_cols(cols):
    return [n for n, t in cols if is_cost_col(n, t)]


def has_col(cols, name):
    return any(c[0].lower() == name.lower() for c in cols)


def main():
    args = [a for a in sys.argv[1:] if a.isdigit()]
    conn = eto_connect()
    cur = conn.cursor()

    ids = [int(a) for a in args] if args else tracked_ids()
    samples = ids[:2] if ids else [240154]
    print(f"Sample project(s) for value sanity-check: {samples}")

    try:
        # ── A. objects named like cost / value / valuation ────────────────────
        rule("A. OBJECTS NAMED LIKE cost / value / valuation / price")
        run(cur, "A1. tables & views named like cost/value/valuation/price",
            "SELECT TABLE_NAME, TABLE_TYPE FROM INFORMATION_SCHEMA.TABLES "
            "WHERE TABLE_NAME LIKE '%Cost%' OR TABLE_NAME LIKE '%Value%' "
            "OR TABLE_NAME LIKE '%Valuation%' OR TABLE_NAME LIKE '%Price%' "
            "ORDER BY TABLE_NAME", max_rows=80)

        # ── B. columns of inventory + item-master objects (flag cost cols) ────
        rule("B. COLUMNS OF INVENTORY & ITEM-MASTER OBJECTS ($ = numeric cost/price/value)")
        existing = {}
        inv_cost = {}     # object -> [cost col names]
        for name in INV_OBJECTS + ITEM_OBJECTS:
            cols = columns_of(cur, name)
            if not cols:
                continue
            existing[name] = cols
            ccs = cost_cols(cols)
            inv_cost[name] = ccs
            print(f"\n  {name} ({len(cols)} cols) — cost candidates: "
                  f"{', '.join(ccs) or '(none)'}")
            for n, t in cols:
                mark = " $" if is_cost_col(n, t) else ""
                print(f"    {n} : {t}{mark}")
        if not existing:
            print("  (none of the candidate objects exist — check A1 for real names)")

        # ── C. vwInventory sample showing on-hand + any cost columns ──────────
        rule("C. vwInventory SAMPLE (item + location + on-hand + cost candidates)")
        inv_cols = existing.get("vwInventory", [])
        inv_ccs = inv_cost.get("vwInventory", [])
        if inv_cols:
            base = ["ItemCompanyID", "ItemDescription", "LocationName", "QtyOnHand"]
            base = [c for c in base if has_col(inv_cols, c)]
            sel = base + inv_ccs
            collist = ", ".join(f"[{c}]" for c in sel) if sel else "*"
            run(cur, "C1. vwInventory rows with on-hand > 0",
                f"SELECT TOP 15 {collist} FROM dbo.vwInventory "
                f"WHERE QtyOnHand > 0 ORDER BY QtyOnHand DESC")
        else:
            print("  vwInventory not found — cannot sample.")

        # ── D. item-master cost sample (for the objects that carry cost) ──────
        rule("D. ITEM-MASTER COST SAMPLE (standard/average/last cost per item)")
        for name in ITEM_OBJECTS:
            cols = existing.get(name)
            if not cols:
                continue
            ccs = inv_cost.get(name, [])
            if not ccs:
                continue
            idcol = next((c for c in ("ItemID", "ItemCompanyID", "ItemNo", "PartID", "PartNo")
                          if has_col(cols, c)), None)
            desc = next((c for c in ("ItemDescription", "Description", "ItemName")
                         if has_col(cols, c)), None)
            sel = [c for c in (idcol, desc) if c] + ccs
            collist = ", ".join(f"[{c}]" for c in sel)
            run(cur, f"D/{name} — cost columns sample",
                f"SELECT TOP 15 {collist} FROM dbo.{name} ORDER BY {ccs[0]} DESC")

        # ── E. PO-derived cost (weighted-avg unit price from PO lines) ────────
        rule("E. PO-DERIVED UNIT COST (fallback: from vwPurchaseOrderDetails)")
        pod_cols = columns_of(cur, "vwPurchaseOrderDetails")
        pod_ccs = cost_cols(pod_cols)
        print(f"\n  vwPurchaseOrderDetails cost candidates: {', '.join(pod_ccs) or '(none)'}")
        # prefer an explicit unit-price/unit-cost column; else a total we can divide by qty
        unit = next((c for c in pod_ccs if "unit" in c.lower()), None)
        qtycol = next((c for c in ("PurchaseQty", "OrderQty", "Received", "Quantity")
                       if has_col(pod_cols, c)), None)
        if unit:
            run(cur, f"E1. weighted-avg unit price per item (via {unit}), sample project "
                     f"{samples[0]}",
                f"SELECT TOP 20 ItemID, MAX(ItemDescription) AS descr, "
                f"AVG(CAST([{unit}] AS float)) AS avg_unit, MAX([{unit}]) AS last_unit, "
                f"COUNT(*) AS lines "
                f"FROM dbo.vwPurchaseOrderDetails "
                f"WHERE ProjectID = ? AND [{unit}] > 0 GROUP BY ItemID ORDER BY lines DESC",
                (samples[0],))
        elif pod_ccs and qtycol:
            tot = pod_ccs[0]
            run(cur, f"E1. derived unit = {tot}/{qtycol} per item, sample project {samples[0]}",
                f"SELECT TOP 20 ItemID, MAX(ItemDescription) AS descr, "
                f"SUM(CAST([{tot}] AS float)) / NULLIF(SUM(CAST([{qtycol}] AS float)),0) AS unit, "
                f"COUNT(*) AS lines "
                f"FROM dbo.vwPurchaseOrderDetails "
                f"WHERE ProjectID = ? GROUP BY ItemID ORDER BY lines DESC", (samples[0],))
        else:
            print("  (no usable price/qty columns on vwPurchaseOrderDetails — see B/A output)")

        # ── F. EXTENDED-VALUE SANITY CHECK per sample project ─────────────────
        rule("F. EXTENDED-VALUE SANITY CHECK  (QtyOnHand x cost, project-scoped like item_location)")
        if inv_cols and has_col(inv_cols, "ItemID") and has_col(inv_cols, "QtyOnHand"):
            if not inv_ccs:
                print("  vwInventory has NO cost column — value must come from item-master (D) "
                      "or PO-derived (E); join those in a follow-up once the source is picked.")
            for sample in samples:
                print(f"\n  ---- project {sample} ----")
                # total inventory value per candidate cost column
                for cc in inv_ccs:
                    run(cur, f"F/{sample}: total on-hand value via vwInventory.[{cc}]",
                        "SELECT COUNT(*) AS lines, COUNT(DISTINCT v.ItemID) AS items, "
                        f"SUM(v.QtyOnHand * v.[{cc}]) AS ext_value "
                        "FROM (SELECT DISTINCT ProjectID, ItemID "
                        "      FROM dbo.vwPurchaseOrderDetails WHERE ProjectID = ?) p "
                        "JOIN dbo.vwInventory v ON v.ItemID = p.ItemID "
                        "WHERE v.QtyOnHand > 0", (sample,), max_rows=5)
                # top lines by extended value for the first candidate
                if inv_ccs:
                    cc0 = inv_ccs[0]
                    idcol = "ItemCompanyID" if has_col(inv_cols, "ItemCompanyID") else "ItemID"
                    loc = "LocationName" if has_col(inv_cols, "LocationName") else "InventoryLocation"
                    run(cur, f"F/{sample}: top lines by ext value (via [{cc0}])",
                        f"SELECT TOP 12 v.[{idcol}] AS item, v.ItemDescription AS descr, "
                        f"v.[{loc}] AS loc, v.QtyOnHand AS onhand, v.[{cc0}] AS unit, "
                        f"v.QtyOnHand * v.[{cc0}] AS ext "
                        "FROM (SELECT DISTINCT ProjectID, ItemID "
                        "      FROM dbo.vwPurchaseOrderDetails WHERE ProjectID = ?) p "
                        "JOIN dbo.vwInventory v ON v.ItemID = p.ItemID "
                        f"WHERE v.QtyOnHand > 0 ORDER BY ext DESC", (sample,))
        else:
            print("  vwInventory missing ItemID/QtyOnHand — cannot run the project-scoped check.")

        # ── G. BY-LOCATION ROLLUP sanity (the second chosen lens) ─────────────
        rule("G. BY-LOCATION ROLLUP  (per-location lines / items / value, sample project)")
        if inv_cols and inv_ccs and has_col(inv_cols, "ItemID"):
            cc0 = inv_ccs[0]
            loc = "LocationName" if has_col(inv_cols, "LocationName") else "InventoryLocation"
            run(cur, f"G/{samples[0]}: rollup by {loc} (value via [{cc0}])",
                f"SELECT v.[{loc}] AS location, COUNT(*) AS lines, "
                "COUNT(DISTINCT v.ItemID) AS items, "
                f"SUM(v.QtyOnHand * v.[{cc0}]) AS value "
                "FROM (SELECT DISTINCT ProjectID, ItemID "
                "      FROM dbo.vwPurchaseOrderDetails WHERE ProjectID = ?) p "
                "JOIN dbo.vwInventory v ON v.ItemID = p.ItemID "
                f"WHERE v.QtyOnHand > 0 GROUP BY v.[{loc}] ORDER BY value DESC", (samples[0],))
        else:
            print("  (need a vwInventory cost column to roll value by location — pick the source "
                  "from B/C/D/E first, then re-run)")

    finally:
        conn.close()

    print("\nDone. Paste the whole output. What to look for:")
    print("  • B/C: does vwInventory carry a usable unit-cost column ($)? If yes, that's the")
    print("    simplest source — F shows whether QtyOnHand x it gives sane project values.")
    print("  • D: if not, which item-master cost (standard vs average vs last) is populated &")
    print("    sensible — we join it by ItemID.")
    print("  • E: PO-derived unit cost as a fallback / cross-check against D.")
    print("  • F: which candidate yields believable extended values (not 0, not absurd).")
    print("  • G: confirms the by-location rollup works off the chosen cost.")


if __name__ == "__main__":
    main()
