"""
console_diag_rfq_dates.py — find the ETO RFQ (Request-for-Quote) tables so the Exception report
can show an RFQ date per PO line (2026-09-12).  READ-ONLY. Nothing is written.

The 2026-08-12 field probe found no RFQ column on the PO views, so RFQ Date has been blank. Vijay:
there's a SET OF RFQ TABLES available — we should pull the date from there. This probe finds them
and shows how they key back to a PO line / item / project, plus which column carries the date, so
we can wire RFQ Date correctly (and against reality, not a guess).

Run where the other console_diag_*.py scripts run (ETO reachable):
    python console_diag_rfq_dates.py
Paste the WHOLE output back.
"""
SAMPLE_PROJECT = 250250
NAME_HINTS = ["rfq", "requestforquote", "request_for_quote", "quote", "quotation", "vendorquote",
              "supplierquote", "bid"]
LINK_HINTS = ["projectid", "purchaseorderid", "purchasedetailid", "itemid", "itemcompanyid",
              "specid", "supplierid", "companyid", "vendorid"]
DATE_HINTS = ["date", "sent", "received", "requested", "created", "due", "quoted", "response"]


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
    like = " OR ".join(f"LOWER(name) LIKE '%{h}%'" for h in NAME_HINTS)

    # ── A. Every RFQ / quote object ──────────────────────────────────────────────
    rule("A. TABLES / VIEWS whose name hints at RFQ / quote / bid")
    _, tv = run(cur, "A1. tables + views", f"""
        SELECT TABLE_TYPE, TABLE_NAME FROM INFORMATION_SCHEMA.TABLES
        WHERE {like} ORDER BY TABLE_TYPE, TABLE_NAME""", cap=200)
    run(cur, "A2. procs / functions (a report proc names its source tables)", f"""
        SELECT o.type_desc, o.name FROM sys.objects o
        WHERE o.type IN ('P','FN','IF','TF') AND ({like.replace('name','o.name')})
        ORDER BY o.type_desc, o.name""", cap=200)

    # ── B. Columns + linkage + date columns for each RFQ object ──────────────────
    rule("B. COLUMNS of each RFQ object — the LINK keys and DATE columns are what we need")
    names = [r[1] for r in (tv or [])]
    for nm in names[:14]:
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
        # sample rows for the sample project when it carries ProjectID
        if "projectid" in low:
            run(cur, f"       sample rows of {nm} for Project {SAMPLE_PROJECT}",
                f"SELECT TOP 8 * FROM dbo.{nm} WHERE ProjectID = ?", (SAMPLE_PROJECT,), cap=8)

    # ── C. Can an RFQ row be tied to a PO line? probe the common joins ───────────
    rule("C. LINKAGE — does an RFQ row join to a PO line/item? (best-effort, tolerate failures)")
    # header/detail pair guess
    for hdr in [n for n in names if "header" in n.lower() or n.lower().endswith("rfq")][:3]:
        hc = {c[0].lower() for c in cols_of(cur, hdr)}
        if "itemid" in hc:
            run(cur, f"C. {hdr}: any RFQ rows for items on Project {SAMPLE_PROJECT}'s POs?", f"""
                SELECT TOP 10 r.* FROM dbo.{hdr} r
                WHERE r.ItemID IN (SELECT DISTINCT ItemID FROM dbo.vwPurchaseOrderDetails
                                   WHERE ProjectID = ?)""", (SAMPLE_PROJECT,), cap=10)
        if "purchaseorderid" in hc:
            run(cur, f"C. {hdr}: any RFQ rows for Project {SAMPLE_PROJECT}'s POs?", f"""
                SELECT TOP 10 r.* FROM dbo.{hdr} r
                WHERE r.PurchaseOrderID IN (SELECT PurchaseOrderID FROM dbo.vwPurchaseOrderHeader poh
                    JOIN dbo.vwPurchaseOrderDetails pod ON pod.PurchaseOrderID = poh.PurchaseOrderID
                    WHERE pod.ProjectID = ?)""", (SAMPLE_PROJECT,), cap=10)

    eto.close()
    print("\nDONE — paste everything above.")


if __name__ == "__main__":
    main()
