"""
console_diag_requisition_module.py — does ETO have a distinct PURCHASE REQUISITION module,
separate from the (draft) Purchase Order?  READ-ONLY.  (2026-09-28)

Background: the console's "Purchase Requisitions" report is currently backed by UNSENT DRAFT POs
(PurchasePrinted=0 AND PurchaseEmailed=0), because our procurement mapping never found a separate
requisition object. This probe settles it: if ETO carries a real requisition table/view/proc, we can
repoint the report at it. Nothing is written.

It prints:
  1. OBJECTS (tables / views / procs / functions) whose NAME looks like a requisition object.
  2. COLUMNS anywhere named like a requisition (a PO line that points back to a requisition, etc.).
  3. The PO header + detail column lists, flagging any column containing 'req' (a requisition link).
  4. tlkpCaption entries mentioning 'requisition' (ETO's own label registry) + distinct Objects w/ 'req'.
  5. For each name-matched TABLE/VIEW: its columns, a row COUNT, and up to 3 sample rows.
  6. A broad, NOISY '%req%' object scan last (Received/Required/Request all match — eyeball it).

Run where the other console_diag_*.py run (ETO reachable):
    python console_diag_requisition_module.py
Paste the WHOLE output back.
"""


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


def q(cur, sql, args=None):
    cur.execute(sql, args or [])
    cols = [d[0] for d in cur.description] if cur.description else []
    return cols, cur.fetchall()


# strong requisition-name signals (low false-positive)
STRONG = ("%requisition%", "%requisit%", "%purchaserequest%", "%purchase_request%",
          "%purchreq%", "%purch_req%")


def main():
    eto = eto_connect()
    cur = eto.cursor()

    # ── 1. objects whose NAME looks like a requisition object ────────────────────
    rule("1. Objects named like a requisition (tables / views / procs / functions)")
    where = " OR ".join("o.name LIKE ?" for _ in STRONG)
    try:
        cols, rows = q(cur,
            "SELECT o.type_desc, s.name AS sch, o.name "
            "FROM sys.objects o JOIN sys.schemas s ON s.schema_id = o.schema_id "
            f"WHERE o.type IN ('U','V','P','FN','TF','IF') AND ({where}) "
            "ORDER BY o.type_desc, o.name", list(STRONG))
        if rows:
            for r in rows:
                print(f"   {r[0]:16} {r[1]}.{r[2]}")
        else:
            print("   (none — no object name contains 'requisition' / 'purchase request')")
        name_hits = [(r[1], r[2], r[0]) for r in rows if r[0] in ("USER_TABLE", "VIEW")]
    except Exception as e:
        print(f"   !! {type(e).__name__}: {e}")
        name_hits = []

    # ── 2. columns anywhere named like a requisition ────────────────────────────
    rule("2. Columns named like a requisition (a link from another table to a requisition)")
    try:
        cols, rows = q(cur,
            "SELECT t.name AS tbl, c.name AS col, ty.name AS type "
            "FROM sys.columns c JOIN sys.tables t ON t.object_id = c.object_id "
            "JOIN sys.types ty ON ty.user_type_id = c.user_type_id "
            "WHERE c.name LIKE '%requisition%' OR c.name LIKE '%requisit%' "
            "   OR c.name LIKE '%purchreq%' OR c.name LIKE '%purchaserequest%' "
            "ORDER BY t.name, c.name")
        if rows:
            for r in rows:
                print(f"   {r[0]}.{r[1]}  ({r[2]})")
        else:
            print("   (none — no column name contains 'requisition')")
    except Exception as e:
        print(f"   !! {type(e).__name__}: {e}")

    # ── 3. PO header + detail columns, flagging any 'req' column ─────────────────
    rule("3. PO header / detail columns — any 'req' column = a requisition link on the PO")
    for obj in ("dbo.tblPurchaseOrderHeader", "dbo.tblPurchaseOrderDetails",
                "dbo.vwPurchaseOrderHeader", "dbo.vwPurchaseOrderDetails"):
        try:
            cols, rows = q(cur,
                "SELECT c.name FROM sys.columns c WHERE c.object_id = OBJECT_ID(?) "
                "ORDER BY c.column_id", [obj])
            names = [r[0] for r in rows]
            reqish = [n for n in names if "req" in n.lower()]
            print(f"   {obj}: {len(names)} cols; 'req'-ish -> {reqish if reqish else '(none)'}")
        except Exception as e:
            print(f"   {obj}: !! {type(e).__name__}: {e}")

    # ── 4. tlkpCaption — ETO's own label registry ───────────────────────────────
    rule("4. tlkpCaption entries mentioning 'requisition' + distinct Objects containing 'req'")
    try:
        cols, rows = q(cur,
            "SELECT FieldName, Object, Caption FROM dbo.tlkpCaption "
            "WHERE Caption LIKE '%requisit%' OR FieldName LIKE '%requisit%' OR Object LIKE '%requisit%'")
        if rows:
            for r in rows:
                print(f"   FieldName={r[0]!s:24} Object={r[1]!s:24} Caption={r[2]}")
        else:
            print("   (no caption mentions 'requisition')")
        cols, rows = q(cur, "SELECT DISTINCT Object FROM dbo.tlkpCaption WHERE Object LIKE '%req%'")
        print("   distinct tlkpCaption.Object containing 'req': " +
              (", ".join(str(r[0]) for r in rows) if rows else "(none)"))
    except Exception as e:
        print(f"   !! {type(e).__name__}: {e}")

    # ── 5. dump each name-matched TABLE/VIEW: columns, row count, sample ─────────
    rule("5. Name-matched tables/views — columns, row count, up to 3 sample rows")
    if not name_hits:
        print("   (nothing to dump — section 1 found no requisition-named table/view)")
    for sch, name, kind in name_hits:
        full = f"{sch}.{name}"
        print(f"\n   --- {kind} {full} ---")
        try:
            cols, _ = q(cur, "SELECT TOP 0 * FROM " + full)
            print("   columns: " + ", ".join(cols))
        except Exception as e:
            print(f"   columns: !! {type(e).__name__}: {e}")
            continue
        try:
            _, cnt = q(cur, "SELECT COUNT_BIG(*) FROM " + full)
            print(f"   row count: {cnt[0][0]:,}")
        except Exception as e:
            print(f"   row count: !! {type(e).__name__}: {e}")
        try:
            cols, rows = q(cur, "SELECT TOP 3 * FROM " + full)
            for r in rows:
                cells = " | ".join("" if v is None else str(v)[:22] for v in r)
                print("   " + cells)
        except Exception as e:
            print(f"   sample: !! {type(e).__name__}: {e}")

    # ── 6. broad, NOISY '%req%' object scan (eyeball — Received/Required/Request match) ─
    rule("6. BROAD '%req%' object scan (NOISY — includes Received / Required / Request)")
    try:
        cols, rows = q(cur,
            "SELECT o.type_desc, o.name FROM sys.objects o "
            "WHERE o.type IN ('U','V','P') AND o.name LIKE '%req%' "
            "ORDER BY o.type_desc, o.name")
        for r in rows:
            print(f"   {r[0]:16} {r[1]}")
        print(f"   ({len(rows)} objects — scan for anything requisition-like the strong filter missed)")
    except Exception as e:
        print(f"   !! {type(e).__name__}: {e}")

    eto.close()
    print("\nDONE — paste everything above.")


if __name__ == "__main__":
    main()
