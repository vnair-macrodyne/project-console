"""
console_diag_transfers.py — confirm the inventory-TRANSFERS source before building the report
(2026-08-06).

Decision: transfers = stock moved location→location = inventory pulls where StockTransfer = 1.
Source `vwCostingInventoryPullsDetailed` carries: ProjectID, ItemID, InventoryLocation (FROM) +
LocationName (from-name), DestInventoryLoc (TO, an id), PullQty, RequiredDate/FulfilledDate,
CostingValue, StockTransfer. We need: (a) that StockTransfer=1 rows actually exist, (b) the
location master to turn DestInventoryLoc (id) into a NAME, (c) whether transfers carry a ProjectID
(scope) or are portfolio-wide.

READ-ONLY. Run:  python console_diag_transfers.py   (opt: pass project ids)
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


def main():
    args = [a for a in sys.argv[1:] if a.isdigit()]
    samples = [int(a) for a in args] if args else [192085, 220154]
    conn = eto_connect()
    cur = conn.cursor()
    try:
        # ── A. location master (id → name) ────────────────────────────────────
        rule("A. LOCATION MASTER — resolve DestInventoryLoc (id) → name")
        for lk in ("tlkpInventoryLocations", "tlkpInventoryLocation"):
            cols = columns_of(cur, lk)
            if cols:
                print(f"\n  {lk}: " + ", ".join(f"{n}:{t}" for n, t in cols))
                run(cur, f"A/{lk} rows", f"SELECT * FROM dbo.{lk}", max_rows=20)

        # ── B. do StockTransfer=1 rows exist? ─────────────────────────────────
        rule("B. STOCK TRANSFERS — do they exist, and do they carry a ProjectID?")
        run(cur, "B1. counts: all pulls vs StockTransfer=1, and how many have ProjectID>0",
            "SELECT COUNT(*) AS all_pulls, "
            "SUM(CASE WHEN StockTransfer = 1 THEN 1 ELSE 0 END) AS transfers, "
            "SUM(CASE WHEN StockTransfer = 1 AND ProjectID > 0 THEN 1 ELSE 0 END) AS transfers_with_project "
            "FROM dbo.vwCostingInventoryPullsDetailed")
        run(cur, "B2. sample transfers — FROM (LocationName) → TO (DestInventoryLoc), item, qty, value",
            "SELECT TOP 25 ProjectID, ItemCompanyID, ItemDescription, InventoryLocation AS FromLoc, "
            "LocationName AS FromName, DestInventoryLoc AS ToLocId, PullQty, "
            "FulfilledDate, RequiredDate, CostingValue "
            "FROM dbo.vwCostingInventoryPullsDetailed WHERE StockTransfer = 1 "
            "ORDER BY FulfilledDate DESC")
        run(cur, "B3. transfers resolved with destination NAME (join to master)",
            "SELECT TOP 25 t.ProjectID, t.ItemCompanyID, t.LocationName AS FromName, "
            "m.LocationName AS ToName, t.PullQty, t.FulfilledDate, t.CostingValue "
            "FROM dbo.vwCostingInventoryPullsDetailed t "
            "LEFT JOIN dbo.tlkpInventoryLocations m ON m.InventoryLocation = t.DestInventoryLoc "
            "WHERE t.StockTransfer = 1 ORDER BY t.FulfilledDate DESC")

        # ── C. project-scoped transfers ───────────────────────────────────────
        rule("C. TRANSFERS for sample projects")
        for proj in samples:
            run(cur, f"C/{proj}: StockTransfer=1 rows",
                "SELECT TOP 15 ItemCompanyID, LocationName AS FromName, DestInventoryLoc AS ToLocId, "
                "PullQty, FulfilledDate, CostingValue "
                "FROM dbo.vwCostingInventoryPullsDetailed WHERE StockTransfer = 1 AND ProjectID = ? "
                "ORDER BY FulfilledDate DESC", (proj,))

    finally:
        conn.close()
    print("\nDone. Decision it drives:")
    print("  • A: the id→name column names on tlkpInventoryLocations (for the destination join).")
    print("  • B1: whether transfers exist at all, and whether they carry a ProjectID (scope).")
    print("  • B3: confirms FROM→TO both resolve to names — the report's core rows.")
    print("  • C: whether to scope the report by project or show it portfolio-wide.")


if __name__ == "__main__":
    main()
