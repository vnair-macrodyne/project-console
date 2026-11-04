"""
console_diag_over_order_cases.py — READ-ONLY. Why are three parts flagged as potential over orders when
the project's positive releases exceed what was ordered? (2026-11-04)
For each: every release-log entry (with negatives / Unrelease), every Non-BOM request, every active PO line,
by machine, and the NET released per machine.

Run:  py console_diag_over_order_cases.py   → paste the whole output.
"""
CASES = [(240148, "E03898"), (230127, "7011H0.0.0.0-07"), (220154, "8027M0.0.0.0-01")]


def show(cur, label, sql, n=60):
    try:
        cur.execute(sql)
    except Exception as e:
        print(f"\n   !! {label}: {type(e).__name__}: {str(e)[:200]}"); return
    cols = [d[0] for d in cur.description]; rows = cur.fetchall()
    print(f"\n   {label}  ({len(rows)} row(s))")
    print("     " + " | ".join(cols))
    for r in rows[:n]:
        print("     " + " | ".join("" if v is None else str(v) for v in r))


def main():
    from console.infra.connections import eto_connection
    cur = eto_connection().cursor()
    for pid, part in CASES:
        print(f"\n== {pid} / {part}")
        it = f"(SELECT ItemID FROM dbo.tblEngItemMaster WHERE ItemCompanyID = '{part}')"
        show(cur, "release log", f"""
            SELECT CAST(SpecID AS float) AS Machine, [Type], CAST(QuantityChange AS float) AS Qty, ReleasedDateTime
            FROM dbo.tblBOMReleaseHistory WHERE ProjectID = {pid} AND ItemID IN {it} ORDER BY ReleasedDateTime""")
        show(cur, "net released by machine", f"""
            SELECT CAST(SpecID AS float) AS Machine, [Type], COUNT(*) AS Entries, SUM(CAST(QuantityChange AS float)) AS NetQty
            FROM dbo.tblBOMReleaseHistory WHERE ProjectID = {pid} AND ItemID IN {it}
            GROUP BY CAST(SpecID AS float), [Type] ORDER BY 1, 2""")
        show(cur, "Non-BOM requests", f"""
            SELECT CAST(SpecID AS float) AS Machine, CAST(PurchaseQty AS float) AS Qty, DateCreated, AddReason
            FROM dbo.vwPurchasingNonBOM WHERE ProjectID = {pid} AND ItemID IN {it} ORDER BY DateCreated""")
        show(cur, "active PO lines", f"""
            SELECT CAST(pod.SpecID AS float) AS Machine, poh.PurchaseOrderID, CAST(poh.PurchaseDate AS date) AS PODate,
                   CAST(pod.PurchaseQty AS float) AS Qty, CAST(pod.Received AS float) AS Received
            FROM dbo.vwPurchaseOrderDetails pod JOIN dbo.vwPurchaseOrderHeader poh ON poh.PurchaseOrderID = pod.PurchaseOrderID
            WHERE poh.PurchaseActive = 1 AND pod.ProjectID = {pid} AND pod.ItemID IN {it} ORDER BY poh.PurchaseDate""")
        show(cur, "BOM quantity by machine", f"""
            SELECT CAST(SpecID AS float) AS Machine, SUM(CAST(TotalQuantity AS float)) AS BOMQty
            FROM dbo.vwEngBOM WHERE ProjectID = {pid} AND ItemID IN {it} GROUP BY CAST(SpecID AS float)""")
    print("\nDONE — paste everything above.")


if __name__ == "__main__":
    main()
