"""
console_diag_po_history.py — can we tell when a PO was CREATED or UPDATED? (2026-08-14)

We know: PurchaseDate = order/created date (reliable). We proved earlier ETO has no per-PO
"last modified" audit column. BUT ETO keeps history logs (e.g. tblBOMReleaseHistory) — so this
probe checks whether a PO CHANGE/HISTORY table exists that would give a real created+updated, plus
other activity dates (receipts, revisions), and assembles the full date picture for one real PO.

  A. PO-related tables — anything with 'Purchase' in the name: row count, has a date/PO key.
  B. HISTORY/AUDIT/LOG tables that carry a PurchaseOrderID / PurchaseDetailID (the change log).
  C. Header/line CREATE/ENTER/MODIFY timestamp columns (created/entered/modified/logdate/…).
  D. RECEIVER LOG — last-receipt activity per PO line.
  E. FULL PICTURE for one recent active PO: order date, revised date, receipts, + any history rows.

READ-ONLY.  Run:  python console_diag_po_history.py [purchaseOrderID]   → paste the whole output.
"""
import sys

TS_HINTS = ("date", "time", "created", "enter", "modif", "updat", "changed", "logdate", "stamp",
            "revis", "received", "receipt")
KEY_HINTS = ("purchaseorderid", "purchasedetailid")
HIS_HINTS = ("his", "audit", "log", "change", "revision", "journal", "track")


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


def scalar(cur, sql):
    try:
        cur.execute(sql)
        r = cur.fetchone()
        return r[0] if r else None
    except Exception as e:
        return f"[ERROR] {type(e).__name__}: {e}"


def run(cur, label, sql, max_rows=30):
    print("\n" + "-" * 78 + f"\n{label}\n" + "-" * 78)
    try:
        cur.execute(sql)
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
    po = None
    if len(sys.argv) > 1:
        try:
            po = int(sys.argv[1])
        except ValueError:
            pass
    if po is None:
        po = scalar(cur, "SELECT MAX(PurchaseOrderID) FROM dbo.vwPurchaseOrderHeader "
                         "WHERE PurchaseActive = 1")
    print(f"Sample PO: {po}")
    try:
        # ── A. tables with 'Purchase' in the name ────────────────────────────────
        rule("A. PO-RELATED TABLES ('Purchase' in name) — rows + has PO key / a date column")
        cur.execute("SELECT TABLE_NAME FROM INFORMATION_SCHEMA.TABLES "
                    "WHERE TABLE_TYPE='BASE TABLE' AND TABLE_NAME LIKE '%Purchase%' ORDER BY TABLE_NAME")
        for (t,) in cur.fetchall():
            cols = columns_of(cur, t)
            names = [c.lower() for c, _ in cols]
            has_key = any(k in names for k in KEY_HINTS)
            date_cols = [c for c, dt in cols if dt.lower() in
                         ("datetime", "date", "datetime2", "smalldatetime")]
            n = scalar(cur, f"SELECT COUNT(*) FROM dbo.[{t}]")
            hislike = " ★history-like" if any(h in t.lower() for h in HIS_HINTS) else ""
            print(f"  {t}  ({n} rows){'  [PO key]' if has_key else ''}"
                  f"{('  dates: ' + ', '.join(date_cols)) if date_cols else ''}{hislike}")

        # ── B. any HISTORY/AUDIT/LOG table carrying a PO key ────────────────────
        rule("B. HISTORY/AUDIT/LOG tables that carry PurchaseOrderID / PurchaseDetailID")
        run(cur, "B1. columns named like a PO key inside history/audit/log tables",
            "SELECT c.TABLE_NAME, c.COLUMN_NAME, c.DATA_TYPE "
            "FROM INFORMATION_SCHEMA.COLUMNS c "
            "WHERE c.COLUMN_NAME IN ('PurchaseOrderID','PurchaseDetailID') "
            "  AND (c.TABLE_NAME LIKE '%His%' OR c.TABLE_NAME LIKE '%Audit%' "
            "       OR c.TABLE_NAME LIKE '%Log%' OR c.TABLE_NAME LIKE '%Change%' "
            "       OR c.TABLE_NAME LIKE '%Revision%' OR c.TABLE_NAME LIKE '%Journal%') "
            "ORDER BY c.TABLE_NAME", max_rows=40)

        # ── C. create/enter/modify timestamps on header + line ──────────────────
        rule("C. CREATE / ENTER / MODIFY timestamp columns on the PO header + line")
        for obj in ("vwPurchaseOrderHeader", "tblPurchaseOrderHeader",
                    "vwPurchaseOrderDetails", "tblPurchaseOrderDetails"):
            cols = columns_of(cur, obj)
            ts = [c for c, dt in cols if (any(h in c.lower() for h in TS_HINTS)
                                          or dt.lower() in ("datetime", "date", "datetime2", "smalldatetime"))]
            print(f"\n  {obj}: " + (", ".join(ts) if ts else "(no timestamp-ish columns)"))

        # ── D. receiver log — last-receipt activity ─────────────────────────────
        rule("D. RECEIVER LOG — the 'received' activity signal")
        run(cur, "D1. vwReceiverLogSummed columns",
            "SELECT COLUMN_NAME, DATA_TYPE FROM INFORMATION_SCHEMA.COLUMNS "
            "WHERE TABLE_NAME='vwReceiverLogSummed' ORDER BY ORDINAL_POSITION", max_rows=40)

        # ── E. full date picture for the sample PO ──────────────────────────────
        rule(f"E. FULL DATE PICTURE for PO {po}")
        run(cur, "E1. header dates",
            f"SELECT PurchaseOrderID, CAST(PurchaseDate AS date) AS Ordered, "
            f"  CAST(PurchaseDateRequired AS date) AS Required, "
            f"  CAST(PurchaseDateRevised AS date) AS Revised, PurchasePrinted, PurchaseEmailed "
            f"FROM dbo.vwPurchaseOrderHeader WHERE PurchaseOrderID = {po}")
        run(cur, "E2. line-level dates + last receipt",
            f"SELECT TOP 20 pod.PurchaseDetailID, pod.ItemID, "
            f"  CAST(pod.DateRequired AS date) AS Required, CAST(pod.DateRevised AS date) AS Revised, "
            f"  CAST(pdd.LastReceivedDate AS date) AS LastReceipt "
            f"FROM dbo.vwPurchaseOrderDetails pod "
            f"LEFT JOIN dbo.vwPurchaseOrderDetailsDetailed pdd ON pdd.PurchaseDetailID = pod.PurchaseDetailID "
            f"WHERE pod.PurchaseOrderID = {po}")
    finally:
        conn.close()
    print("\nDone. Paste the whole output. How to read it:\n"
          "  • A/B = does a PO history/audit/log table exist? If B returns a table with a PO key +\n"
          "    a datetime, that is the real CREATED (first row) + UPDATED (last row) trail.\n"
          "  • C = any created/entered/modified timestamp on the header/line itself.\n"
          "  • D = the receiver log gives a genuine 'last received' activity date per line.\n"
          "  • E = the assembled picture for one PO. If no history table + no modify stamp, the best\n"
          "    'updated' proxy = the latest of (revised date, last receipt); 'created' = order date.")


if __name__ == "__main__":
    main()
