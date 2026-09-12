"""
console_diag_find_captions.py — locate where ETO stores the item-master custom-field captions
('Inspected', 'Oversized', 'LLT'/'Long Lead', 'Lead Time') so we can map them to PartCustom* columns
authoritatively.  READ-ONLY.  Nothing is written.  (2026-09-12)

The captions aren't in a *Caption COLUMN (already checked). They're either aliased in the item-master
VIEW, or stored as VALUES in a settings/resource/label table. This probe:
  1. Dumps the full column list of vwEngItemMaster (it may expose the customs under friendly names).
  2. Scans every nvarchar column in tables whose NAME hints at settings/labels/custom/resource, for
     values matching the caption words — reporting table.column + the value + how many rows. Wherever
     'Inspected' / 'Oversized' live, that table also holds the PartCustom<->caption mapping.

Run from the repo root:
    python console_diag_find_captions.py
Paste the WHOLE output back.
"""
CAPTION_LIKE = ["Inspect%", "Oversize%", "Over Size%", "Oversized%", "LLT%", "Long Lead%",
                "Lead Time%"]
TABLE_NAME_HINTS = ["%Custom%", "%Setting%", "%Option%", "%Caption%", "%Label%", "%Field%",
                    "%Resource%", "%System%", "%Config%", "%Lang%", "%Screen%", "%Grid%"]


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

    # ── 1. vwEngItemMaster columns (may already expose captions) ─────────────────
    rule("1. vwEngItemMaster columns (look for friendly names / custom captions)")
    try:
        cur.execute("SELECT COLUMN_NAME, DATA_TYPE FROM INFORMATION_SCHEMA.COLUMNS "
                    "WHERE TABLE_NAME='vwEngItemMaster' ORDER BY ORDINAL_POSITION")
        for r in cur.fetchall():
            print(f"   {r[0]} : {r[1]}")
    except Exception as e:
        print(f"   !! {type(e).__name__}: {e}")

    # ── 2. candidate nvarchar columns in settings/label-ish tables ───────────────
    rule("2. Scanning settings/label-ish tables for the caption words")
    name_pred = " OR ".join(f"t.name LIKE '{p}'" for p in TABLE_NAME_HINTS)
    cur.execute(f"""
        SELECT t.name AS tbl, c.name AS col
        FROM sys.tables t
        JOIN sys.columns c ON c.object_id = t.object_id
        JOIN sys.types ty ON ty.user_type_id = c.user_type_id
        WHERE ty.name IN ('nvarchar','varchar','nchar','char')
          AND c.max_length BETWEEN 6 AND 400
          AND ({name_pred})
        ORDER BY t.name, c.name""")
    candidates = [(r[0], r[1]) for r in cur.fetchall()]
    print(f"   ({len(candidates)} candidate text columns to scan)")

    like_pred = " OR ".join(f"[{{col}}] LIKE '{p}'" for p in CAPTION_LIKE)
    hits = 0
    for tbl, col in candidates:
        pred = like_pred.format(col=col)
        try:
            cur.execute(f"SELECT DISTINCT TOP 12 [{col}] AS v FROM dbo.[{tbl}] WHERE {pred}")
            vals = [r[0] for r in cur.fetchall()]
            if vals:
                hits += 1
                print(f"\n   >>> {tbl}.{col}:")
                for v in vals:
                    print(f"        {v}")
        except Exception:
            pass   # skip columns that error (computed, permissions, etc.)
    if not hits:
        print("\n   (no caption words found in settings-ish tables — captions may be client-side)")

    # ── 3. If a caption table was found, show its full row for PartCustom mapping ─
    rule("3. Next: whichever table above shows 'Inspected'/'Oversized' — paste it and I'll map the "
         "PartCustom columns. If nothing surfaced, the ETO client's Item Master custom-field setup "
         "screen shows the caption beside each Part Custom N.")

    eto.close()
    print("\nDONE — paste everything above.")


if __name__ == "__main__":
    main()
