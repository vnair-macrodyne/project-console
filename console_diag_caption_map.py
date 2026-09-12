"""
console_diag_caption_map.py — dump tlkpCaption so we map every custom-field CAPTION to its
PartCustom* / PurchaseOrderDetailCustom* column, and find what 'Inspected' and 'Critical' are
actually called.  READ-ONLY.  Nothing written.  (2026-09-12)

console_diag_find_captions found tlkpCaption.Caption holds 'Long Lead Item', 'Oversize Permit
Required', 'Lead Time', … This probe:
  1. Prints tlkpCaption's columns (to see the key that links a caption to a table+column).
  2. Dumps EVERY tlkpCaption row (so we see all captions incl. anything like Inspected/Critical).
  3. Highlights rows whose caption OR key mentions custom / part / PO / inspect / critical / oversize
     / lead / drawing — the ones we care about for the Exception report.

Run from the repo root:
    python console_diag_caption_map.py
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


def main():
    eto = eto_connect()
    cur = eto.cursor()

    # ── 1. structure ─────────────────────────────────────────────────────────────
    rule("1. tlkpCaption columns")
    cur.execute("SELECT COLUMN_NAME, DATA_TYPE FROM INFORMATION_SCHEMA.COLUMNS "
                "WHERE TABLE_NAME='tlkpCaption' ORDER BY ORDINAL_POSITION")
    cols_meta = cur.fetchall()
    for r in cols_meta:
        print(f"   {r[0]} : {r[1]}")
    colnames = [r[0] for r in cols_meta]

    # ── 2. full dump ─────────────────────────────────────────────────────────────
    rule("2. tlkpCaption — ALL rows")
    try:
        cur.execute("SELECT * FROM dbo.tlkpCaption ORDER BY " + ", ".join(f"[{c}]" for c in colnames[:2]))
        cols = [d[0] for d in cur.description]
        rows = cur.fetchall()
        print("   " + " | ".join(cols))
        for r in rows:
            print("   " + " | ".join("" if v is None else str(v) for v in r))
        print(f"   ({len(rows)} row(s))")
    except Exception as e:
        print(f"   !! {type(e).__name__}: {e}")
        rows, cols = [], []

    # ── 3. focused view — rows we care about ─────────────────────────────────────
    rule("3. Rows mentioning custom / part / PO / inspect / critical / oversize / lead / drawing")
    hint = ("custom", "part", "purchase", "po", "inspect", "critical", "oversize", "oversized",
            "long lead", "llt", "lead", "drawing")
    for r in rows:
        blob = " | ".join("" if v is None else str(v) for v in r).lower()
        if any(h in blob for h in hint):
            print("   " + " | ".join("" if v is None else str(v) for v in r))

    eto.close()
    print("\nDONE — paste everything above.")


if __name__ == "__main__":
    main()
