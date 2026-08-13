"""
console_diag_po_exc_fields.py — find ETO sources for the requested PO-Exception columns (2026-08-12).

Vijay wants the PO Exception report to carry: buyer, project#, project name, Code (machine/spec),
item, category, release date, po#, planned ship date, planned receipt date, revised receipt date,
receipt date, status, last updated, days to assembly, RFQ date, permit dates, lead time, oversized.

Several already exist; several are uncertain (category / status / last-updated / days-to-assembly /
RFQ date / permit dates / planned ship date). This probe dumps the candidate columns across the PO
tables + item master + spec, flags likely matches, and samples a few REAL open lines so we can map
each requested field to an ETO column — or prove ETO doesn't hold it (like it doesn't hold lead time).

READ-ONLY. Run:  python console_diag_po_exc_fields.py [projectID]   → paste the whole output.
"""
import sys

HINTS = {
    "category":  ("categ", "class", "commodity", "group"),
    "rfq/quote": ("rfq", "quote", "quot"),
    "permit":    ("permit",),
    "assembly":  ("assembl", "mfgbegin", "mfg"),
    "status":    ("status", "state"),
    "updated":   ("lastmod", "modif", "updat", "changed", "revdate"),
    "receipt":   ("receiv", "receipt"),
    "ship":      ("ship", "deliver"),
    "release":   ("release",),
    "lead":      ("lead",),
    "oversize":  ("oversiz", "custom7", "custom8", "custom6"),
    "date":      ("date",),
}
OBJECTS = ["vwPurchaseOrderDetails", "vwPurchaseOrderHeader", "vwPurchaseOrderDetailsDetailed",
           "tblPurchaseOrderDetails", "tblPurchaseOrderHeader", "tblEngItemMaster", "vwSpec"]


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


def run(cur, label, sql, params=(), max_rows=40):
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


def flags_for(name):
    out = []
    nl = name.lower()
    for tag, hints in HINTS.items():
        if tag == "date":
            continue
        if any(h in nl for h in hints):
            out.append(tag)
    return out


def main():
    pid = 230219
    if len(sys.argv) > 1:
        try:
            pid = int(sys.argv[1])
        except ValueError:
            pass
    conn = eto_connect()
    cur = conn.cursor()
    print(f"Sample project: {pid}")
    try:
        # ── A. columns of every candidate object, flagged to the requested fields ─
        rule("A. CANDIDATE COLUMNS (tags show which requested field a column might feed)")
        for obj in OBJECTS:
            cols = columns_of(cur, obj)
            if not cols:
                print(f"\n  {obj}: (not found)")
                continue
            print(f"\n  {obj} ({len(cols)} cols):")
            for n, t in cols:
                tags = flags_for(n)
                mark = ("   ◆ " + ",".join(tags)) if tags else ""
                print(f"    {n} : {t}{mark}")

        # ── B. a few OPEN lines with the fields we already know how to get ───────
        rule(f"B. SAMPLE OPEN PO LINES for {pid} (known fields + Code/spec + item master)")
        run(cur, "B1. open lines joined to spec + item master",
            "SELECT TOP 25 pod.ProjectID, pod.SpecID AS Code, poh.PurchaseOrderID AS PO, "
            "       pod.ItemID, pod.ItemDescription, pod.PurchaseQty, pod.Received, "
            "       CAST(pod.DateRequired AS date) AS PlannedReceipt, "
            "       CAST(pod.DateRevised AS date) AS RevisedReceipt, "
            "       CAST(poh.PurchaseDate AS date) AS Ordered "
            "FROM vwPurchaseOrderHeader poh "
            "JOIN vwPurchaseOrderDetails pod ON pod.PurchaseOrderID = poh.PurchaseOrderID "
            f"WHERE poh.PurchaseActive = 1 AND pod.ProjectID = {pid} "
            "  AND (pod.Received IS NULL OR pod.Received < pod.PurchaseQty) "
            "ORDER BY pod.SpecID, pod.ItemID")

        # ── C. actual RECEIPT date from the receiver log ─────────────────────────
        rule("C. RECEIPT DATE — vwReceiverLogSummed (actual last receipt per PO line)")
        run(cur, "C1. columns of vwReceiverLogSummed",
            "SELECT COLUMN_NAME, DATA_TYPE FROM INFORMATION_SCHEMA.COLUMNS "
            "WHERE TABLE_NAME = 'vwReceiverLogSummed' ORDER BY ORDINAL_POSITION", max_rows=60)

        # ── D. item CATEGORY — what's on the item master ─────────────────────────
        rule(f"D. ITEM CATEGORY candidates (tblEngItemMaster) for {pid}'s open items")
        run(cur, "D1. item + any category-ish columns (adjust after seeing A's tags)",
            "SELECT TOP 20 eim.ItemID, eim.ItemDescription, eim.PartCategory, eim.ItemCategory "
            "FROM tblEngItemMaster eim "
            f"WHERE eim.ItemID IN (SELECT DISTINCT pod.ItemID FROM vwPurchaseOrderDetails pod "
            f"                     WHERE pod.ProjectID = {pid})")

        # ── E. spec dates — planned ship / assembly per machine ──────────────────
        rule(f"E. SPEC DATES for {pid} — planned ship / assembly (per machine/spec)")
        run(cur, "E1. spec ship/assembly candidate dates",
            "SELECT ProjectID, SpecID, BudgetShipRelease, BudgetMfgRelease, MfgBegin "
            f"FROM dbo.vwSpec WHERE ProjectID = {pid} ORDER BY SpecID")
    finally:
        conn.close()
    print("\nDone. Paste the whole output.\n"
          "  • A = every candidate column, tagged to the requested fields. The tags tell us which\n"
          "    ETO column feeds category / status / updated / assembly / RFQ / permit / ship, or\n"
          "    that ETO has no such column (⇒ that field can't be populated, like lead time).\n"
          "  • B/C/D/E = real values for the ones we expect to exist. If D1 errors on a column\n"
          "    name, A's item-master list shows the real category column to use.\n"
          "Then I'll rebuild the PO Exception report with every field ETO can actually supply.")


if __name__ == "__main__":
    main()
