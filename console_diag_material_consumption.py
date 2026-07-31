"""
console_diag_material_consumption.py — confirm the MATERIAL CONSUMPTION source (2026-07-31).

FINDING we're acting on: the dashboard's "Material %" is the COMMITTED (ordered) PO value =
ETO's "Purchasing" column ONLY. It ignores Inventory issues + Payables/Extra costs, so it reads
low vs ETO's "Material Costs Compared" report.

  Project 240154 (Iten Defense — 15,500T press), from the ETO report:
      Purchasing  2,870,408.22
      Inventory      32,996.87
      Payables           54.00
      TOTAL       2,903,459.09   ÷ Budget 3,699,504.60  = 78.48%
  Console scorecard today: Material Actual 2,870,371.63  → 77.6%  (= Purchasing only)

DECISION (owner, 2026-07-31): keep BOTH lenses on the dashboard —
  * Committed Spend      = Purchasing (committed PO value)      — the cash-out-the-door lens
  * Resource Consumption = Purchasing + Inventory + Payables    — the run-rate lens (HEADLINE)
Resource Consumption must tie to ETO's report (78.48% on 240154).

THIS PROBE confirms, read-only, before we change any financial code:
  A. which estimate view/column carries ActTotalMaterials (= Resource Consumption)
  B. for 240154 + every tracked project: EstTotalMaterials (budget), ActTotalMaterials
     (consumption), our committed PO sum, and the delta (should ≈ Inventory + Payables)
  C. which project-level COSTING view reproduces the exact Purchasing / Inventory / Payables
     split (so the two lenses tie to the penny and we can show the breakdown)

Run on the box:  python console_diag_material_consumption.py
Paste the WHOLE output back. Nothing is written.
"""

PRIMARY = 240154
EXPECT = {"purchasing": 2870408.22, "inventory": 32996.87, "payables": 54.00,
          "total": 2903459.09, "budget": 3699504.60, "pct": 0.7848}

# Estimate/actual rollup views that may carry ActTotalMaterials.
EST_VIEWS = ["vwProjectActualsVSEstimates",
             "vwProjectActualsVSEstimates_LaborAndMaterials"]

# Project-level costing views that (by analogy to the verified _ByNC family) should carry the
# Purchasing / Inventory / Payables(Extra) split per project.
COSTING_VIEWS = ["vwCostingSummed_ByProjectID",
                 "vwCostingPurchasedMaterialsSummed_ByProjectID",
                 "vwCostingInventoryPullsSummed_ByProjectID",
                 "vwCostingExtraCostsSummed_ByProjectID",
                 "vwProjectMaterialActualVsEstimatesByItemCategory"]


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


def tracked_ids(max_n=400):
    """Tracked project ids from the Console reporting store (best-effort)."""
    try:
        from console.infra.connections import console_connection
        c = console_connection()
        cur = c.cursor()
        cur.execute("SELECT DISTINCT ProjectID FROM Reporting.vw_Console_BudgetCurrent ORDER BY ProjectID")
        ids = [int(r[0]) for r in cur.fetchall()][:max_n]
        c.close()
        return ids
    except Exception as e:
        print(f"  [note] could not read tracked ids ({type(e).__name__}: {e}); using [{PRIMARY}] only")
        return [PRIMARY]


def rule(t):
    print("\n" + "=" * 78 + f"\n{t}\n" + "=" * 78)


def run(cur, label, sql, params=(), max_rows=20):
    print("\n" + "-" * 78 + f"\n{label}\n" + "-" * 78)
    try:
        cur.execute(sql, params)
        while cur.description is None and cur.nextset():
            pass
        if cur.description is None:
            print("  (executed OK, no result set)")
            return
        cols = [d[0] for d in cur.description]
        rows = cur.fetchall()
        print("  " + " | ".join(cols))
        for r in rows[:max_rows]:
            print("  " + " | ".join("" if v is None else str(v) for v in r))
        if len(rows) > max_rows:
            print(f"  ... (+{len(rows) - max_rows} more rows)")
        if not rows:
            print("  (0 rows)")
    except Exception as e:
        print(f"  [ERROR] {type(e).__name__}: {e}")


def committed_sql(idlist):
    """Our current 'Material Actual' = committed PO value in CAD (the number to KEEP as
    Committed Spend)."""
    return (
        "SELECT pod.ProjectID AS ProjectID, "
        "CAST(SUM(pod.ExtendedPrice * CASE WHEN poh.PurchaseCurrRate > 0 "
        "     THEN poh.PurchaseCurrRate ELSE 1 END) AS decimal(20,2)) AS CommittedCAD "
        "FROM dbo.vwPurchaseOrderDetails pod "
        "JOIN dbo.vwPurchaseOrderHeader poh ON poh.PurchaseOrderID = pod.PurchaseOrderID "
        f"WHERE pod.ProjectID IN ({idlist}) AND poh.PurchaseActive = 1 "
        "GROUP BY pod.ProjectID")


def main():
    conn = eto_connect()
    cur = conn.cursor()
    ids = tracked_ids()
    if PRIMARY not in ids:
        ids = [PRIMARY] + ids
    idlist = ",".join(str(i) for i in ids)
    try:
        # ── A. Where does ActTotalMaterials live? ────────────────────────────────
        rule("A. ESTIMATE/ACTUAL VIEWS — is ActTotalMaterials present, and readable?")
        for v in EST_VIEWS:
            run(cur, f"A/{v} — material columns",
                "SELECT COLUMN_NAME, DATA_TYPE FROM INFORMATION_SCHEMA.COLUMNS "
                "WHERE TABLE_NAME = ? AND (COLUMN_NAME LIKE '%Material%' OR COLUMN_NAME LIKE '%Mat%') "
                "ORDER BY ORDINAL_POSITION", (v,))

        # ── B. 240154 headline reconciliation ────────────────────────────────────
        rule(f"B. PROJECT {PRIMARY} — budget / consumption / committed reconciliation")
        print(f"  EXPECT  Budget={EXPECT['budget']:,.2f}  Consumption(Total)={EXPECT['total']:,.2f}"
              f"  Purchasing={EXPECT['purchasing']:,.2f}  Inv={EXPECT['inventory']:,.2f}"
              f"  Pay={EXPECT['payables']:,.2f}  Consumption%={EXPECT['pct']*100:.2f}%")
        run(cur, "B1. vwProjectActualsVSEstimates — Est vs Act total materials",
            "SELECT ProjectID, EstTotalMaterials, ActTotalMaterials "
            f"FROM dbo.vwProjectActualsVSEstimates WHERE ProjectID = {PRIMARY}")
        run(cur, "B2. vwProjectActualsVSEstimates_LaborAndMaterials — Est vs Act total materials",
            "SELECT ProjectID, EstTotalMaterials, ActTotalMaterials "
            f"FROM dbo.vwProjectActualsVSEstimates_LaborAndMaterials WHERE ProjectID = {PRIMARY}")
        run(cur, "B3. our COMMITTED PO value (CAD) — the Committed Spend lens",
            committed_sql(str(PRIMARY)))

        # ── C. Project-level costing split (Purchasing / Inventory / Payables) ────
        rule(f"C. COSTING VIEWS — the exact P/I/P split for {PRIMARY}")
        for v in COSTING_VIEWS:
            run(cur, f"C/{v} — columns",
                "SELECT COLUMN_NAME, DATA_TYPE FROM INFORMATION_SCHEMA.COLUMNS "
                "WHERE TABLE_NAME = ? ORDER BY ORDINAL_POSITION", (v,))
            run(cur, f"C/{v} — scoped row(s) for {PRIMARY}",
                f"SELECT * FROM dbo.{v} WHERE ProjectID = {PRIMARY}")

        # ── D. Portfolio sweep — consumption vs committed for every tracked project ─
        rule("D. TRACKED PROJECTS — Est material / Act material (consumption) / committed / delta")
        run(cur, "D1. estimate-view actuals vs our committed (delta ≈ inventory + payables)",
            "SELECT e.ProjectID, "
            "CAST(e.EstTotalMaterials AS decimal(20,2)) AS EstMaterial, "
            "CAST(e.ActTotalMaterials AS decimal(20,2)) AS Consumption, "
            "cm.CommittedCAD AS Committed, "
            "CAST(e.ActTotalMaterials - ISNULL(cm.CommittedCAD,0) AS decimal(20,2)) AS Delta "
            "FROM dbo.vwProjectActualsVSEstimates e "
            f"LEFT JOIN ({committed_sql(idlist)}) cm ON cm.ProjectID = e.ProjectID "
            f"WHERE e.ProjectID IN ({idlist}) ORDER BY e.ProjectID", max_rows=400)

    finally:
        conn.close()
    print("\nDone. Paste the whole output back.\n"
          "  • B: which of B1/B2 shows ActTotalMaterials = 2,903,459.09 is the Consumption source.\n"
          "  • C: the costing view whose columns foot to Purchasing 2,870,408.22 / Inventory\n"
          "       32,996.87 / Payables 54.00 gives us the exact split (for the breakdown).\n"
          "  • D: sanity — Consumption ≥ Committed on every project; Delta = inventory + payables.")


if __name__ == "__main__":
    main()
