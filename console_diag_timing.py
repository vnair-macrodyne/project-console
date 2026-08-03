"""
console_diag_timing.py — where does the time go? (2026-08-03)

Times each report end-to-end AND the individual heavy ETO sub-queries, using the live service,
so we optimise the actual bottleneck instead of guessing. READ-ONLY.

Run on the app host (env set like the app):  python console_diag_timing.py
Paste the whole output back.
"""
import time


def _t(label, fn):
    t0 = time.perf_counter()
    err = None
    n = None
    try:
        r = fn()
        n = (len(r.rows) if hasattr(r, "rows") else (len(r) if hasattr(r, "__len__") else None))
    except Exception as e:
        err = f"{type(e).__name__}: {e}"
    dt = time.perf_counter() - t0
    tag = f"{dt:7.2f}s  {label}"
    if n is not None:
        tag += f"   ({n} rows)"
    if err:
        tag += f"   [ERROR] {err}"
    print(tag)
    return dt


def tracked_ids():
    from console.infra.connections import console_connection
    c = console_connection()
    cur = c.cursor()
    cur.execute("SELECT DISTINCT ProjectID FROM Reporting.vw_Console_BudgetCurrent ORDER BY ProjectID")
    ids = [int(r[0]) for r in cur.fetchall()]
    c.close()
    return ids


def main():
    from console_web.queries import LiveQueryService
    ids = tracked_ids()
    one = ids[:1]
    print(f"tracked projects: {len(ids)}   (also timing a single-project run)\n")

    print("== connection warm-up ==")
    svc = LiveQueryService()
    _t("open ETO + store, load crosswalk/maps (first _financials)",
       lambda: svc._financials(one))

    print("\n== REPORTS (full tracked scope) — end to end ==")
    reports = ["exec", "scorecard", "discipline", "budget_actual",
               "po_status", "po_to_order", "item_location", "nc_costs", "po_all"]
    times = {}
    for qid in reports:
        s2 = LiveQueryService()   # fresh service per report = realistic per-request cost
        times[qid] = _t(qid, lambda q=qid, s=s2: s.run(q, ids))

    print("\n== same reports, SINGLE project (does it scale with project count?) ==")
    for qid in ("exec", "scorecard", "item_location", "po_to_order"):
        s2 = LiveQueryService()
        _t(f"{qid} [1 proj]", lambda q=qid, s=s2: s.run(q, one))

    print("\n== heavy ETO SUB-QUERIES in isolation (full scope) ==")
    s = LiveQueryService()
    idlist = ",".join(str(i) for i in ids)
    subs = {
        "material: vwCostingSummed_ByProjectID":
            f"SELECT ProjectID, TotalPurchasedMaterials, TotalInventoryPulls, TotalExtraCosts, "
            f"TotalMaterials FROM dbo.vwCostingSummed_ByProjectID WHERE ProjectID IN ({idlist})",
        "budget: vwProjectActualsVSEstimates":
            f"SELECT ProjectID, EstAdminHours, EstEngHours, EstMfgHours, EstTotalMaterials, "
            f"ActTotalMaterials FROM dbo.vwProjectActualsVSEstimates WHERE ProjectID IN ({idlist})",
        "budget detail: tblSpecHours group":
            f"SELECT ProjectID, HourType, SUM(Hours) FROM dbo.tblSpecHours "
            f"WHERE ProjectID IN ({idlist}) GROUP BY ProjectID, HourType",
        "actuals: vwTimecards group":
            f"SELECT ProjectID, HourDescription, SUM(HourTime) FROM dbo.vwTimecards "
            f"WHERE ProjectID IN ({idlist}) GROUP BY ProjectID, HourDescription",
        "item_location scope: DISTINCT PO items":
            f"SELECT DISTINCT ProjectID, ItemID FROM dbo.vwPurchaseOrderDetails "
            f"WHERE ProjectID IN ({idlist}) AND ItemID IS NOT NULL",
        "item_location join: vwInventory":
            f"SELECT pi.ProjectID, inv.ItemCompanyID, inv.LocationName, inv.QtyOnHand "
            f"FROM (SELECT DISTINCT ProjectID, ItemID FROM dbo.vwPurchaseOrderDetails "
            f"WHERE ProjectID IN ({idlist}) AND ItemID IS NOT NULL) pi "
            f"JOIN dbo.vwInventory inv ON inv.ItemID = pi.ItemID WHERE inv.QtyOnHand > 0",
        "po committed sum: vwPurchaseOrderDetails":
            f"SELECT pod.ProjectID, SUM(pod.ExtendedPrice) FROM dbo.vwPurchaseOrderDetails pod "
            f"JOIN dbo.vwPurchaseOrderHeader poh ON poh.PurchaseOrderID = pod.PurchaseOrderID "
            f"WHERE pod.ProjectID IN ({idlist}) GROUP BY pod.ProjectID",
    }
    for label, sql in subs.items():
        _t(label, lambda q=sql: s._df(q))

    print("\nDone. Paste the whole output.\n"
          "  • Compare the report totals to the sub-query times — the biggest sub-query is the target.\n"
          "  • If single-project ≈ full-scope, the cost is per-view overhead (cache it), not row volume.\n"
          "  • Watch the material costing view — it was added recently and may dominate the dashboards.")


if __name__ == "__main__":
    main()
