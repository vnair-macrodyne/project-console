"""
console_diag_bom_release_date.py — find the BOM ASSEMBLY RELEASE DATE in ETO (2026-08-14)

Starting point for the released-BOM material projection: we need the DATE each BOM assembly was
released. `vwEngBOM.BOMAssemblyReleaseID` points at a release record; this probe finds that record's
table, its date column, joins it back to the BOM, and shows a real release date per assembly for a
sample project — plus how much of the BOM resolves to a date (and how it compares to other date
signals we already know, like the item Eng Release date).

  A. RELEASE TABLES — anything named *Release* / *AssemblyRel*: columns (date ⧗, key ◆) + row count.
  B. SAMPLE the most likely release table.
  C. JOIN vwEngBOM.BOMAssemblyReleaseID → release record: real release dates per assembly (project).
  D. COVERAGE — BOM lines with a release id, and of those how many resolve to a release DATE; the
     release-date span per spec/machine.
  E. CROSS-CHECK vs other date signals (BOM RequiredDate, item Eng Release = PartCustom6).

READ-ONLY.  Run:  python console_diag_bom_release_date.py [projectID]   (default 240040) → paste.
"""
import sys

BOM = "vwEngBOM"
DATE_HINTS = ("date", "released", "effectiv")
KEY_HINTS = ("assemblyreleaseid", "bomassemblyreleaseid", "releaseid", "projectid", "specid",
             "parentid", "childid", "itemid")


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


def run(cur, label, sql, params=(), max_rows=30):
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


def scalar(cur, sql):
    try:
        cur.execute(sql)
        r = cur.fetchone()
        return r[0] if r else None
    except Exception as e:
        return f"[ERROR] {type(e).__name__}: {e}"


def main():
    pid = 240040
    if len(sys.argv) > 1:
        try:
            pid = int(sys.argv[1])
        except ValueError:
            pass
    conn = eto_connect()
    cur = conn.cursor()
    print(f"Sample project: {pid}")
    try:
        # ── A. release tables ────────────────────────────────────────────────────
        rule("A. RELEASE TABLES (name ~ Release / AssemblyRel) — columns (⧗ date  ◆ key) + rows")
        cur.execute("SELECT TABLE_NAME FROM INFORMATION_SCHEMA.TABLES "
                    "WHERE TABLE_NAME LIKE '%Release%' OR TABLE_NAME LIKE '%AssemblyRel%' "
                    "ORDER BY TABLE_NAME")
        tables = [r[0] for r in cur.fetchall()]
        info = {}
        for t in tables:
            cols = columns_of(cur, t)
            info[t] = cols
            n = scalar(cur, f"SELECT COUNT(*) FROM dbo.[{t}]")
            print(f"\n  ── {t}  ({n} rows)")
            for c, dt in cols:
                cl = c.lower()
                tag = ""
                if dt.lower() in ("datetime", "date", "datetime2", "smalldatetime") or any(h in cl for h in DATE_HINTS):
                    tag += " ⧗date"
                if any(h in cl for h in KEY_HINTS):
                    tag += " ◆key"
                print(f"       {c} : {dt}{tag}")

        # choose the most likely release-header table: has an *AssemblyReleaseID/ReleaseID + a date
        def date_col(cols):
            for c, dt in cols:
                if dt.lower() in ("datetime", "date", "datetime2", "smalldatetime"):
                    return c
            return None

        def id_col(cols):
            names = [c for c, _ in cols]
            for pref in ("BOMAssemblyReleaseID", "AssemblyReleaseID", "ReleaseID"):
                for c in names:
                    if c.lower() == pref.lower():
                        return c
            for c in names:
                if "releaseid" in c.lower():
                    return c
            return None

        pick = None
        for t, cols in info.items():
            if id_col(cols) and date_col(cols):
                pick = t
                break

        # ── B. sample the chosen table ──────────────────────────────────────────
        rule(f"B. SAMPLE release table = {pick}")
        if pick:
            print(f"  key column  = {id_col(info[pick])}")
            print(f"  date column = {date_col(info[pick])}")
            run(cur, f"B1. {pick} — 15 rows", f"SELECT TOP 15 * FROM dbo.[{pick}]", max_rows=15)

        # ── C. JOIN BOM → release record for real dates ─────────────────────────
        rule("C. JOIN vwEngBOM.BOMAssemblyReleaseID → release date (this project)")
        if pick:
            k = id_col(info[pick])
            d = date_col(info[pick])
            run(cur, f"C1. released assemblies with dates (BOM joined to {pick})",
                f"SELECT DISTINCT b.SpecID, b.ParentID, b.BOMAssemblyReleaseID, "
                f"       CAST(rel.[{d}] AS date) AS ReleaseDate "
                f"FROM dbo.{BOM} b "
                f"JOIN dbo.[{pick}] rel ON rel.[{k}] = b.BOMAssemblyReleaseID "
                f"WHERE b.ProjectID = {pid} AND ISNULL(b.BOMAssemblyReleaseID,0) > 0 "
                f"ORDER BY ReleaseDate, b.SpecID", max_rows=40)

            # ── D. coverage ─────────────────────────────────────────────────────
            rule("D. COVERAGE — BOM lines with a release id, and of those how many resolve to a DATE")
            run(cur, "D1. line counts",
                f"SELECT COUNT(*) AS bom_lines, "
                f"  SUM(CASE WHEN ISNULL(b.BOMAssemblyReleaseID,0) > 0 THEN 1 ELSE 0 END) AS has_release_id, "
                f"  SUM(CASE WHEN rel.[{d}] IS NOT NULL THEN 1 ELSE 0 END) AS resolves_to_date "
                f"FROM dbo.{BOM} b "
                f"LEFT JOIN dbo.[{pick}] rel ON rel.[{k}] = b.BOMAssemblyReleaseID "
                f"WHERE b.ProjectID = {pid}")
            run(cur, "D2. release-date span per spec/machine",
                f"SELECT b.SpecID, MIN(CAST(rel.[{d}] AS date)) AS first_release, "
                f"       MAX(CAST(rel.[{d}] AS date)) AS last_release, "
                f"       COUNT(DISTINCT b.BOMAssemblyReleaseID) AS released_assemblies "
                f"FROM dbo.{BOM} b "
                f"JOIN dbo.[{pick}] rel ON rel.[{k}] = b.BOMAssemblyReleaseID "
                f"WHERE b.ProjectID = {pid} AND ISNULL(b.BOMAssemblyReleaseID,0) > 0 "
                f"GROUP BY b.SpecID ORDER BY b.SpecID")
        else:
            print("  No release table with both an id + a date was auto-picked — read A and tell me\n"
                  "  which table/column holds the release date and I'll wire the join.")

        # ── E. cross-check other date signals ───────────────────────────────────
        rule("E. CROSS-CHECK other date signals on the BOM (for context)")
        run(cur, "E1. BOM RequiredDate span + Eng-release (item PartCustom6) presence",
            f"SELECT COUNT(*) AS lines, "
            f"  MIN(CAST(RequiredDate AS date)) AS req_min, MAX(CAST(RequiredDate AS date)) AS req_max, "
            f"  SUM(CASE WHEN RequiredDate IS NOT NULL THEN 1 ELSE 0 END) AS has_required "
            f"FROM dbo.{BOM} WHERE ProjectID = {pid}")
    finally:
        conn.close()
    print("\nDone. Paste the whole output. How to read it:\n"
          "  • A/B = which table holds the assembly-release record and which column is the DATE.\n"
          "  • C = proof we can pull a real release date per assembly by joining on\n"
          "    BOMAssemblyReleaseID. That date is the anchor for 'released BOM'.\n"
          "  • D = how much of the BOM actually resolves to a release date (coverage / the dial).\n"
          "  • E = other dates we already have, in case the release table is thin or missing.\n"
          "  Once we've confirmed the release date, the released-BOM costing builds on top of it.")


if __name__ == "__main__":
    main()
