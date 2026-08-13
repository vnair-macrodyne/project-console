"""
console_diag_required_qty.py — where does a project's REQUIRED item quantity live? (2026-08-13)

The Inventory view is being reframed for manufacturing: instead of shared on-hand/bin, show the
QUANTITY REQUIRED BY THE PROJECT per item (coverage: Required · On-hand · Short · Value). Two
candidate ETO sources for "required":
  (1) the engineered BOM / product structure  (design demand — how many the build calls for)
  (2) the inventory-pull requirement           (that demand allocated to stock, w/ fulfilled split)
This probe finds which objects carry ProjectID + ItemID + a required quantity, which are actually
POPULATED for a live project, and previews the coverage join against vwInventory on-hand.

READ-ONLY. Run:  python console_diag_required_qty.py [projectID]   (default 240040) → paste output.
"""
import sys

HINTS = {
    "qty":      ("qty", "quantity"),
    "required": ("required", "require", "demand", "need"),
    "fulfilled": ("fulfil", "fulfill", "pulled", "issued", "allocat", "reserved", "received"),
    "onhand":   ("onhand", "on_hand"),
    "project":  ("projectid",),
    "item":     ("itemid",),
    "spec":     ("specid",),
}
CANDIDATES = ["vwEngBOM", "vwEngProductStructure", "tblEngProductStructure",
              "vwInventoryUnfulfilledPulls", "vwInventoryUnfulfilledPulls_Slim",
              "tblInventoryPullDetails", "vwCostingInventoryPullsDetailed",
              "vwPurchasingDemand", "vwInventoryHolding"]


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


def columns_of(cur, name):
    cur.execute("SELECT COLUMN_NAME, DATA_TYPE FROM INFORMATION_SCHEMA.COLUMNS "
                "WHERE TABLE_NAME = ? ORDER BY ORDINAL_POSITION", (name,))
    return [(r[0], r[1]) for r in cur.fetchall()]


def flags(name):
    nl = name.lower()
    return [tag for tag, hs in HINTS.items() if any(h in nl for h in hs)]


def has(cols, want):
    return any(n.lower() == want.lower() for n, _ in cols)


def main():
    pid = 240040
    if len(sys.argv) > 1:
        try:
            pid = int(sys.argv[1])
        except ValueError:
            pass
    conn = eto_connect()
    cur = conn.cursor()
    print(f"Sample project: {pid}")
    try:
        # ── A. which candidates carry ProjectID + ItemID + a required qty? ───────
        rule("A. CANDIDATE OBJECTS — columns tagged (project ★ item ◆ qty/required)")
        present = {}
        for obj in CANDIDATES:
            cols = columns_of(cur, obj)
            if not cols:
                print(f"\n  {obj}: (not found)")
                continue
            present[obj] = cols
            has_pid = has(cols, "ProjectID")
            print(f"\n  {obj} ({len(cols)} cols){'   [has ProjectID]' if has_pid else ''}:")
            for n, t in cols:
                tg = flags(n)
                mark = ("   " + " ".join(tg)) if tg else ""
                print(f"    {n} : {t}{mark}")

        # ── B. per-project ROW COUNTS — which sources are actually populated? ────
        rule(f"B. POPULATION for project {pid} (row counts per candidate that has ProjectID)")
        for obj, cols in present.items():
            if has(cols, "ProjectID"):
                run(cur, f"B/{obj} — rows for {pid}",
                    f"SELECT COUNT(*) AS rows_ FROM dbo.{obj} WHERE ProjectID = {pid}")

        # ── C. sample REQUIRED qty per item from each populated source ───────────
        rule(f"C. SAMPLE required-qty rows for {pid} (eyeball which is the real demand)")
        for obj in ("vwEngBOM", "vwEngProductStructure", "vwInventoryUnfulfilledPulls",
                    "vwInventoryUnfulfilledPulls_Slim", "tblInventoryPullDetails",
                    "vwPurchasingDemand"):
            if obj in present and has(present[obj], "ProjectID"):
                run(cur, f"C/{obj} — first rows for {pid}",
                    f"SELECT TOP 20 * FROM dbo.{obj} WHERE ProjectID = {pid}", max_rows=20)

        # ── D. coverage preview — required (unfulfilled pulls) vs on-hand ────────
        rule(f"D. COVERAGE PREVIEW for {pid} — required vs shared on-hand (if pulls are populated)")
        if "vwInventoryUnfulfilledPulls" in present and has(present["vwInventoryUnfulfilledPulls"], "ProjectID"):
            run(cur, "D1. unfulfilled-pull required qty joined to vwInventory on-hand",
                "SELECT TOP 30 up.ProjectID, up.ItemID, inv.ItemCompanyID AS ItemNo, "
                "       inv.ItemDescription AS Descr, inv.QtyOnHand AS OnHand, "
                "       inv.LocationName AS Location, inv.BinLabel AS Bin "
                "FROM dbo.vwInventoryUnfulfilledPulls up "
                "LEFT JOIN dbo.vwInventory inv ON inv.ItemID = up.ItemID "
                f"WHERE up.ProjectID = {pid} ORDER BY up.ItemID", max_rows=30)
    finally:
        conn.close()
    print("\nDone. Paste the whole output. Reading it:\n"
          "  • A = which objects carry ProjectID + ItemID + a required/qty column.\n"
          "  • B = row counts for the project → which sources are actually POPULATED (some ETO\n"
          "    tables come back empty, like the ship dates did).\n"
          "  • C = the real shape/values of 'required qty' from each — so we pick BOM (design\n"
          "    demand) vs inventory-pull requirement (with fulfilled/unfulfilled split).\n"
          "  • D = a first look at the coverage view (required vs on-hand) we'll build.\n"
          "Tell me which source is the authoritative 'quantity required' and I'll build the "
          "coverage report (Required · On-hand · Short · Value, bin last).")


if __name__ == "__main__":
    main()
