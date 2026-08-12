"""
console_diag_material_budget.py — reconcile 250250's BUDGET to ETO's own sources (2026-08-12).

Context: the labour budget hours already reconcile to ETO's "All Departments - Project Status Report"
exactly (PM=Admin, Mech+Elec+Hyd=Engineering, Mfg, total 5,841). The number in question is the
MATERIAL budget the Console shows ($1,916,772). Console currently sources material from ETO's
`EstTotalMaterials`; this probe pulls EVERY ETO material-estimate view for the project so we can see
which one is authoritative and which reproduces the displayed figure — and confirms the labour $
(the report's BCost) at the same time.

READ-ONLY. Run:
    python console_diag_material_budget.py            # defaults to 250250
    python console_diag_material_budget.py 230219     # any project
"""
import sys

MAT_HINTS = ("material", "totalmaterial", "estmaterial", "esttotal", "purchas", "estimate", "extended")
EST_VIEWS = ["vwProjectActualsVSEstimates", "vwProjectActualsVSEstimates_LaborAndMaterials",
             "vwProjectEstimate", "vwProjectMaterialEstimateByItemCategory",
             "vwProjectMaterialActualVsEstimatesByItemCategory", "vwProjectSalesPrice",
             "vwSpecLaborEstimateByHourType"]


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


def run(cur, label, sql, params=(), max_rows=60):
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


def has_col(cur, table, col):
    return any(n.lower() == col.lower() for n, _ in columns_of(cur, table))


def main():
    pid = 250250
    if len(sys.argv) > 1:
        try:
            pid = int(sys.argv[1])
        except ValueError:
            pass
    conn = eto_connect()
    cur = conn.cursor()
    print(f"Project: {pid}")
    try:
        # ── A. LABOUR budget — reproduce the report's BHrs (5,841) and BCost ($511,295) ──
        rule("A. LABOUR BUDGET from tblSpecHours (should reproduce the report's 5,841 hrs)")
        run(cur, "A1. total estimate hours (all spec-hours rows = ETO headline estimate)",
            "SELECT ProjectID, COUNT(*) AS rows_, SUM(Hours) AS BudgetHours "
            f"FROM dbo.tblSpecHours WHERE ProjectID = {pid} GROUP BY ProjectID")
        run(cur, "A2. labour $ estimate by hour type (SUM Extended = the report's BCost)",
            "SELECT ProjectID, SUM(Extended) AS LabourBudgetCost "
            f"FROM dbo.vwSpecLaborEstimateByHourType WHERE ProjectID = {pid} GROUP BY ProjectID")

        # ── B. every MATERIAL-estimate view: columns (material cols flagged) + value ──────
        rule("B. MATERIAL-ESTIMATE CANDIDATES (◆ = a material/estimate column)")
        for v in EST_VIEWS:
            cols = columns_of(cur, v)
            if not cols:
                print(f"\n  {v}: (view not found)")
                continue
            print(f"\n  {v} ({len(cols)} cols):")
            matcols = []
            for n, t in cols:
                nl = n.lower()
                mark = "  ◆" if any(h in nl for h in MAT_HINTS) else ""
                if mark:
                    matcols.append(n)
                print(f"    {n} : {t}{mark}")
            # scoped value(s) for this project
            if has_col(cur, v, "ProjectID"):
                run(cur, f"  → {v} rows for project {pid}",
                    f"SELECT * FROM dbo.{v} WHERE ProjectID = {pid}", max_rows=40)

        # ── C. material estimate by item category, summed (the build-up of the number) ───
        rule("C. MATERIAL ESTIMATE BY ITEM CATEGORY — total + breakdown")
        if has_col(cur, "vwProjectMaterialEstimateByItemCategory", "ProjectID"):
            catcols = [n for n, _ in columns_of(cur, "vwProjectMaterialEstimateByItemCategory")]
            amt = next((c for c in catcols if any(h in c.lower()
                        for h in ("estimate", "amount", "material", "extended", "total"))), None)
            run(cur, "C1. total material estimate for the project (sum over categories)",
                f"SELECT ProjectID, COUNT(*) AS cats, SUM([{amt}]) AS MaterialEstimate "
                f"FROM dbo.vwProjectMaterialEstimateByItemCategory WHERE ProjectID = {pid} "
                "GROUP BY ProjectID" if amt else
                f"SELECT TOP 40 * FROM dbo.vwProjectMaterialEstimateByItemCategory WHERE ProjectID = {pid}")
            run(cur, "C2. by category",
                f"SELECT TOP 60 * FROM dbo.vwProjectMaterialEstimateByItemCategory "
                f"WHERE ProjectID = {pid}")
    finally:
        conn.close()
    print("\nDone. Paste the whole output.\n"
          "  • A should reproduce 5,841 hrs and ~$511,295 (confirms labour source is right).\n"
          "  • B: each candidate view's material-estimate value for the project — the one that reads\n"
          "    $1,916,772 is what the Console shows today; note any that ETO itself treats as the\n"
          "    budget (e.g. EstTotalMaterials vs the item-category build-up).\n"
          "  • C: the category build-up — its total is the 'true' bottom-up material estimate.\n"
          "Tell me which figure ETO regards as the material budget and I'll repoint the Console at it.")


if __name__ == "__main__":
    main()
