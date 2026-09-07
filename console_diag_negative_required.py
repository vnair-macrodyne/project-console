"""
console_diag_negative_required.py — WHY is "Required" negative on the Inventory Coverage /
Allocation reports?  (2026-09-07)   READ-ONLY. Nothing is written.

"Required" = SUM(PullQty) per project × item from dbo.vwInventoryUnfulfilledPulls (ETO's
outstanding inventory-pull requirement). Some items sum to a NEGATIVE. This probe finds those
and dumps the RAW underlying rows so we can see the real cause (a negative pull line / return /
over-fulfilment / correction) instead of inferring it — then we decide how the reports should
handle it.

Run where the other console_diag_*.py scripts run (ETO reachable):
    python console_diag_negative_required.py
Paste the WHOLE output back.
"""
import sys

VIEW = "vwInventoryUnfulfilledPulls"
PULL_DETAIL_CANDIDATES = ["tblInventoryPullDetails", "vwCostingInventoryPullsDetailed",
                          "vwInventoryPulls", "tblInventoryPulls"]
SAMPLE_KEYS = 6      # how many negative (project,item) keys to dump raw rows for


def eto_connect():
    try:
        from console_store import eto_connection
        return eto_connection()
    except Exception:
        import os, pyodbc
        from console_config import TENANT
        cs = (f"Driver={{ODBC Driver 17 for SQL Server}};Server={TENANT.eto_server};"
              f"Database={TENANT.eto_database};")
        cs += ("Trusted_Connection=yes;" if TENANT.use_windows_auth
               else f"UID={os.environ.get('ETO_USER')};PWD={os.environ.get('ETO_PWD')};")
        return pyodbc.connect(cs)


def rule(t):
    print("\n" + "=" * 80 + f"\n{t}\n" + "=" * 80)


def run(cur, label, sql, params=None):
    print(f"\n-- {label}")
    print(f"   {sql.strip()}")
    try:
        cur.execute(sql, params) if params else cur.execute(sql)
        cols = [d[0] for d in cur.description]
        rows = cur.fetchall()
        print("   " + " | ".join(cols))
        for r in rows:
            print("   " + " | ".join("" if v is None else str(v) for v in r))
        print(f"   ({len(rows)} row(s))")
        return cols, rows
    except Exception as e:
        print(f"   !! {type(e).__name__}: {e}")
        return [], []


def cols_of(cur, table):
    try:
        cur.execute("SELECT COLUMN_NAME, DATA_TYPE FROM INFORMATION_SCHEMA.COLUMNS "
                    "WHERE TABLE_NAME = ? ORDER BY ORDINAL_POSITION", (table,))
        return [(r[0], r[1]) for r in cur.fetchall()]
    except Exception as e:
        print(f"   !! columns of {table}: {e}")
        return []


def main():
    eto = eto_connect()
    cur = eto.cursor()

    # ── A. What columns does the view actually carry? ────────────────────────────
    rule(f"A. COLUMNS of dbo.{VIEW}")
    vcols = cols_of(cur, VIEW)
    for name, dt in vcols:
        print(f"   {name:32} {dt}")
    vcolset = {c.lower() for c, _ in vcols}
    has = lambda c: c.lower() in vcolset
    # figure out the item-number column name (ItemCompanyID in the report)
    item_no = "ItemCompanyID" if has("ItemCompanyID") else ("ItemNumber" if has("ItemNumber") else "ItemID")

    # ── B. Which (project, item, location) groups sum to a NEGATIVE required? ─────
    rule("B. NEGATIVE 'Required' GROUPS  (SUM(PullQty) < 0) — the report's grouping")
    run(cur, "B0. count + magnitude of negative-required groups",
        f"""SELECT COUNT(*) AS NegGroups,
                   SUM(NetPull) AS TotalNetPullNeg
            FROM (SELECT up.ProjectID, up.{item_no} AS ItemNo, up.InventoryLocation,
                         SUM(CAST(up.PullQty AS float)) AS NetPull
                  FROM dbo.{VIEW} up
                  GROUP BY up.ProjectID, up.{item_no}, up.InventoryLocation
                  HAVING SUM(CAST(up.PullQty AS float)) < 0) t""")
    _, negrows = run(cur, f"B1. worst {SAMPLE_KEYS*4} negative groups",
        f"""SELECT TOP {SAMPLE_KEYS*4}
                   up.ProjectID, up.{item_no} AS ItemNo, MAX(up.ItemDescription) AS Descr,
                   up.InventoryLocation AS LocID,
                   COUNT(*) AS Lines,
                   SUM(CAST(up.PullQty AS float)) AS NetPull,
                   MAX(CAST(up.QtyOnHand AS float)) AS OnHand,
                   SUM(CAST(up.TotalCost AS float)) AS NetValue
            FROM dbo.{VIEW} up
            GROUP BY up.ProjectID, up.{item_no}, up.InventoryLocation
            HAVING SUM(CAST(up.PullQty AS float)) < 0
            ORDER BY SUM(CAST(up.PullQty AS float)) ASC""")

    # also: are there any individual NEGATIVE PullQty lines at all?
    run(cur, "B2. do individual negative PullQty LINES exist? (count + min)",
        f"SELECT SUM(CASE WHEN CAST(PullQty AS float) < 0 THEN 1 ELSE 0 END) AS NegLines, "
        f"COUNT(*) AS TotalLines, MIN(CAST(PullQty AS float)) AS MinLine, "
        f"MAX(CAST(PullQty AS float)) AS MaxLine FROM dbo.{VIEW}")

    # ── C. RAW rows behind a few negative keys — see the actual line composition ──
    rule("C. RAW LINES behind the worst negative keys (SELECT * from the view)")
    keys = []
    for r in negrows:
        keys.append((r[0], r[1]))   # ProjectID, ItemNo
        if len(keys) >= SAMPLE_KEYS:
            break
    if not keys:
        print("   (no negative groups found — nothing to dump)")
    for pid, itemno in keys:
        run(cur, f"C. all view rows for Project {pid} × Item {itemno}",
            f"SELECT * FROM dbo.{VIEW} WHERE ProjectID = ? AND {item_no} = ?", (pid, itemno))

    # ── D. Cross-check against the full pull-detail source (fulfilled/returns) ────
    rule("D. FULL PULL DETAIL for one negative key — look for returns / fulfilled / over-issue")
    if keys:
        pid, itemno = keys[0]
        # find which detail table/view exists and carries ProjectID + a pull qty + fulfilled flag
        for t in PULL_DETAIL_CANDIDATES:
            dc = cols_of(cur, t)
            if not dc:
                continue
            names = [c for c, _ in dc]
            print(f"\n   >>> {t} columns: {', '.join(names)}")
            dcl = {c.lower() for c in names}
            if "projectid" in dcl:
                run(cur, f"D. {t} rows for Project {pid} (item filter best-effort)",
                    f"SELECT TOP 60 * FROM dbo.{t} WHERE ProjectID = ?", (pid,))
    else:
        print("   (no negative key to cross-check)")

    eto.close()
    print("\nDONE — paste everything above.")


if __name__ == "__main__":
    main()
