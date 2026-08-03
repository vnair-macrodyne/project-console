"""
console_diag_po_to_order.py — find the ETO "issued vs draft" PO signal (2026-08-03).

GOAL: build a "Purchase Lines to Order" report = PO detail lines that exist in ETO but have
NOT yet been ISSUED to the vendor (the draft / un-placed backlog), grouped by project → machine.
The console's existing PO reports all cover POs that are already issued (open / overdue / by
buyer). We need the field that separates an *issued/placed* PO from a *draft* one.

This probe is READ-ONLY. It:
  A. lists the columns of the PO header (view + base table) so we can see what state fields exist
  B. hunts for a PO-status lookup table and prints its values
  C. profiles every plausible state column that actually exists (date null/!null, or value counts)
  D. previews a couple of best-guess "not yet issued" definitions, scoped to tracked projects

Run:  python console_diag_po_to_order.py
Paste the WHOLE output back. Nothing is written.
"""

HEADER_VIEW = "vwPurchaseOrderHeader"
HEADER_TBL = "tblPurchaseOrderHeader"
DETAIL_VIEW = "vwPurchaseOrderDetails"

# Columns that, in Total ETO installs, tend to carry the issued/placed/draft signal.
CANDIDATE_STATE_COLS = [
    "PurchaseDate", "DatePlaced", "PlacedDate", "IssuedDate", "DateIssued", "OrderedDate",
    "DateOrdered", "PrintedDate", "DatePrinted", "SentDate", "DateSent", "ApprovedDate",
    "PurchaseOrderStatusID", "POStatusID", "StatusID", "PurchaseOrderStatus", "POStatus",
    "Status", "PurchaseStatus", "Placed", "Issued", "Printed", "Sent", "Emailed", "Approved",
    "Ordered", "Released", "Confirmed", "Complete", "Closed", "PurchaseActive", "IsDraft",
    "Draft", "PurchaseOrderNumber", "PONumber",
]


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


def main():
    conn = eto_connect()
    cur = conn.cursor()
    ids = tracked_ids()
    idlist = ",".join(str(i) for i in ids) if ids else None
    try:
        # ── A. Header shape ──────────────────────────────────────────────────────
        rule("A. PO HEADER COLUMNS — what state fields exist?")
        hdr_view_cols = columns_of(cur, HEADER_VIEW)
        hdr_tbl_cols = columns_of(cur, HEADER_TBL)
        print(f"\n  {HEADER_VIEW} ({len(hdr_view_cols)} cols):")
        for n, t in hdr_view_cols:
            print(f"    {n} : {t}")
        print(f"\n  {HEADER_TBL} ({len(hdr_tbl_cols)} cols):")
        for n, t in hdr_tbl_cols:
            print(f"    {n} : {t}")

        # ── B. Status lookup tables ──────────────────────────────────────────────
        rule("B. PO STATUS LOOKUP TABLES (if any) + their values")
        run(cur, "B1. tables/views named like a PO status lookup",
            "SELECT TABLE_NAME FROM INFORMATION_SCHEMA.TABLES "
            "WHERE TABLE_NAME LIKE '%PurchaseOrderStatus%' OR TABLE_NAME LIKE '%POStatus%' "
            "OR (TABLE_NAME LIKE '%Purchase%' AND TABLE_NAME LIKE 'tlkp%') ORDER BY TABLE_NAME")
        for lk in ("tlkpPurchaseOrderStatus", "tlkpPOStatus", "tlkpPurchaseStatus"):
            run(cur, f"B/{lk} — values", f"SELECT * FROM dbo.{lk}")

        # ── C. Profile the state columns that actually exist ─────────────────────
        rule("C. STATE-COLUMN PROFILING on " + HEADER_TBL)
        present = {n for n, _ in hdr_tbl_cols}
        typemap = {n: t for n, t in hdr_tbl_cols}
        for col in CANDIDATE_STATE_COLS:
            if col not in present:
                continue
            t = (typemap.get(col) or "").lower()
            if t in ("date", "datetime", "datetime2", "smalldatetime"):
                run(cur, f"C/{col} ({t}) — null vs populated",
                    f"SELECT CASE WHEN {col} IS NULL THEN 'NULL' ELSE 'set' END AS state, "
                    f"COUNT(*) AS n FROM dbo.{HEADER_TBL} GROUP BY CASE WHEN {col} IS NULL "
                    "THEN 'NULL' ELSE 'set' END")
            else:
                run(cur, f"C/{col} ({t}) — value distribution",
                    f"SELECT {col} AS value, COUNT(*) AS n FROM dbo.{HEADER_TBL} "
                    f"GROUP BY {col} ORDER BY n DESC", max_rows=25)

        # ── D. Best-guess "to order" previews, scoped to tracked projects ────────
        rule("D. TO-ORDER PREVIEWS (scoped to tracked projects)")
        if not idlist:
            print("  (no tracked ids — skipping scoped previews)")
        else:
            # D1: headers whose PurchaseDate IS NULL (a common 'not placed yet' signal)
            if "PurchaseDate" in present:
                run(cur, "D1. detail lines under headers with PurchaseDate IS NULL, by project",
                    "SELECT pod.ProjectID, COUNT(*) AS ToOrderLines, "
                    "CAST(SUM(pod.ExtendedPrice) AS decimal(20,2)) AS ExtValue "
                    f"FROM dbo.{DETAIL_VIEW} pod JOIN dbo.{HEADER_VIEW} poh "
                    "ON poh.PurchaseOrderID = pod.PurchaseOrderID "
                    f"WHERE pod.ProjectID IN ({idlist}) AND poh.PurchaseDate IS NULL "
                    "GROUP BY pod.ProjectID ORDER BY pod.ProjectID")
            # D2: sample of those candidate draft lines (columns we know exist on the detail view)
            if "PurchaseDate" in present:
                run(cur, "D2. sample draft (PurchaseDate NULL) lines",
                    "SELECT TOP 15 pod.ProjectID, pod.PurchaseOrderID, poh.PurchaseActive, "
                    "poh.PurchaseDate, pod.ExtendedPrice, pod.Received "
                    f"FROM dbo.{DETAIL_VIEW} pod JOIN dbo.{HEADER_VIEW} poh "
                    "ON poh.PurchaseOrderID = pod.PurchaseOrderID "
                    f"WHERE pod.ProjectID IN ({idlist}) AND poh.PurchaseDate IS NULL "
                    "ORDER BY pod.ProjectID")
    finally:
        conn.close()
    print("\nDone. Paste the whole output back.\n"
          "  • A/B tell us if there's a real status field/lookup (best signal for 'issued').\n"
          "  • C shows which candidate columns carry the draft/issued distinction and their spread.\n"
          "  • D is a first count of 'to order' lines per project under the PurchaseDate-null guess —\n"
          "    we'll swap in the true 'issued' field once A–C identify it.")


if __name__ == "__main__":
    main()
