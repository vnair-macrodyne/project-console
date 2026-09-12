"""
console_diag_bom_readiness.py — find the ETO data behind the "Structured BOM - Readiness
Detailed Report" so Sextant can reproduce it faithfully (2026-09-08).  READ-ONLY. Nothing is
written.

The PDF is a native Total ETO report: a per-machine structured BOM (assembly tree: scope →
sub-assembly → part) with, per line, Assembly Qty · Total Qty · Available Qty · Procured Qty ·
To-Be-Procured · % Available · Bin. We need the underlying source(s):
  1. the BOM STRUCTURE (parent/child assembly tree with per-node quantities), and
  2. the AVAILABILITY / PROCUREMENT quantities per part.

This probe (a) name-searches ETO views/tables/procs for BOM/readiness/structure/spec-item, (b)
dumps the DEFINITION of any stored proc that looks like the report (that reveals its exact source
tables — the fastest ground truth), and (c) dumps columns + a few sample rows of the top candidate
views for the sample job (Project 250250, Machine 10).

Run where the other console_diag_*.py scripts run (ETO reachable):
    python console_diag_bom_readiness.py
Paste the WHOLE output back.
"""
SAMPLE_PROJECT = 250250
SAMPLE_MACHINE = 10
NAME_HINTS = ["bom", "readiness", "structur", "billofmaterial", "bill_of_material",
              "specitem", "spec_item", "assembly", "availab", "procure", "kitting", "kit"]


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


def run(cur, label, sql, params=None, cap=40):
    print(f"\n-- {label}\n   {' '.join(sql.split())[:300]}")
    try:
        cur.execute(sql, params) if params else cur.execute(sql)
        if cur.description is None:
            print("   (no result set)")
            return [], []
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


def main():
    eto = eto_connect()
    cur = eto.cursor()

    like = " OR ".join(f"LOWER(name) LIKE '%{h}%'" for h in NAME_HINTS)

    # ── A. Name-search every view / table / proc ─────────────────────────────────
    rule("A. OBJECTS whose name hints at BOM / readiness / structure / spec-item / procurement")
    run(cur, "A1. views + tables", f"""
        SELECT TABLE_TYPE, TABLE_NAME
        FROM INFORMATION_SCHEMA.TABLES
        WHERE {like}
        ORDER BY TABLE_TYPE, TABLE_NAME""", cap=200)
    run(cur, "A2. stored procedures / functions", f"""
        SELECT o.type_desc, o.name
        FROM sys.objects o
        WHERE o.type IN ('P','FN','IF','TF') AND ({like.replace('name','o.name')})
        ORDER BY o.type_desc, o.name""", cap=200)

    # ── B. Proc DEFINITIONS — the report proc names its own source tables ────────
    rule("B. DEFINITIONS of procs/functions that look like the report (source tables live here)")
    _, procs = run(cur, "B0. candidate proc names",
        f"""SELECT o.name FROM sys.objects o
            WHERE o.type IN ('P','FN','IF','TF')
              AND (LOWER(o.name) LIKE '%readiness%' OR LOWER(o.name) LIKE '%structur%bom%'
                   OR LOWER(o.name) LIKE '%bom%structur%' OR LOWER(o.name) LIKE '%bomreadiness%')
            ORDER BY o.name""", cap=50)
    for (nm,) in (procs or [])[:6]:
        run(cur, f"B. definition of {nm}",
            "SELECT m.definition FROM sys.sql_modules m "
            "JOIN sys.objects o ON o.object_id=m.object_id WHERE o.name = ?", (nm,), cap=1)

    # ── C. Candidate BOM-structure views: columns + sample for the sample job ────
    rule("C. COLUMNS of the most likely BOM-structure / availability views")
    _, cands = run(cur, "C0. best-guess candidate views",
        f"""SELECT TABLE_NAME FROM INFORMATION_SCHEMA.VIEWS
            WHERE (LOWER(TABLE_NAME) LIKE '%bom%' OR LOWER(TABLE_NAME) LIKE '%structur%'
                   OR LOWER(TABLE_NAME) LIKE '%specitem%' OR LOWER(TABLE_NAME) LIKE '%readiness%'
                   OR LOWER(TABLE_NAME) LIKE '%availab%')
            ORDER BY TABLE_NAME""", cap=60)
    for (nm,) in (cands or [])[:10]:
        cur2 = eto.cursor()
        try:
            cur2.execute("SELECT COLUMN_NAME, DATA_TYPE FROM INFORMATION_SCHEMA.COLUMNS "
                         "WHERE TABLE_NAME = ? ORDER BY ORDINAL_POSITION", (nm,))
            cc = cur2.fetchall()
            print(f"\n   >>> {nm}: " + ", ".join(f"{c[0]}({c[1]})" for c in cc))
            # if it carries a ProjectID, show a few rows for the sample job
            names = {c[0].lower() for c in cc}
            if "projectid" in names:
                run(cur, f"   sample rows of {nm} for Project {SAMPLE_PROJECT}",
                    f"SELECT TOP 12 * FROM dbo.{nm} WHERE ProjectID = ?", (SAMPLE_PROJECT,), cap=12)
        except Exception as e:
            print(f"   !! columns of {nm}: {e}")

    # ── D. How is a machine/assembly identified? spec / structure keys ───────────
    rule("D. SPEC / STRUCTURE tables carrying ProjectID (assembly tree keys, quantities)")
    run(cur, "D1. tables with ProjectID + a 'qty'/'parent'/'level' column",
        """SELECT c.TABLE_NAME, COUNT(*) AS Cols,
                  MAX(CASE WHEN LOWER(c.COLUMN_NAME) LIKE '%qty%' OR LOWER(c.COLUMN_NAME) LIKE '%quantit%' THEN c.COLUMN_NAME END) AS QtyCol,
                  MAX(CASE WHEN LOWER(c.COLUMN_NAME) LIKE '%parent%' OR LOWER(c.COLUMN_NAME) LIKE '%level%' OR LOWER(c.COLUMN_NAME) LIKE '%seq%' THEN c.COLUMN_NAME END) AS TreeCol
           FROM INFORMATION_SCHEMA.COLUMNS c
           WHERE c.TABLE_NAME IN (SELECT TABLE_NAME FROM INFORMATION_SCHEMA.COLUMNS WHERE LOWER(COLUMN_NAME)='projectid')
             AND (LOWER(c.TABLE_NAME) LIKE '%spec%' OR LOWER(c.TABLE_NAME) LIKE '%bom%'
                  OR LOWER(c.TABLE_NAME) LIKE '%structur%' OR LOWER(c.TABLE_NAME) LIKE '%item%'
                  OR LOWER(c.TABLE_NAME) LIKE '%part%')
           GROUP BY c.TABLE_NAME ORDER BY c.TABLE_NAME""", cap=120)

    eto.close()
    print("\nDONE — paste everything above.")


if __name__ == "__main__":
    main()
