"""
console_diag_item_location.py — map ETO's inventory on-hand-by-item-and-location (2026-08-03).

GOAL: an "Item Location" report = on-hand quantity by item and location, scoped to selected
projects (where a project's stocked material is physically sitting). We know PO lines carry
vwPurchaseOrderDetails.DestInventoryLoc and there's an inventory-pull cost stream, but we need
to map: (1) the LOCATION master DestInventoryLoc points at, (2) the ON-HAND table
(item + location + qty), and (3) how on-hand inventory ties back to a PROJECT.

READ-ONLY. Run:  python console_diag_item_location.py   → paste the whole output.
"""

# Curated candidates — we print columns for whichever actually exist.
CANDIDATES = [
    "tblInventory", "tblInventoryLocation", "tblInventoryLocations", "tblInventoryDetail",
    "tblItemInventory", "tblItemLocation", "tblStock", "tblBin",
    "tlkpInventoryLocation", "tlkpInventoryLocations", "tlkpLocation", "tblLocation",
    "vwInventory", "vwInventoryLocations", "vwInventoryOnHand", "vwInventoryByLocation",
    "vwItemInventory", "vwInventoryItems",
    "tblItem", "tblItems", "vwItem", "vwItems",
]
QTY_HINTS = ("qty", "onhand", "quantity", "stock", "balance", "count")
LOC_HINTS = ("location", "loc", "bin", "warehouse", "shelf")
PROJ_HINTS = ("projectid", "specid")


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


def tracked_ids(max_n=400):
    try:
        from console.infra.connections import console_connection
        c = console_connection()
        cur = c.cursor()
        cur.execute("SELECT DISTINCT ProjectID FROM Reporting.vw_Console_BudgetCurrent ORDER BY ProjectID")
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
    cur.execute("SELECT COLUMN_NAME, DATA_TYPE FROM INFORMATION_SCHEMA.COLUMNS "
                "WHERE TABLE_NAME = ? ORDER BY ORDINAL_POSITION", (name,))
    return [(r[0], r[1]) for r in cur.fetchall()]


def main():
    conn = eto_connect()
    cur = conn.cursor()
    ids = tracked_ids()
    sample = ids[0] if ids else 240154
    try:
        # ── A. catalogue of inventory / location / item objects ──────────────────
        rule("A. INVENTORY / LOCATION / ITEM OBJECTS IN ETO")
        run(cur, "A1. tables & views named like inventory/location/stock/bin/item",
            "SELECT TABLE_NAME, TABLE_TYPE FROM INFORMATION_SCHEMA.TABLES "
            "WHERE TABLE_NAME LIKE '%Inventory%' OR TABLE_NAME LIKE '%Location%' "
            "OR TABLE_NAME LIKE '%Stock%' OR TABLE_NAME LIKE '%Bin%' "
            "OR TABLE_NAME LIKE '%ItemLoc%' ORDER BY TABLE_NAME", max_rows=80)

        # ── B. columns of the candidates that exist (flag qty/loc/project cols) ───
        rule("B. COLUMNS OF CANDIDATE OBJECTS (▶ = qty, ◆ = location, ★ = project link)")
        existing = {}
        for name in CANDIDATES:
            cols = columns_of(cur, name)
            if not cols:
                continue
            existing[name] = cols
            print(f"\n  {name} ({len(cols)} cols):")
            for n, t in cols:
                nl = n.lower()
                mark = ""
                if any(h in nl for h in QTY_HINTS):
                    mark += " ▶"
                if any(h in nl for h in LOC_HINTS):
                    mark += " ◆"
                if nl in PROJ_HINTS:
                    mark += " ★"
                print(f"    {n} : {t}{mark}")
        if not existing:
            print("  (none of the curated candidates exist — rely on A1 to pick real names)")

        # ── C. the location master DestInventoryLoc points at ────────────────────
        rule("C. LOCATION MASTER (what DestInventoryLoc references)")
        run(cur, "C1. distinct DestInventoryLoc on PO lines (are they populated?)",
            "SELECT TOP 25 DestInventoryLoc, COUNT(*) AS lines "
            "FROM dbo.vwPurchaseOrderDetails WHERE DestInventoryLoc IS NOT NULL "
            "GROUP BY DestInventoryLoc ORDER BY lines DESC")
        for lk in ("tlkpInventoryLocation", "tblInventoryLocation", "tblLocation", "tlkpLocation"):
            if lk in existing:
                run(cur, f"C/{lk} — sample rows", f"SELECT TOP 20 * FROM dbo.{lk}")

        # ── D. on-hand sample from likely tables ─────────────────────────────────
        rule("D. ON-HAND SAMPLE (item + location + qty)")
        for t in ("tblInventory", "tblItemInventory", "vwInventory", "vwInventoryByLocation",
                  "vwInventoryOnHand"):
            if t in existing:
                run(cur, f"D/{t} — sample rows", f"SELECT TOP 15 * FROM dbo.{t}")

        # ── E. project linkage — for a sample project ────────────────────────────
        rule(f"E. PROJECT LINKAGE — sample project {sample}")
        run(cur, "E1. PO lines with a destination inventory location (received-into)",
            "SELECT TOP 20 pod.ProjectID, pod.ItemID, pod.ItemDescription, pod.DestInventoryLoc, "
            "pod.PurchaseQty, pod.Received "
            "FROM dbo.vwPurchaseOrderDetails pod "
            f"WHERE pod.ProjectID = {sample} AND pod.DestInventoryLoc IS NOT NULL "
            "ORDER BY pod.ItemID")
        # which candidate inventory tables actually carry a ProjectID/SpecID?
        linked = [n for n, cols in existing.items()
                  if any(c[0].lower() in PROJ_HINTS for c in cols)]
        print("\n  Inventory objects that carry a ProjectID/SpecID column:",
              ", ".join(linked) or "(none — inventory is a shared stock pool; tie via ItemID)")
    finally:
        conn.close()
    print("\nDone. Paste the whole output.\n"
          "  • A/B: the real object names + which carry qty (▶), location (◆), project (★).\n"
          "  • C: the location master (id → name/code) so the report shows readable locations.\n"
          "  • D: the on-hand table shape (item + location + qty).\n"
          "  • E: whether on-hand ties to a project directly (★) or only via the item on its POs.")


if __name__ == "__main__":
    main()
