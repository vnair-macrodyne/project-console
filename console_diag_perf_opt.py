"""
console_diag_perf_opt.py — find FAST, project-filtered replacements for the two slow ETO
rollup views (2026-08-03).

The dashboards are slow because two vendor views don't push the ProjectID filter down (1 project
≈ 22 projects, ~5s fixed):
    vwProjectActualsVSEstimates       (est hours + EstTotalMaterials + ActTotalMaterials)
    vwCostingSummed_ByProjectID       (Purchased / Inventory / Extra / Total materials)

We already know fast base sources for est HOURS (tblSpecHours, 0.04s) and committed PO (0.21s).
This probe times candidate FAST sources for the two things still coming from the slow views —
the MATERIAL BUDGET and the CONSUMPTION + P/I/P split — on a SINGLE project, and checks they
reconcile to the known-good numbers. READ-ONLY.

Known target — project 240154:
    EstTotalMaterials 3,699,504.60 · Consumption(ActTotalMaterials) 2,903,459.09
    Purchasing 2,870,408.22 · Inventory 32,996.87 · Payables 54.00

Run:  python console_diag_perf_opt.py   → paste the whole output.
"""
import time

PID = 240154


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


def timed(cur, label, sql, warm=True):
    """Run once (optional warm-up) then time a run; print time + the row(s)."""
    try:
        if warm:
            cur.execute(sql); cur.fetchall()
        t0 = time.perf_counter()
        cur.execute(sql)
        rows = cur.fetchall()
        dt = time.perf_counter() - t0
        cols = [d[0] for d in cur.description]
        val = ""
        if rows:
            val = "  ".join(f"{c}={rows[0][i]}" for i, c in enumerate(cols))
            if len(rows) > 1:
                val += f"   (+{len(rows)-1} rows)"
        print(f"  {dt:7.3f}s  {label}")
        if val:
            print(f"           {val}")
    except Exception as e:
        print(f"  {'ERR':>7}   {label}   [{type(e).__name__}] {e}")


def main():
    conn = eto_connect()
    cur = conn.cursor()
    print(f"single project = {PID}\n")

    print("== BASELINE (the slow rollup views) ==")
    timed(cur, "vwProjectActualsVSEstimates",
          f"SELECT ProjectID, EstTotalMaterials, ActTotalMaterials FROM dbo.vwProjectActualsVSEstimates "
          f"WHERE ProjectID = {PID}")
    timed(cur, "vwCostingSummed_ByProjectID",
          f"SELECT ProjectID, TotalPurchasedMaterials, TotalInventoryPulls, TotalExtraCosts, "
          f"TotalMaterials FROM dbo.vwCostingSummed_ByProjectID WHERE ProjectID = {PID}")

    print("\n== MATERIAL BUDGET candidates (target EstTotalMaterials = 3,699,504.60) ==")
    timed(cur, "SUM vwProjectMaterialActualVsEstimatesByItemCategory (Est & Act in one view)",
          "SELECT ProjectID, CAST(SUM(TotalMaterialEstimate) AS decimal(20,2)) AS EstMat, "
          "CAST(SUM(TotalMaterialActual) AS decimal(20,2)) AS ActMat "
          f"FROM dbo.vwProjectMaterialActualVsEstimatesByItemCategory WHERE ProjectID = {PID} "
          "GROUP BY ProjectID")

    print("\n== CONSUMPTION + P/I/P components (each project-filtered — are they fast?) ==")
    timed(cur, "vwCostingPurchasedMaterialsSummed_ByProjectID  (target 2,870,408.22)",
          f"SELECT ProjectID, PurchasedCostingValue FROM dbo.vwCostingPurchasedMaterialsSummed_ByProjectID "
          f"WHERE ProjectID = {PID}")
    timed(cur, "vwCostingInventoryPullsSummed_ByProjectID  (target 32,996.87)",
          f"SELECT ProjectID, InventoryCostingValue FROM dbo.vwCostingInventoryPullsSummed_ByProjectID "
          f"WHERE ProjectID = {PID}")
    timed(cur, "vwCostingExtraCostsSummed_ByProjectID  (target 54.00)",
          f"SELECT ProjectID, ExtraCostingValue FROM dbo.vwCostingExtraCostsSummed_ByProjectID "
          f"WHERE ProjectID = {PID}")

    print("\n== EST HOURS — the known-fast base source (for reference) ==")
    timed(cur, "tblSpecHours group by HourType",
          f"SELECT ProjectID, HourType, SUM(Hours) AS H FROM dbo.tblSpecHours WHERE ProjectID = {PID} "
          "GROUP BY ProjectID, HourType", warm=False)

    print("\n== ALL-PROJECT cost of the same components (fixed-cost check) ==")
    # if a component view is ALSO fixed-cost, one-project ≈ all-projects; if it scales, it pushes down
    timed(cur, "vwCostingPurchasedMaterialsSummed_ByProjectID — ALL projects",
          "SELECT COUNT(*) AS projects, CAST(SUM(PurchasedCostingValue) AS decimal(20,2)) AS total "
          "FROM dbo.vwCostingPurchasedMaterialsSummed_ByProjectID")
    timed(cur, "vwCostingInventoryPullsSummed_ByProjectID — ALL projects",
          "SELECT COUNT(*) AS projects, CAST(SUM(InventoryCostingValue) AS decimal(20,2)) AS total "
          "FROM dbo.vwCostingInventoryPullsSummed_ByProjectID")

    conn.close()
    print("\nDone. Paste the whole output.\n"
          "  • If the three component views (Purchased/Inventory/Extra) are each <~0.3s per project,\n"
          "    we replace vwCostingSummed with them and the P/I/P split stays.\n"
          "  • If vwProjectMaterialActualVsEstimatesByItemCategory is fast and its Est/Act sums hit\n"
          "    3,699,504.60 / 2,903,459.09, it replaces vwProjectActualsVSEstimates for material.\n"
          "  • Est hours already come from tblSpecHours. Net: drop BOTH slow views from the hot path.")


if __name__ == "__main__":
    main()
