"""
console_diag_custom_captions.py — map ETO item-master custom-field CAPTIONS to their PartCustom*
columns, so we wire the Exception report's "Inspected" (and verify Oversized / LLT / Eng Release) to
the RIGHT column.  READ-ONLY.  Nothing is written.  (2026-09-12)

etospec currently assumes:  PartCustom6 = Eng Release,  PartCustom7 = LLT,  PartCustom8 = Oversized.
We now also need "Inspected". Total ETO keeps the custom-field labels in a settings table (columns
like 'PartCustom8Caption' or a lookup of field->caption). This probe finds them and prints the
caption for every PartCustom* so we can map by NAME, not by guessing a column number.

It:
  1. Finds every column named like a custom-field CAPTION (…Custom…Caption / …Caption…) and its table.
  2. Dumps those caption values (the caption row) so we see e.g. PartCustom8Caption = 'Oversized'.
  3. Lists tblEngItemMaster's PartCustom* columns + data types, with a sample of DISTINCT non-null
     values per column, so an 'Inspected' flag/date is recognizable even if captions aren't found.

Run from the repo root:
    python console_diag_custom_captions.py
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


def run(cur, label, sql, cap=80):
    print(f"\n-- {label}")
    try:
        cur.execute(sql)
        if cur.description is None:
            print("   (no result set)"); return []
        cols = [d[0] for d in cur.description]
        rows = cur.fetchall()
        print("   " + " | ".join(cols))
        for r in rows[:cap]:
            print("   " + " | ".join("" if v is None else str(v) for v in r))
        print(f"   ({len(rows)} row(s))")
        return rows
    except Exception as e:
        print(f"   !! {type(e).__name__}: {e}")
        return []


def main():
    eto = eto_connect()
    cur = eto.cursor()

    # ── 1. Find caption columns (where the labels live) ──────────────────────────
    rule("1. Columns that look like custom-field CAPTIONS (…Custom…Caption / …Caption)")
    capcols = run(cur, "1. INFORMATION_SCHEMA.COLUMNS caption-like", """
        SELECT TABLE_NAME, COLUMN_NAME
        FROM INFORMATION_SCHEMA.COLUMNS
        WHERE (COLUMN_NAME LIKE '%PartCustom%Caption%' OR COLUMN_NAME LIKE '%ItemCustom%Caption%'
            OR COLUMN_NAME LIKE '%Custom%Caption%' OR COLUMN_NAME LIKE '%Custom%Label%')
        ORDER BY TABLE_NAME, COLUMN_NAME""", cap=200)

    # ── 2. Dump the caption values from each table that has PartCustom*Caption ────
    rule("2. Caption VALUES (maps PartCustom* -> its label, incl. 'Inspected'/'Oversized'/'LLT')")
    tables = sorted({r[0] for r in capcols})
    for t in tables:
        cols = [r[1] for r in capcols if r[0] == t]
        # only the part/item custom captions, keep it readable
        pcols = [c for c in cols if "custom" in c.lower()]
        if not pcols:
            continue
        sel = ", ".join(f"[{c}]" for c in pcols)
        run(cur, f"2. {t} — caption row", f"SELECT TOP 1 {sel} FROM dbo.{t}", cap=1)

    # ── 3. tblEngItemMaster PartCustom* columns + sample distinct values ─────────
    rule("3. tblEngItemMaster PartCustom* columns + sample non-null values")
    pc = run(cur, "3a. PartCustom* / Inspect* columns on tblEngItemMaster", """
        SELECT COLUMN_NAME, DATA_TYPE FROM INFORMATION_SCHEMA.COLUMNS
        WHERE TABLE_NAME='tblEngItemMaster'
          AND (COLUMN_NAME LIKE 'PartCustom%' OR COLUMN_NAME LIKE '%Inspect%'
            OR COLUMN_NAME LIKE '%Oversiz%' OR COLUMN_NAME LIKE '%LLT%' OR COLUMN_NAME LIKE '%Lead%')
        ORDER BY COLUMN_NAME""", cap=60)
    for cname, dtype in [(r[0], r[1]) for r in pc]:
        run(cur, f"3b. {cname} ({dtype}) — distinct non-null sample",
            f"SELECT TOP 8 [{cname}] AS val, COUNT(*) AS n FROM dbo.tblEngItemMaster "
            f"WHERE [{cname}] IS NOT NULL GROUP BY [{cname}] ORDER BY n DESC", cap=8)

    eto.close()
    print("\nDONE — paste everything above.")


if __name__ == "__main__":
    main()
