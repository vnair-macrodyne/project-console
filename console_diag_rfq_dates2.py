"""
console_diag_rfq_dates2.py — RFQ probe, take 2 (2026-09-12).  READ-ONLY. Nothing is written.

Take 1 confirmed an RFQ module exists (urpRFQ, urpRFQDetail, uspRFQHeaderInsert, uspRFQDetailInsert,
uspPurchaseOrderFromRFQ, ...) but section A had a bug (queried INFORMATION_SCHEMA.TABLES with column
`name` instead of `TABLE_NAME`), so it never listed the RFQ TABLES and B/C ran empty.

This take:
  A. lists the RFQ tables/views correctly,
  B. dumps their columns (LINK keys + DATE columns) and a few sample rows,
  C. dumps the DEFINITIONS of the key procs — the insert procs name the exact table+columns, and
     uspPurchaseOrderFromRFQ shows how an RFQ line maps to a PO line (the join we need for RFQ Date).

Run where the other console_diag_*.py scripts run (ETO reachable):
    python console_diag_rfq_dates2.py
Paste the WHOLE output back.
"""
SAMPLE_PROJECT = 250250
LINK_HINTS = ["projectid", "purchaseorderid", "purchasedetailid", "itemid", "itemcompanyid",
              "specid", "supplierid", "companyid", "vendorid", "rfqid", "rfqdetailid"]
DATE_HINTS = ["date", "sent", "received", "requested", "created", "due", "quoted", "response", "reply"]
PROC_DEFS = ["uspRFQHeaderInsert", "uspRFQDetailInsert", "uspPurchaseOrderFromRFQ",
             "urpRFQDetail", "urpRFQ", "uspRFQHeaderInsertWithID", "udfSuppliersByRFQ"]


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
    print("\n" + "=" * 84 + f"\n{t}\n" + "=" * 84)


def run(cur, label, sql, params=None, cap=30):
    print(f"\n-- {label}\n   {' '.join(sql.split())[:280]}")
    try:
        cur.execute(sql, params) if params else cur.execute(sql)
        if cur.description is None:
            print("   (no result set)"); return [], []
        cols = [d[0] for d in cur.description]
        rows = cur.fetchall()
        print("   " + " | ".join(cols))
        for r in rows[:cap]:
            print("   " + " | ".join("" if v is None else str(v) for v in r))
        print(f"   ({len(rows)} row(s){', showing '+str(cap) if len(rows)>cap else ''})")
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
        print(f"   !! columns of {table}: {e}"); return []


def main():
    eto = eto_connect()
    cur = eto.cursor()

    # ── A. RFQ tables / views (TABLE_NAME, fixed) ────────────────────────────────
    rule("A. RFQ / quote TABLES and VIEWS")
    _, tv = run(cur, "A1. tables + views", """
        SELECT TABLE_TYPE, TABLE_NAME FROM INFORMATION_SCHEMA.TABLES
        WHERE LOWER(TABLE_NAME) LIKE '%rfq%' OR LOWER(TABLE_NAME) LIKE '%quote%'
           OR LOWER(TABLE_NAME) LIKE '%quotation%'
        ORDER BY TABLE_TYPE, TABLE_NAME""", cap=200)

    # ── B. Columns + sample rows of each RFQ table ───────────────────────────────
    rule("B. COLUMNS of each RFQ table — LINK keys + DATE columns, with sample rows")
    for _, nm in (tv or []):
        cc = cols_of(cur, nm)
        if not cc:
            continue
        low = {c[0].lower(): c[0] for c in cc}
        links = [low[h] for h in LINK_HINTS if h in low]
        dates = [c[0] for c in cc if any(h in c[0].lower() for h in DATE_HINTS)]
        print(f"\n   >>> {nm}")
        print(f"       ALL: " + ", ".join(f"{c[0]}({c[1]})" for c in cc))
        print(f"       LINK keys: {links or '(none obvious)'}")
        print(f"       DATE cols: {dates or '(none)'}")
        run(cur, f"       TOP 6 rows of {nm}", f"SELECT TOP 6 * FROM dbo.{nm}", cap=6)
        if "projectid" in low:
            run(cur, f"       rows of {nm} for Project {SAMPLE_PROJECT}",
                f"SELECT TOP 8 * FROM dbo.{nm} WHERE ProjectID = ?", (SAMPLE_PROJECT,), cap=8)

    # ── C. Proc DEFINITIONS — insert procs name the table+cols; PO-from-RFQ shows the link ──
    rule("C. DEFINITIONS of the key RFQ procs (schema + RFQ→PO linkage)")
    for nm in PROC_DEFS:
        run(cur, f"C. definition of {nm}",
            "SELECT m.definition FROM sys.sql_modules m "
            "JOIN sys.objects o ON o.object_id = m.object_id WHERE o.name = ?", (nm,), cap=1)

    eto.close()
    print("\nDONE — paste everything above.")


if __name__ == "__main__":
    main()
