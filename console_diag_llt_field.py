"""
console_diag_llt_field.py — confirm WHICH custom field is the "Long Lead" flag, and that it carries
data.  READ-ONLY.  (2026-09-29)

The purchasing reports source the Long Lead flag from dbo.tblEngItemMaster.PartCustom7 (caption
"Long Lead Item", per a 2026-09-12 caption check). This re-verifies that from scratch and shows how
many items are actually tagged, so we're not relying on a 3-week-old note.

Prints:
  1. Every 'Part' custom-field caption (dbo.tlkpCaption, Object like 'Part') — so you can SEE which
     PartCustom<n> is the long-lead one, and whether there's a *separate* "Long Lead Time" field.
  2. Any caption anywhere containing 'lead' (catches a differently-named field if one exists).
  3. Population of PartCustom7 on tblEngItemMaster: total items, # tagged (=1), # explicitly 0, # NULL.
  4. The same, but restricted to items that are ON PURCHASE ORDERS (vwPurchaseOrderDetails) — i.e. the
     population the purchasing reports actually show — plus 10 sample tagged part numbers.

Run where the other console_diag_*.py run (ETO reachable):
    python console_diag_llt_field.py
Paste the whole output back. Nothing is written.
"""
LLT_COL = "PartCustom7"


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
    print("\n" + "=" * 92 + f"\n{t}\n" + "=" * 92)


def q(cur, sql):
    cur.execute(sql)
    cols = [d[0] for d in cur.description] if cur.description else []
    return cols, cur.fetchall()


def scalar(cur, sql):
    try:
        cur.execute(sql)
        r = cur.fetchone()
        return r[0] if r else None
    except Exception as e:
        return f"!! {type(e).__name__}: {e}"


def main():
    eto = eto_connect()
    cur = eto.cursor()

    # ── 1. Part custom-field captions ────────────────────────────────────────────
    rule("1. 'Part' custom-field captions (dbo.tlkpCaption) — which PartCustom<n> is 'Long Lead'?")
    try:
        cols, rows = q(cur,
            "SELECT FieldName, Object, Caption FROM dbo.tlkpCaption "
            "WHERE Object LIKE 'Part%' AND FieldName LIKE 'PartCustom%' ORDER BY FieldName")
        for r in rows:
            star = "  <== " if (r[2] and "lead" in str(r[2]).lower()) else ""
            print(f"   {str(r[0]):16} {str(r[1]):10} {r[2]}{star}")
    except Exception as e:
        print(f"   !! {type(e).__name__}: {e}")

    # ── 2. Any caption mentioning 'lead' anywhere ────────────────────────────────
    rule("2. Any caption containing 'lead' (catches a separately-named 'Long Lead Time' field)")
    try:
        cols, rows = q(cur,
            "SELECT FieldName, Object, Caption FROM dbo.tlkpCaption WHERE Caption LIKE '%lead%'")
        if rows:
            for r in rows:
                print(f"   {str(r[0]):16} {str(r[1]):16} {r[2]}")
        else:
            print("   (no caption contains 'lead')")
    except Exception as e:
        print(f"   !! {type(e).__name__}: {e}")

    # ── 3. PartCustom7 population on the item master ─────────────────────────────
    rule(f"3. {LLT_COL} population on dbo.tblEngItemMaster (all items)")
    total = scalar(cur, "SELECT COUNT_BIG(*) FROM dbo.tblEngItemMaster")
    tagged = scalar(cur, f"SELECT COUNT_BIG(*) FROM dbo.tblEngItemMaster WHERE CAST([{LLT_COL}] AS int) = 1")
    zero = scalar(cur, f"SELECT COUNT_BIG(*) FROM dbo.tblEngItemMaster WHERE CAST([{LLT_COL}] AS int) = 0")
    nul = scalar(cur, f"SELECT COUNT_BIG(*) FROM dbo.tblEngItemMaster WHERE [{LLT_COL}] IS NULL")
    print(f"   total items : {total}")
    print(f"   tagged (=1) : {tagged}")
    print(f"   not (=0)    : {zero}")
    print(f"   NULL        : {nul}")

    # ── 4. Restricted to items actually on POs (what the reports show) + samples ──
    rule(f"4. {LLT_COL} among items that are ON PURCHASE ORDERS (the reported population)")
    on_po_tagged = scalar(cur,
        f"SELECT COUNT_BIG(DISTINCT eim.ItemID) FROM dbo.tblEngItemMaster eim "
        f"WHERE CAST(eim.[{LLT_COL}] AS int) = 1 "
        f"AND eim.ItemID IN (SELECT DISTINCT ItemID FROM dbo.vwPurchaseOrderDetails)")
    print(f"   distinct long-lead items that appear on POs: {on_po_tagged}")
    try:
        cols, rows = q(cur,
            f"SELECT TOP 10 eim.ItemCompanyID, eim.ItemDescription "
            f"FROM dbo.tblEngItemMaster eim WHERE CAST(eim.[{LLT_COL}] AS int) = 1 "
            f"AND eim.ItemID IN (SELECT DISTINCT ItemID FROM dbo.vwPurchaseOrderDetails) "
            f"ORDER BY eim.ItemCompanyID")
        print("   sample tagged part numbers on POs:")
        for r in rows:
            print(f"     {str(r[0]):16} {r[1]}")
        if not rows:
            print("     (none — either nothing is tagged, or PartCustom7 is the wrong column)")
    except Exception as e:
        print(f"   !! {type(e).__name__}: {e}")

    eto.close()
    print("\nDONE — paste everything above.")


if __name__ == "__main__":
    main()
