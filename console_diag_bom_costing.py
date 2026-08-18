"""
console_diag_bom_costing.py — feasibility of a RELEASED-BOM, historically-costed material projection.
(2026-08-14)

Direction (Vijay): stop projecting material as "budget − committed" and instead cost the RELEASED
BOM at historical prices → a bottom-up estimate-to-complete. Proposed:
    Material EAC = committed + (released-but-not-yet-ordered, priced at historical cost)
                             + allowance for the not-yet-released remainder
with release % as the confidence dial. Before building, this probe measures whether the data
supports it, for one sample project:

  A. RELEASE MODEL  — how ETO marks a BOM line/assembly "released" (columns + any release table).
  B. BOM SIZE + RELEASE COVERAGE — lines / distinct items / value, released vs not.
  C. PURCHASED vs FABRICATED — the ItemFabrication split (we only price purchased leaves; summing
     everything double-counts assemblies).
  D. HISTORICAL PRICE COVERAGE — of released PURCHASED items, how many we can price from real PO
     history vs item-master fallback vs nothing; a rough should-cost.
  E. RELEASED vs ORDERED — released purchased items already on a PO (committed) vs still-to-buy.
  F. COMPARISON — released-BOM should-cost vs material budget vs committed.

READ-ONLY.  Run:  python console_diag_bom_costing.py [projectID]   (default 240040) → paste output.
Run it for 2–3 projects at different maturity (early / mid / near-done) so we see the range.
"""
import sys

BOM = "vwEngBOM"        # per the inventory probe this carries ItemFabrication, ItemLastCost, release id
REL_HINTS = ("release", "revis", "hold", "approved", "status", "effectiv")


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
        # ── A. RELEASE MODEL ─────────────────────────────────────────────────────
        rule("A. RELEASE MODEL — BOM columns hinting at release/revision + any release table")
        cols = columns_of(cur, BOM)
        rel_cols = [n for n, _ in cols if any(h in n.lower() for h in REL_HINTS)]
        print(f"  {BOM} release/revision-ish columns: " + (", ".join(rel_cols) or "(none)"))
        cur.execute("SELECT TABLE_NAME FROM INFORMATION_SCHEMA.TABLES "
                    "WHERE TABLE_NAME LIKE '%Release%' OR TABLE_NAME LIKE '%AssemblyRel%' "
                    "ORDER BY TABLE_NAME")
        rel_tables = [r[0] for r in cur.fetchall()]
        print("  release tables: " + (", ".join(rel_tables) or "(none)"))
        for t in rel_tables[:4]:
            tc = columns_of(cur, t)
            print(f"    ── {t}: " + ", ".join(n for n, _ in tc))
        run(cur, "A1. distinct BOMAssemblyReleaseID on this project (0/NULL = un-released?)",
            f"SELECT TOP 20 BOMAssemblyReleaseID, COUNT(*) AS lines "
            f"FROM dbo.{BOM} WHERE ProjectID = {pid} GROUP BY BOMAssemblyReleaseID ORDER BY lines DESC")

        # ── B. BOM SIZE + RELEASE COVERAGE ──────────────────────────────────────
        rule("B. BOM SIZE + RELEASE COVERAGE (released = BOMAssemblyReleaseID > 0)")
        run(cur, "B1. lines / items / released split",
            f"SELECT COUNT(*) AS lines, COUNT(DISTINCT ItemID) AS items, "
            f"  SUM(CASE WHEN ISNULL(BOMAssemblyReleaseID,0) > 0 THEN 1 ELSE 0 END) AS released_lines, "
            f"  SUM(CASE WHEN ISNULL(BOMAssemblyReleaseID,0) = 0 THEN 1 ELSE 0 END) AS unreleased_lines "
            f"FROM dbo.{BOM} WHERE ProjectID = {pid}")

        # ── C. PURCHASED vs FABRICATED ──────────────────────────────────────────
        rule("C. PURCHASED vs FABRICATED (we price purchased leaves; assemblies would double-count)")
        run(cur, "C1. line + rough-value split by ItemFabrication",
            f"SELECT ItemFabrication, COUNT(*) AS lines, COUNT(DISTINCT ItemID) AS items, "
            f"  CAST(SUM(CAST(ItemQty AS float) * CAST(ISNULL(ItemLastCost,0) AS float)) AS decimal(18,2)) AS qty_x_lastcost "
            f"FROM dbo.{BOM} WHERE ProjectID = {pid} GROUP BY ItemFabrication")

        # ── D. HISTORICAL PRICE COVERAGE (released purchased items) ──────────────
        rule("D. HISTORICAL PRICE COVERAGE — released, purchased BOM items priced from PO history")
        # per-item historical unit price from PO lines (avg of ExtendedPrice/qty), any project
        hist = ("(SELECT pod.ItemID, "
                "        AVG(CASE WHEN pod.PurchaseQty > 0 THEN pod.ExtendedPrice / pod.PurchaseQty END) AS hist_unit, "
                "        COUNT(*) AS po_lines "
                " FROM dbo.vwPurchaseOrderDetails pod WHERE pod.ItemID IS NOT NULL GROUP BY pod.ItemID)")
        run(cur, "D1. of released+purchased items: priced from PO history vs item-master vs nothing",
            f"WITH bom AS ("
            f"  SELECT DISTINCT b.ItemID, b.ItemLastCost, b.ItemListCost "
            f"  FROM dbo.{BOM} b WHERE b.ProjectID = {pid} "
            f"    AND ISNULL(b.ItemFabrication,0) = 0 AND ISNULL(b.BOMAssemblyReleaseID,0) > 0) "
            f"SELECT COUNT(*) AS released_purchased_items, "
            f"  SUM(CASE WHEN h.hist_unit IS NOT NULL THEN 1 ELSE 0 END) AS priced_from_PO_history, "
            f"  SUM(CASE WHEN h.hist_unit IS NULL AND ISNULL(b.ItemLastCost,0) > 0 THEN 1 ELSE 0 END) AS fallback_lastcost, "
            f"  SUM(CASE WHEN h.hist_unit IS NULL AND ISNULL(b.ItemLastCost,0) = 0 "
            f"           AND ISNULL(b.ItemListCost,0) > 0 THEN 1 ELSE 0 END) AS fallback_listcost, "
            f"  SUM(CASE WHEN h.hist_unit IS NULL AND ISNULL(b.ItemLastCost,0) = 0 "
            f"           AND ISNULL(b.ItemListCost,0) = 0 THEN 1 ELSE 0 END) AS no_price "
            f"FROM bom b LEFT JOIN {hist} h ON h.ItemID = b.ItemID")

        # ── E. RELEASED vs ORDERED ──────────────────────────────────────────────
        rule("E. RELEASED PURCHASED items — already on a PO (committed) vs still-to-buy")
        run(cur, "E1. released purchased items split by whether a PO exists for them on this project",
            f"WITH bom AS ("
            f"  SELECT DISTINCT b.ItemID FROM dbo.{BOM} b WHERE b.ProjectID = {pid} "
            f"    AND ISNULL(b.ItemFabrication,0) = 0 AND ISNULL(b.BOMAssemblyReleaseID,0) > 0), "
            f"ordered AS (SELECT DISTINCT ItemID FROM dbo.vwPurchaseOrderDetails WHERE ProjectID = {pid}) "
            f"SELECT COUNT(*) AS released_purchased_items, "
            f"  SUM(CASE WHEN o.ItemID IS NOT NULL THEN 1 ELSE 0 END) AS already_ordered, "
            f"  SUM(CASE WHEN o.ItemID IS NULL THEN 1 ELSE 0 END) AS still_to_buy "
            f"FROM bom b LEFT JOIN ordered o ON o.ItemID = b.ItemID")

        # ── F. COMPARISON — rough should-cost vs budget vs committed ─────────────
        rule("F. ROUGH should-cost of the released BOM  vs  material budget  vs  committed")
        run(cur, "F1. released-BOM should-cost (qty × best available unit: PO-hist → lastcost → listcost)",
            f"WITH bom AS ("
            f"  SELECT b.ItemID, SUM(CAST(b.ItemQty AS float)) AS qty, "
            f"         MAX(CAST(b.ItemLastCost AS float)) AS lastc, MAX(CAST(b.ItemListCost AS float)) AS listc "
            f"  FROM dbo.{BOM} b WHERE b.ProjectID = {pid} "
            f"    AND ISNULL(b.ItemFabrication,0) = 0 AND ISNULL(b.BOMAssemblyReleaseID,0) > 0 "
            f"  GROUP BY b.ItemID) "
            f"SELECT CAST(SUM(bom.qty * COALESCE(h.hist_unit, NULLIF(bom.lastc,0), NULLIF(bom.listc,0), 0)) "
            f"            AS decimal(18,2)) AS released_bom_should_cost, "
            f"       COUNT(*) AS items "
            f"FROM bom LEFT JOIN {hist} h ON h.ItemID = bom.ItemID")
        run(cur, "F2. material budget + committed context (from the costing rollup, if present)",
            f"SELECT TOP 5 * FROM dbo.vwCostingSummed_ByProjectID WHERE ProjectID = {pid}")
    finally:
        conn.close()
    print("\nDone. Paste the whole output. How to read it:\n"
          "  • A = confirms what 'released' means (release id / table) so the filter is right.\n"
          "  • B = how much of THIS project's BOM is released → the confidence dial in practice.\n"
          "  • C = purchased vs fabricated; we cost only purchased leaves (fabricated = raw material).\n"
          "  • D = the make-or-break: what share of released-purchased items we can price from real\n"
          "    PO history vs fallback vs nothing. High PO-history coverage = trustworthy.\n"
          "  • E = of the released items, which are already committed vs still-to-buy (what we'd add).\n"
          "  • F = does the released-BOM should-cost land sensibly next to budget & committed?\n"
          "  Run it for an early, a mid, and a near-done job so we see how the numbers firm up.")


if __name__ == "__main__":
    main()
