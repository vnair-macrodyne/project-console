"""
console_diag_project_type.py -- find the ETO field that holds a project's TYPE / CATEGORY
(Forging, Compression Molding (SMC), Metalforming, Mechanical Retrofits, ...) so the new
"Project Types" report can read it live.  READ-ONLY.  Nothing is written.  (2026-10-29)

Background: the attached sheet (ETO_Project_Types_20260917.xlsx) tags each project with a
"Draft Category Name" grouped into 7 Category Groups. Vijay says this lives in an ETO field.
This probe locates it and shows whether its raw values match the 26 category labels or need a
small normalization map.

Run from the repo root:   python console_diag_project_type.py
Paste the WHOLE output back.
"""
import sys


def eto_connect():
    try:
        from console_store import eto_connection
        return eto_connection()
    except Exception:
        import os, pyodbc
        from console_config import TENANT
        cs = (f"Driver={{ODBC Driver 17 for SQL Server}};Server={TENANT.eto_server};"
              f"Database={TENANT.eto_database};Trusted_Connection=yes;TrustServerCertificate=yes;")
        return pyodbc.connect(cs, timeout=30)


TAXONOMY = [
    "Press", "Compression Molding (SMC)", "Mechanical Retrofits", "Metalforming",
    "Hydroforming / SPF", "Hot Stamping / Heated Platen", "Extrusion", "Draw / Deep Draw",
    "Press Lines / Cells", "Non-Standard / Other", "Forging", "Specialty Presses",
    "Prototype / Testing", "Simulation & Process Dev", "Pulp Bailing Press", "Material Handling",
    "Auxiliary Systems", "Automation Systems", "R&D / Internal Projects", "Engineering Studies",
    "Controls Retrofits", "Blanking Press", "Stretch Forming", "Warranty Work",
    "Thermal Systems", "Assembly Press",
]
TAXO_LC = {t.lower() for t in TAXONOMY}

SAMPLE = {
    111163: "Forging", 121432: "Press", 141614: "Metalforming",
    141615: "Compression Molding (SMC)", 161665: "Metalforming", 161672: "Warranty Work",
    161674: "Mechanical Retrofits", 161679: "Compression Molding (SMC)", 161682: "Press",
    161689: "Hot Stamping / Heated Platen", 171726: "Compression Molding (SMC)",
    171731: "Blanking Press", 171738: "Material Handling", 171740: "Press Lines / Cells",
    181784: "Extrusion", 181785: "Auxiliary Systems",
}

CAND_HINTS = ["type", "categ", "class", "product", "press", "group", "line", "kind", "segment"]


def q(cur, sql):
    cur.execute(sql)
    cols = [d[0] for d in cur.description]
    return cols, cur.fetchall()


def main():
    eto = eto_connect()
    cur = eto.cursor()

    print("=" * 78); print("A. tblProjects columns"); print("=" * 78)
    cand = []
    try:
        cols, rows = q(cur, """
            SELECT COLUMN_NAME, DATA_TYPE, CHARACTER_MAXIMUM_LENGTH
            FROM INFORMATION_SCHEMA.COLUMNS WHERE TABLE_NAME='tblProjects'
            ORDER BY ORDINAL_POSITION""")
        for name, dt, ln in rows:
            flag = ""; nl = name.lower()
            if any(h in nl for h in CAND_HINTS) or "custom" in nl:
                flag = "   <-- candidate"; cand.append(name)
            print(f"  {name:32s} {dt}{('('+str(ln)+')') if ln else ''}{flag}")
    except Exception as e:
        print("  ERROR:", e)
    print("\n  candidate columns:", cand)

    print("\n" + "=" * 78)
    print("B. caption registry entries mentioning project/type/category/product/press/...")
    print("=" * 78)
    HINT = ["project", "type", "categ", "product", "press", "class", "group", "line", "segment", "kind"]
    for obj in ("vwCaption", "tlkpCaption"):
        try:
            cols, rows = q(cur, f"SELECT TOP 2000 * FROM {obj}")
            print(f"\n  -- {obj} (cols: {cols}) --")
            hit = 0
            for r in rows:
                blob = " ".join("" if v is None else str(v) for v in r).lower()
                if any(h in blob for h in HINT):
                    print("   ", dict(zip(cols, r))); hit += 1
                    if hit >= 60:
                        print("    ... (truncated)"); break
            if not hit:
                print("    (no matching rows)")
        except Exception as e:
            print(f"  {obj}: ERROR {e}")

    print("\n" + "=" * 78)
    print("C. lookup tables named like Type/Category/Class/Product/Group + their rows")
    print("=" * 78)
    try:
        cols, rows = q(cur, """
            SELECT TABLE_NAME FROM INFORMATION_SCHEMA.TABLES
            WHERE TABLE_TYPE IN ('BASE TABLE','VIEW')
              AND (TABLE_NAME LIKE '%Type%' OR TABLE_NAME LIKE '%Categ%'
                   OR TABLE_NAME LIKE '%Class%' OR TABLE_NAME LIKE '%Product%'
                   OR TABLE_NAME LIKE '%Group%' OR TABLE_NAME LIKE '%Segment%')
            ORDER BY TABLE_NAME""")
        names = [r[0] for r in rows]
        print("  tables:", names)
        for t in names:
            nl = t.lower()
            if not any(k in nl for k in ("projecttype", "projectcateg", "projectclass",
                                         "producttype", "productline", "projectgroup",
                                         "jobtype", "machinetype")):
                continue
            try:
                c2, r2 = q(cur, f"SELECT TOP 80 * FROM {t}")
                print(f"\n  -- {t} (cols {c2}) {len(r2)} rows --")
                for r in r2:
                    print("   ", tuple(r))
            except Exception as e:
                print(f"    {t}: ERROR {e}")
    except Exception as e:
        print("  ERROR:", e)

    print("\n" + "=" * 78)
    print("D. distinct values of each candidate column on tblProjects (+ taxonomy match)")
    print("=" * 78)
    for col in cand:
        try:
            cur.execute(f"SELECT [{col}] AS v, COUNT(*) AS n FROM dbo.tblProjects "
                        f"GROUP BY [{col}] ORDER BY n DESC")
            rows = cur.fetchall()
            matched = sum(1 for v, n in rows if v is not None and str(v).strip().lower() in TAXO_LC)
            nonnull = sum(n for v, n in rows if v is not None and str(v).strip() != "")
            print(f"\n  [{col}] -- {len(rows)} distinct, {nonnull} non-blank rows, "
                  f"{matched} distinct values match the 26 taxonomy labels")
            for v, n in rows[:40]:
                star = "  *taxo" if (v is not None and str(v).strip().lower() in TAXO_LC) else ""
                print(f"      {n:5d}  {v!r}{star}")
        except Exception as e:
            print(f"  [{col}]: ERROR {e}")

    print("\n" + "=" * 78)
    print("E. cross-check: 16 known projects -- candidate values vs sheet category")
    print("=" * 78)
    ids = ",".join(str(i) for i in SAMPLE)
    try:
        sel = ", ".join(f"[{c}]" for c in cand) if cand else "*"
        cols, rows = q(cur, f"SELECT ProjectID, {sel} FROM dbo.tblProjects "
                            f"WHERE ProjectID IN ({ids})")
        idx = {r[0]: r for r in rows}
        print(f"  (candidate cols shown: {cand})\n")
        for pid in SAMPLE:
            r = idx.get(pid)
            if r is None:
                print(f"  {pid}: (not found in tblProjects)   sheet={SAMPLE[pid]!r}"); continue
            vals = dict(zip(cols, r))
            print(f"  {pid}: sheet={SAMPLE[pid]!r}")
            for c in cand:
                print(f"        {c} = {vals.get(c)!r}")
    except Exception as e:
        print("  ERROR:", e)

    eto.close()
    print("\n--- done ---")


if __name__ == "__main__":
    main()
