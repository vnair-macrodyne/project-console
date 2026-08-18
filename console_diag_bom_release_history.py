"""
console_diag_bom_release_history.py — released-material feasibility off tblBOMReleaseHistory (2026-08-14)

The release DATE lives in **tblBOMReleaseHistory** (ProjectID, SpecID, ItemID, ReleasedDateTime,
QuantityChange, Type, ReleasedByEmployeeID, Old/NewRequiredDate) — a per-item release-event log.
(BOMAssemblyReleaseID / tsysBOMAssemblyRelease is only a 3-row lookup — NOT the released flag; the
first costing probe used it wrongly, ignore its 82-line / $70k numbers.)

This probe rebuilds the released-material feasibility on the CORRECT basis — the release log gives us
released item + released QUANTITY + release DATE directly, so we don't need to explode the BOM:

  A. LOG SHAPE for the project — rows, distinct items/specs, date span, Type/QuantityChange mix.
  B. PER-ITEM released qty (net ΣQuantityChange) + first/last release date (sample).
  C. RELEASE TIMELINE — items & qty released per month (the maturity dial over time).
  D. PRICE COVERAGE — released items priced from PO history vs item-master fallback vs nothing.
  E. SHOULD-COST + RECONCILE — Σ(net released qty × best unit) vs actual materials
     (vwCostingSummed_ByProjectID) and vs committed POs.
  F. RELEASED vs ORDERED — released items already on a PO vs still-to-buy (+ value).

READ-ONLY.  Run:  python console_diag_bom_release_history.py [projectID]   (default 240040) → paste.
Run it for an early, a mid and a near-done job so we see the should-cost firm up toward actuals.
"""
import sys

REL = "tblBOMReleaseHistory"


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


def run(cur, label, sql, max_rows=30):
    print("\n" + "-" * 78 + f"\n{label}\n" + "-" * 78)
    try:
        cur.execute(sql)
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

    # per-item historical unit price from PO lines (any project), + per-item cost fallback from the BOM
    hist = ("(SELECT pod.ItemID, "
            "        AVG(CASE WHEN pod.PurchaseQty > 0 THEN pod.ExtendedPrice / pod.PurchaseQty END) AS hist_unit, "
            "        COUNT(*) AS po_lines "
            " FROM dbo.vwPurchaseOrderDetails pod WHERE pod.ItemID IS NOT NULL GROUP BY pod.ItemID)")
    cost = (f"(SELECT ItemID, MAX(CAST(ItemLastCost AS float)) AS lastc, "
            f"        MAX(CAST(ItemListCost AS float)) AS listc "
            f" FROM dbo.vwEngBOM WHERE ProjectID = {pid} GROUP BY ItemID)")
    # released net qty per item for this project
    rel_item = (f"(SELECT ItemID, SUM(CAST(QuantityChange AS float)) AS net_qty, "
                f"        MIN(ReleasedDateTime) AS first_rel, MAX(ReleasedDateTime) AS last_rel, "
                f"        COUNT(*) AS events "
                f" FROM dbo.{REL} WHERE ProjectID = {pid} GROUP BY ItemID)")

    try:
        # ── A. log shape ─────────────────────────────────────────────────────────
        rule("A. tblBOMReleaseHistory shape for the project")
        run(cur, "A1. rows / items / specs / date span",
            f"SELECT COUNT(*) AS rows_, COUNT(DISTINCT ItemID) AS items, COUNT(DISTINCT SpecID) AS specs, "
            f"  MIN(CAST(ReleasedDateTime AS date)) AS first_release, "
            f"  MAX(CAST(ReleasedDateTime AS date)) AS last_release "
            f"FROM dbo.{REL} WHERE ProjectID = {pid}")
        run(cur, "A2. event Type mix (what QuantityChange means)",
            f"SELECT Type, COUNT(*) AS events, "
            f"  CAST(SUM(CAST(QuantityChange AS float)) AS decimal(18,2)) AS sum_qty_change "
            f"FROM dbo.{REL} WHERE ProjectID = {pid} GROUP BY Type ORDER BY events DESC")

        # ── B. per-item released qty + dates ────────────────────────────────────
        rule("B. PER-ITEM net released qty + first/last release date (top 30 by qty)")
        run(cur, "B1.",
            f"SELECT TOP 30 r.ItemID, im.ItemCompanyID, "
            f"  CAST(r.net_qty AS decimal(18,2)) AS net_qty, CAST(r.first_rel AS date) AS first_rel, "
            f"  CAST(r.last_rel AS date) AS last_rel, r.events "
            f"FROM {rel_item} r "
            f"LEFT JOIN dbo.vwEngBOM im ON im.ItemID = r.ItemID AND im.ProjectID = {pid} "
            f"WHERE r.net_qty <> 0 ORDER BY r.net_qty DESC")

        # ── C. release timeline (maturity dial) ─────────────────────────────────
        rule("C. RELEASE TIMELINE — items touched + qty released per month")
        run(cur, "C1.",
            f"SELECT CONVERT(char(7), ReleasedDateTime, 126) AS ym, "
            f"  COUNT(DISTINCT ItemID) AS items_touched, "
            f"  CAST(SUM(CAST(QuantityChange AS float)) AS decimal(18,2)) AS qty_released "
            f"FROM dbo.{REL} WHERE ProjectID = {pid} GROUP BY CONVERT(char(7), ReleasedDateTime, 126) "
            f"ORDER BY ym")

        # ── D. price coverage on the released item set ──────────────────────────
        rule("D. PRICE COVERAGE — released items (net qty > 0): PO history vs fallback vs none")
        run(cur, "D1.",
            f"SELECT COUNT(*) AS released_items, "
            f"  SUM(CASE WHEN h.hist_unit IS NOT NULL THEN 1 ELSE 0 END) AS priced_from_PO_history, "
            f"  SUM(CASE WHEN h.hist_unit IS NULL AND ISNULL(c.lastc,0) > 0 THEN 1 ELSE 0 END) AS fb_lastcost, "
            f"  SUM(CASE WHEN h.hist_unit IS NULL AND ISNULL(c.lastc,0) = 0 AND ISNULL(c.listc,0) > 0 THEN 1 ELSE 0 END) AS fb_listcost, "
            f"  SUM(CASE WHEN h.hist_unit IS NULL AND ISNULL(c.lastc,0) = 0 AND ISNULL(c.listc,0) = 0 THEN 1 ELSE 0 END) AS no_price "
            f"FROM {rel_item} r "
            f"LEFT JOIN {hist} h ON h.ItemID = r.ItemID "
            f"LEFT JOIN {cost} c ON c.ItemID = r.ItemID "
            f"WHERE r.net_qty > 0")
        run(cur, "D2. same, but WEIGHTED by value (share of $ we can price from real history)",
            f"SELECT "
            f"  CAST(SUM(r.net_qty * COALESCE(h.hist_unit, NULLIF(c.lastc,0), NULLIF(c.listc,0), 0)) AS decimal(18,2)) AS total_should_cost, "
            f"  CAST(SUM(CASE WHEN h.hist_unit IS NOT NULL THEN r.net_qty * h.hist_unit ELSE 0 END) AS decimal(18,2)) AS from_PO_history, "
            f"  CAST(SUM(CASE WHEN h.hist_unit IS NULL THEN r.net_qty * COALESCE(NULLIF(c.lastc,0), NULLIF(c.listc,0),0) ELSE 0 END) AS decimal(18,2)) AS from_fallback "
            f"FROM {rel_item} r "
            f"LEFT JOIN {hist} h ON h.ItemID = r.ItemID "
            f"LEFT JOIN {cost} c ON c.ItemID = r.ItemID "
            f"WHERE r.net_qty > 0")

        # ── E. should-cost + reconcile ──────────────────────────────────────────
        rule("E. RECONCILE — released should-cost  vs  actual materials  vs  committed POs")
        run(cur, "E1. released-material should-cost (net qty × best unit)",
            f"SELECT CAST(SUM(r.net_qty * COALESCE(h.hist_unit, NULLIF(c.lastc,0), NULLIF(c.listc,0),0)) "
            f"            AS decimal(18,2)) AS released_should_cost, COUNT(*) AS items "
            f"FROM {rel_item} r "
            f"LEFT JOIN {hist} h ON h.ItemID = r.ItemID "
            f"LEFT JOIN {cost} c ON c.ItemID = r.ItemID WHERE r.net_qty > 0")
        run(cur, "E2. actual materials (vwCostingSummed_ByProjectID)",
            f"SELECT ProjectID, TotalPurchasedMaterials, TotalInventoryPulls, TotalMaterials "
            f"FROM dbo.vwCostingSummed_ByProjectID WHERE ProjectID = {pid}")
        run(cur, "E3. committed POs (active) for the project",
            f"SELECT CAST(SUM(pod.ExtendedPrice) AS decimal(18,2)) AS committed, COUNT(*) AS po_lines "
            f"FROM dbo.vwPurchaseOrderHeader poh "
            f"JOIN dbo.vwPurchaseOrderDetails pod ON pod.PurchaseOrderID = poh.PurchaseOrderID "
            f"WHERE poh.PurchaseActive = 1 AND pod.ProjectID = {pid}")

        # ── F. released vs ordered ──────────────────────────────────────────────
        rule("F. RELEASED items — already on a PO vs still-to-buy (+ value at best unit)")
        run(cur, "F1.",
            f"WITH ordered AS (SELECT DISTINCT ItemID FROM dbo.vwPurchaseOrderDetails WHERE ProjectID = {pid}) "
            f"SELECT "
            f"  SUM(CASE WHEN o.ItemID IS NOT NULL THEN 1 ELSE 0 END) AS already_ordered, "
            f"  SUM(CASE WHEN o.ItemID IS NULL THEN 1 ELSE 0 END) AS still_to_buy, "
            f"  CAST(SUM(CASE WHEN o.ItemID IS NULL THEN r.net_qty * COALESCE(h.hist_unit, NULLIF(c.lastc,0), NULLIF(c.listc,0),0) ELSE 0 END) "
            f"       AS decimal(18,2)) AS still_to_buy_value "
            f"FROM {rel_item} r "
            f"LEFT JOIN ordered o ON o.ItemID = r.ItemID "
            f"LEFT JOIN {hist} h ON h.ItemID = r.ItemID "
            f"LEFT JOIN {cost} c ON c.ItemID = r.ItemID WHERE r.net_qty > 0")
    finally:
        conn.close()
    print("\nDone. Paste the whole output. How to read it:\n"
          "  • A/B = the release log per item: date + released quantity, straight from ETO.\n"
          "  • C = the maturity dial — how release built up over the job's life.\n"
          "  • D = MAKE-OR-BREAK: share of released $ we can price from real PO history (D2 weighted).\n"
          "  • E = does released-should-cost land near actual materials (~$541.7k on 240040) and\n"
          "    committed? For a fully-released job it should; for an early one it'll be lower.\n"
          "  • F = of the released items, what's still to buy — the forward $ the projection adds.\n"
          "  Run early/mid/near-done. If D2 shows most $ priced from history and E reconciles, build it.")


if __name__ == "__main__":
    main()
