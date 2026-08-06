"""
console_diag_movement_docs.py — map ETO objects for PACKING SLIPS + INVENTORY TRANSFERS (2026-08-06).

Two team asks:
  (1) "Packing Slip information" — shipping/receiving documents (pack slips out to customer,
      receiver slips in from suppliers) with their line items.
  (2) "Show transfers of inventory" — stock moved between locations (Macrodyne 1 / Macrodyne 2
      (Racco) / TOC) and other inventory transactions/adjustments.

This is a READ-ONLY discovery pass (same harness as the other console_diag_*.py). It maps:
  - which packing-slip / shipment / receiver objects exist and their shape,
  - which inventory-transfer / transaction / movement objects exist and their shape,
  - for each, whether it links to a PROJECT directly (ProjectID/SpecID) or only via ItemID,
  - and shows sample rows (project-scoped where a ProjectID exists) so we can see doc no.,
    item, qty, from/to location and date.

Run:  python console_diag_movement_docs.py            # tracked project ids
      python console_diag_movement_docs.py 240154     # or an explicit project id
Paste the WHOLE output back.
"""

import sys

# ── candidate objects (we only print the ones that actually exist) ────────────
SHIP_CANDIDATES = [
    "tblPackingSlip", "tblPackingSlipDetail", "tblPackSlip", "tblPackSlipDetail",
    "vwPackingSlip", "vwPackingSlipDetail", "vwPackSlip",
    "tblShipment", "tblShipmentDetail", "tblShipHeader", "tblShipDetail",
    "tblShipping", "tblShippingDetail", "vwShipment", "vwShipmentDetail",
    "vwShipping", "vwPackingList", "tblPackingList", "tblPackingListDetail",
]
RECEIVE_CANDIDATES = [
    "tblReceiver", "tblReceiverDetail", "tblReceipt", "tblReceiptDetail",
    "tblPOReceipt", "tblPOReceiptDetail", "vwReceiver", "vwReceiverDetail",
    "vwReceiving", "vwReceipt", "vwReceipts", "vwPOReceipt", "vwPOReceipts",
    "tblReceiving", "tblReceivingDetail",
]
TRANSFER_CANDIDATES = [
    "tblInventoryTransfer", "tblInventoryTransferDetail", "tblStockTransfer",
    "tblInventoryTransaction", "tblInventoryTransactions", "tblInventoryMovement",
    "tblInventoryMovements", "tblInventoryAdjustment", "tblInventoryHistory",
    "tblMaterialTransaction", "tblMaterialTransactions", "tblItemTransaction",
    "vwInventoryTransfer", "vwInventoryTransaction", "vwInventoryTransactions",
    "vwInventoryMovement", "vwInventoryMovements", "vwInventoryHistory",
    "vwMaterialTransaction", "vwStockTransfer", "vwInventoryAdjustment",
]

PROJ_HINTS = ("projectid", "specid")
ITEM_HINTS = ("itemid", "itemcompanyid", "itemno", "partid", "partno")
QTY_HINTS = ("qty", "quantity", "onhand", "shipped", "received")
LOC_HINTS = ("location", "loc", "fromloc", "toloc", "sourceloc", "destloc", "warehouse", "bin")
DATE_HINTS = ("date", "shipped", "received", "posted", "trandate", "transdate", "created")
DOC_HINTS = ("packingslip", "packslip", "packinglist", "shipno", "shipment", "shipnum",
             "receiver", "receipt", "docno", "docnum", "number", "tranno", "transno", "slipno")


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


def run(cur, label, sql, params=(), max_rows=20):
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


def flag(nl):
    m = ""
    if any(h in nl for h in QTY_HINTS):
        m += " >"       # qty
    if any(h in nl for h in LOC_HINTS):
        m += " @"       # location
    if nl in PROJ_HINTS:
        m += " *"       # project link
    if any(h in nl for h in ITEM_HINTS):
        m += " #"       # item
    if any(h in nl for h in DATE_HINTS):
        m += " ~"       # date
    if any(h in nl for h in DOC_HINTS):
        m += " !"       # document number
    return m


def has_col(cols, name):
    return any(c[0].lower() == name.lower() for c in cols)


def first_col(cols, hints):
    for n, _ in cols:
        if n.lower() in hints or any(h == n.lower() for h in hints):
            return n
    for n, _ in cols:
        if any(h in n.lower() for h in hints):
            return n
    return None


def catalogue(cur, like_terms):
    ors = " OR ".join(f"TABLE_NAME LIKE '{t}'" for t in like_terms)
    run(cur, "objects matching " + ", ".join(like_terms),
        f"SELECT TABLE_NAME, TABLE_TYPE FROM INFORMATION_SCHEMA.TABLES "
        f"WHERE {ors} ORDER BY TABLE_NAME", max_rows=80)


def profile(cur, candidates, existing):
    """Print columns (flagged) for the candidates that exist; return {name: cols}."""
    found = {}
    for name in candidates:
        cols = columns_of(cur, name)
        if not cols:
            continue
        found[name] = cols
        existing[name] = cols
        marks = []
        for n, _ in cols:
            nl = n.lower()
            if nl in PROJ_HINTS:
                marks.append("project*")
                break
        has_proj = "★ has ProjectID" if any(c[0].lower() in PROJ_HINTS for c in cols) else \
                   "(item-linked only)"
        print(f"\n  {name} ({len(cols)} cols) — {has_proj}")
        for n, t in cols:
            print(f"    {n} : {t}{flag(n.lower())}")
    return found


def sample_scoped(cur, found, sample):
    """Sample rows for each found object, project-scoped if it has a ProjectID else TOP N."""
    for name, cols in found.items():
        proj = first_col(cols, PROJ_HINTS)
        # pick a readable subset of columns to show
        wanted = []
        for hints in (DOC_HINTS, PROJ_HINTS, ITEM_HINTS, QTY_HINTS, LOC_HINTS, DATE_HINTS):
            c = first_col(cols, hints)
            if c and c not in wanted:
                wanted.append(c)
        collist = ", ".join(f"[{c}]" for c in wanted) if wanted else "*"
        if proj:
            run(cur, f"{name} — sample for project {sample} (scoped on {proj})",
                f"SELECT TOP 15 {collist} FROM dbo.{name} WHERE [{proj}] = ?", (sample,))
        else:
            run(cur, f"{name} — TOP 15 (no ProjectID; item-linked)",
                f"SELECT TOP 15 {collist} FROM dbo.{name}")


def main():
    args = [a for a in sys.argv[1:] if a.isdigit()]
    conn = eto_connect()
    cur = conn.cursor()
    ids = [int(a) for a in args] if args else tracked_ids()
    sample = ids[0] if ids else 240154
    print(f"Sample project for scoped samples: {sample}")
    existing = {}
    try:
        # ── A. catalogue ──────────────────────────────────────────────────────
        rule("A. OBJECT CATALOGUE (what exists)")
        print("\n  A1. shipping / packing")
        catalogue(cur, ["%Packing%", "%PackSlip%", "%PackingList%", "%Shipment%", "%Shipping%",
                        "%Ship%"])
        print("\n  A2. receiving")
        catalogue(cur, ["%Receiver%", "%Receiving%", "%Receipt%"])
        print("\n  A3. inventory transfer / transaction / movement")
        catalogue(cur, ["%Transfer%", "%InventoryTran%", "%InventoryMov%", "%InventoryHist%",
                        "%MaterialTran%", "%ItemTran%", "%Adjustment%", "%StockTran%"])

        # ── B. PACKING / SHIPPING objects (columns, flagged) ──────────────────
        rule("B. PACKING / SHIPPING OBJECTS  (> qty  @ location  * project  # item  ~ date  ! docno)")
        ship = profile(cur, SHIP_CANDIDATES, existing)
        if not ship:
            print("  (none of the curated shipping candidates exist — use A1 for real names)")

        # ── C. RECEIVING objects ──────────────────────────────────────────────
        rule("C. RECEIVING OBJECTS  (> qty  @ location  * project  # item  ~ date  ! docno)")
        recv = profile(cur, RECEIVE_CANDIDATES, existing)
        if not recv:
            print("  (none of the curated receiving candidates exist — note PO receipts may live "
                  "on vwPurchaseOrderDetails.Received instead)")

        # ── D. INVENTORY TRANSFER / TRANSACTION objects ───────────────────────
        rule("D. INVENTORY TRANSFER / TRANSACTION OBJECTS  (> qty  @ location  # item  ~ date  ! docno)")
        xfer = profile(cur, TRANSFER_CANDIDATES, existing)
        if not xfer:
            print("  (none of the curated transfer candidates exist — use A3 for real names)")

        # ── E. SAMPLE ROWS (project-scoped where possible) ────────────────────
        rule(f"E. SAMPLE ROWS — packing/shipping (project {sample} where a ProjectID exists)")
        sample_scoped(cur, ship, sample)
        rule(f"F. SAMPLE ROWS — receiving (project {sample} where a ProjectID exists)")
        sample_scoped(cur, recv, sample)
        rule(f"G. SAMPLE ROWS — inventory transfers/transactions (TOP 15; watch for from/to loc)")
        sample_scoped(cur, xfer, sample)

        # ── H. project-linkage summary ────────────────────────────────────────
        rule("H. PROJECT LINKAGE SUMMARY")
        direct = [n for n, cols in existing.items()
                  if any(c[0].lower() in PROJ_HINTS for c in cols)]
        itemonly = [n for n in existing if n not in direct]
        print("  Objects with a DIRECT ProjectID/SpecID (scope by project directly):")
        print("    " + (", ".join(direct) or "(none)"))
        print("  Objects with NO ProjectID (scope via ItemID on the project's POs, like Item Location):")
        print("    " + (", ".join(itemonly) or "(none)"))

    finally:
        conn.close()

    print("\nDone. Paste the whole output. What to look for:")
    print("  • A: the REAL object names (curated list is a guess; A is ground truth).")
    print("  • B/C: the packing-slip header+detail pair (doc no ! , item #, qty >, date ~) and")
    print("    whether a pack slip carries a ProjectID * or links via the order/item.")
    print("  • D/G: an inventory-transfer object with FROM-location and TO-location (@) + qty (>)")
    print("    + date (~) — that's what 'show transfers' needs.")
    print("  • H: which of these we can scope to a project directly vs via ItemID.")


if __name__ == "__main__":
    main()
