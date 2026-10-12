"""
console_diag_eto_grids3b.py — re-run of K4/K5 from console_diag_eto_grids3.py (SQL Server refused EXISTS inside
SUM / GROUP BY; rewritten with joins).  READ-ONLY.  (2026-10-12)

  K4  Non-BOM PO lines from the last 2 years (part on no BOM, never released): how many have a matching
      vwPurchasingNonBOM request on the same project + part, and on any project. Same for all active PO lines.
  K5  vwPurchasingDemand rows for 250005 split by source: Non-BOM request / release log / neither.
  K6  The 13 rows of Peter's 8 Oct export that are gone with no new PO: what the release log and Non-BOM
      requests show for them since 8 Oct.

Run:  python console_diag_eto_grids3b.py   → paste the whole output.
"""
import time

GONE = [(220154, 10.0, '8005M0.0.0.0-01'), (240088, 180.0, 'E07448'), (240088, 300.0, 'E08328'),
        (240088, 305.0, 'E07448'), (240088, 330.0, 'E07448'), (240088, 345.0, 'E07448'),
        (240148, 10.0, '240148-10H3.0.0.0-00'), (240148, 10.0, '240148-10H3.1.0.0-00'),
        (240148, 10.0, '240148-10H4.0.0.0-00'), (240148, 10.0, '240148-10H7.0.0.0-00')]


def show(cur, label, sql, n=40):
    try:
        cur.execute(sql)
        cols = [d[0] for d in cur.description]
        rows = cur.fetchall()
        print(f"\n   {label}  ({len(rows)} row(s))")
        print("     " + " | ".join(cols))
        for r in rows[:n]:
            print("     " + " | ".join("" if v is None else str(v) for v in r))
    except Exception as e:
        print(f"   !! {label}: {type(e).__name__}: {e}")


def main():
    from console.infra.connections import eto_connection
    eto = eto_connection(); cur = eto.cursor()
    try:
        eto.timeout = 300
    except Exception:
        pass
    print(f"console_diag_eto_grids3b — {time.strftime('%Y-%m-%d %H:%M')}  (read-only)")
    print("\n== K4. PO lines (last 2 years) with a Non-BOM request")
    show(cur, "non-BOM PO lines (part on no BOM, never released)", """
        WITH nb AS (
            SELECT pod.PurchaseDetailID, pod.ProjectID, pod.ItemID
            FROM dbo.vwPurchaseOrderHeader poh JOIN dbo.vwPurchaseOrderDetails pod ON pod.PurchaseOrderID = poh.PurchaseOrderID
            WHERE poh.PurchaseActive = 1 AND poh.PurchaseDate >= DATEADD(year, -2, GETDATE()) AND pod.ItemID IS NOT NULL
              AND NOT EXISTS (SELECT 1 FROM dbo.vwEngBOM b WHERE b.ItemID = pod.ItemID)
              AND NOT EXISTS (SELECT 1 FROM dbo.tblBOMReleaseHistory h WHERE h.ItemID = pod.ItemID)),
        rp AS (SELECT DISTINCT ProjectID, ItemID FROM dbo.vwPurchasingNonBOM),
        ri AS (SELECT DISTINCT ItemID FROM dbo.vwPurchasingNonBOM)
        SELECT COUNT(*) AS NonBOMLines,
               SUM(CASE WHEN rp.ItemID IS NOT NULL THEN 1 ELSE 0 END) AS WithRequestSameProject,
               SUM(CASE WHEN ri.ItemID IS NOT NULL THEN 1 ELSE 0 END) AS WithRequestAnyProject
        FROM nb LEFT JOIN rp ON rp.ProjectID = nb.ProjectID AND rp.ItemID = nb.ItemID
                LEFT JOIN ri ON ri.ItemID = nb.ItemID""")
    show(cur, "all active PO lines (last 2 years)", """
        WITH rp AS (SELECT DISTINCT ProjectID, ItemID FROM dbo.vwPurchasingNonBOM),
        rl AS (SELECT DISTINCT ProjectID, ItemID FROM dbo.tblBOMReleaseHistory)
        SELECT COUNT(*) AS Lines,
               SUM(CASE WHEN rp.ItemID IS NOT NULL THEN 1 ELSE 0 END) AS WithNonBOMRequest,
               SUM(CASE WHEN rl.ItemID IS NOT NULL THEN 1 ELSE 0 END) AS WithRelease,
               SUM(CASE WHEN rp.ItemID IS NULL AND rl.ItemID IS NULL THEN 1 ELSE 0 END) AS WithNeither
        FROM dbo.vwPurchaseOrderHeader poh JOIN dbo.vwPurchaseOrderDetails pod ON pod.PurchaseOrderID = poh.PurchaseOrderID
        LEFT JOIN rp ON rp.ProjectID = pod.ProjectID AND rp.ItemID = pod.ItemID
        LEFT JOIN rl ON rl.ProjectID = pod.ProjectID AND rl.ItemID = pod.ItemID
        WHERE poh.PurchaseActive = 1 AND poh.PurchaseDate >= DATEADD(year, -2, GETDATE())""")
    show(cur, "same, by year", """
        WITH rp AS (SELECT DISTINCT ProjectID, ItemID FROM dbo.vwPurchasingNonBOM),
        rl AS (SELECT DISTINCT ProjectID, ItemID FROM dbo.tblBOMReleaseHistory)
        SELECT YEAR(poh.PurchaseDate) AS Yr, COUNT(*) AS Lines,
               SUM(CASE WHEN rl.ItemID IS NOT NULL THEN 1 ELSE 0 END) AS WithRelease,
               SUM(CASE WHEN rl.ItemID IS NULL AND rp.ItemID IS NOT NULL THEN 1 ELSE 0 END) AS NonBOMRequestOnly,
               SUM(CASE WHEN rp.ItemID IS NULL AND rl.ItemID IS NULL THEN 1 ELSE 0 END) AS WithNeither
        FROM dbo.vwPurchaseOrderHeader poh JOIN dbo.vwPurchaseOrderDetails pod ON pod.PurchaseOrderID = poh.PurchaseOrderID
        LEFT JOIN rp ON rp.ProjectID = pod.ProjectID AND rp.ItemID = pod.ItemID
        LEFT JOIN rl ON rl.ProjectID = pod.ProjectID AND rl.ItemID = pod.ItemID
        WHERE poh.PurchaseActive = 1 GROUP BY YEAR(poh.PurchaseDate) ORDER BY 1""")

    print("\n== K5. vwPurchasingDemand for 250005 by source")
    show(cur, "demand rows", """
        WITH nbr AS (SELECT DISTINCT ProjectID, CAST(SpecID AS float) AS SpecID, ChildID FROM dbo.vwPurchasingNonBOM WHERE ProjectID = 250005),
        rel AS (SELECT DISTINCT ProjectID, CAST(SpecID AS float) AS SpecID, ItemID FROM dbo.tblBOMReleaseHistory WHERE ProjectID = 250005),
        d AS (SELECT dd.*, CASE WHEN rel.ItemID IS NOT NULL THEN 'Release log'
                                WHEN nbr.ChildID IS NOT NULL THEN 'Non-BOM request only' ELSE 'neither' END AS Source
              FROM dbo.vwPurchasingDemand dd
              LEFT JOIN rel ON rel.ProjectID = dd.ProjectID AND rel.SpecID = CAST(dd.SpecID AS float) AND rel.ItemID = dd.ChildID
              LEFT JOIN nbr ON nbr.ProjectID = dd.ProjectID AND nbr.SpecID = CAST(dd.SpecID AS float) AND nbr.ChildID = dd.ChildID
              WHERE dd.ProjectID = 250005)
        SELECT Source, COUNT(*) AS Rows, SUM(CAST(PurchaseQty AS float)) AS Qty FROM d GROUP BY Source ORDER BY 2 DESC""")

    print("\n== K6. Peter's rows now gone with no new PO (first 10 of 13)")
    for p, m, part in GONE:
        show(cur, f"{p} m{m:g} {part}", f"""
            SELECT 'release log' AS Src, h.[Type] AS Kind, CAST(h.QuantityChange AS float) AS Qty, h.ReleasedDateTime AS Dt, CAST(h.ReleaseNote AS nvarchar(120)) AS Note
            FROM dbo.tblBOMReleaseHistory h JOIN dbo.tblEngItemMaster e ON e.ItemID = h.ItemID
            WHERE h.ProjectID = {p} AND CAST(h.SpecID AS float) = {m} AND e.ItemCompanyID = '{part}' AND h.ReleasedDateTime >= '20261001'
            UNION ALL
            SELECT 'non-BOM request', 'request', CAST(n.PurchaseQty AS float), n.DateCreated, LEFT(n.AddReason, 120)
            FROM dbo.vwPurchasingNonBOM n
            WHERE n.ProjectID = {p} AND CAST(n.SpecID AS float) = {m} AND n.ItemCompanyID = '{part}' AND n.DateCreated >= '20261001'
            ORDER BY 4""", 10)
    print("\nDONE — paste everything above.")


if __name__ == "__main__":
    main()
