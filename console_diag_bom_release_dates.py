"""
console_diag_bom_release_dates.py — what timestamps/authorship does tblBOMReleaseHistory carry, and
what can we use when ReleasedDateTime is null?  READ-ONLY.  (2026-09-28)

Lines to Order dates each released item by MIN(ReleasedDateTime) from dbo.tblBOMReleaseHistory. Some
items come back with a BLANK release date — meaning every log row for that (project,item) has a null
ReleasedDateTime. This probe finds a reliable fallback:

  1. Full column list of dbo.tblBOMReleaseHistory (name, type, nullable) — so we can see every date /
     'created' / 'by' / employee column that exists (is it a proper audit log?).
  2. Row count + how many rows have ReleasedDateTime NULL vs populated.
  3. For EVERY date-ish and user-ish column, a populated-vs-null count (which ones are actually filled).
  4. The key test: of the (ProjectID, ItemID) GROUPS whose MIN(ReleasedDateTime) IS NULL (the blank-date
     items on the report), how many are rescued by each candidate date column (i.e. that column IS
     populated) — so we can pick the best COALESCE fallback.
  5. A few sample log rows WHERE ReleasedDateTime IS NULL, dumping all columns, to eyeball what an
     'undated' release actually recorded (author? created time? type?).

Run where the other console_diag_*.py run (ETO reachable):
    python console_diag_bom_release_dates.py
Paste the WHOLE output back. Nothing is written.
"""
TBL = "dbo.tblBOMReleaseHistory"


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

    # ── 1. columns ──────────────────────────────────────────────────────────────
    rule(f"1. Columns of {TBL}")
    cols, rows = q(cur,
        "SELECT COLUMN_NAME, DATA_TYPE, IS_NULLABLE FROM INFORMATION_SCHEMA.COLUMNS "
        "WHERE TABLE_SCHEMA='dbo' AND TABLE_NAME='tblBOMReleaseHistory' ORDER BY ORDINAL_POSITION")
    colnames = [r[0] for r in rows]
    for r in rows:
        print(f"   {r[0]:34} {r[1]:14} null={r[2]}")

    # candidate columns to profile
    datey = [c for c in colnames if any(k in c.lower() for k in ("date", "time", "stamp"))]
    usery = [c for c in colnames if any(k in c.lower() for k in
             ("by", "user", "employee", "creator", "author", "name", "who"))]
    print(f"\n   date-ish columns : {datey}")
    print(f"   user-ish columns : {usery}")

    # ── 2. row counts + ReleasedDateTime null-ness ──────────────────────────────
    rule("2. Row count and ReleasedDateTime population")
    total = scalar(cur, f"SELECT COUNT_BIG(*) FROM {TBL}")
    print(f"   total rows: {total}")
    if "ReleasedDateTime" in colnames:
        nn = scalar(cur, f"SELECT COUNT_BIG(*) FROM {TBL} WHERE ReleasedDateTime IS NOT NULL")
        nu = scalar(cur, f"SELECT COUNT_BIG(*) FROM {TBL} WHERE ReleasedDateTime IS NULL")
        print(f"   ReleasedDateTime populated: {nn}   NULL: {nu}")
    else:
        print("   (no ReleasedDateTime column?! see the column list above)")

    # ── 3. populated-vs-null per date/user column ───────────────────────────────
    rule("3. Populated vs NULL for every date-ish and user-ish column")
    for c in datey + usery:
        nn = scalar(cur, f"SELECT COUNT_BIG(*) FROM {TBL} WHERE [{c}] IS NOT NULL")
        print(f"   {c:34} populated={nn} / {total}")

    # ── 4. fallback rescue test at the GROUP grain the report uses ──────────────
    rule("4. Blank-date GROUPS (MIN(ReleasedDateTime) IS NULL) rescued by each candidate date column")
    # groups with no released date
    blank_groups = scalar(cur,
        f"SELECT COUNT_BIG(*) FROM (SELECT ProjectID, ItemID FROM {TBL} "
        f"GROUP BY ProjectID, ItemID HAVING MIN(ReleasedDateTime) IS NULL) z") \
        if "ReleasedDateTime" in colnames else "n/a"
    print(f"   (project,item) groups with net-any rows and MIN(ReleasedDateTime) NULL: {blank_groups}")
    for c in datey:
        if c == "ReleasedDateTime":
            continue
        rescued = scalar(cur,
            f"SELECT COUNT_BIG(*) FROM (SELECT ProjectID, ItemID FROM {TBL} "
            f"GROUP BY ProjectID, ItemID "
            f"HAVING MIN(ReleasedDateTime) IS NULL AND MAX([{c}]) IS NOT NULL) z")
        print(f"   ...of those, rescued by MAX([{c}]) IS NOT NULL: {rescued}")

    # ── 5. sample undated rows — all columns ────────────────────────────────────
    rule("5. Up to 5 sample rows WHERE ReleasedDateTime IS NULL (all columns)")
    if "ReleasedDateTime" in colnames:
        try:
            cols, rows = q(cur, f"SELECT TOP 5 * FROM {TBL} WHERE ReleasedDateTime IS NULL")
            print("   columns: " + ", ".join(cols))
            for r in rows:
                print("   " + " | ".join("" if v is None else str(v)[:20] for v in r))
        except Exception as e:
            print(f"   !! {type(e).__name__}: {e}")
        # and a couple of DATED rows for contrast
        rule("5b. Up to 3 rows WHERE ReleasedDateTime IS NOT NULL (contrast)")
        try:
            cols, rows = q(cur, f"SELECT TOP 3 * FROM {TBL} WHERE ReleasedDateTime IS NOT NULL")
            for r in rows:
                print("   " + " | ".join("" if v is None else str(v)[:20] for v in r))
        except Exception as e:
            print(f"   !! {type(e).__name__}: {e}")

    eto.close()
    print("\nDONE — paste everything above.")


if __name__ == "__main__":
    main()
