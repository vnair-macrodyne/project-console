"""
console_diag_feedback_250005.py — checks behind the purchasing-report feedback.  READ-ONLY.  (2026-10-12)

Feedback: "Jamal noted the number of items for 250005 looked like it was missing many items. It is
supposed to be all items ever ordered for the project." Plus: Planned Ship Date to verify, and
"Days to Assembly" to become a Manufacture Begin date.

  F1  Every PO line on the project, counted the ways the reports filter it: all lines in the PO
      table; on cancelled POs (PurchaseActive = 0); freight/courier/cartage/brokerage lines (reports
      hide them); archived lines; what is left = All Purchase Orders.
  F2  What each live report actually returns for the project (All Purchase Orders, PO Exceptions,
      Purchase Requisitions, Lines to Order).
  F3  The project's BOM parts: how many have a PO on this project, how many were bought only on
      ANOTHER project (e.g. 9000), how many have no PO anywhere.
  F4  Date fields that could feed Planned Ship / Manufacture Begin — ETO per-machine dates on the
      project, their fill rate across active projects, and the Console's own Plan-page Planned Ship.

Run:  python console_diag_feedback_250005.py            # project 250005
      python console_diag_feedback_250005.py 220154     # another project
Paste the whole output back.
"""
import sys, time

PID = next((int(a) for a in sys.argv[1:] if a.isdigit()), 250005)
FREIGHT = ("(LOWER(ISNULL(pod.ItemDescription,'')) LIKE '%freight%' OR LOWER(ISNULL(pod.ItemDescription,'')) LIKE '%courier%' "
           "OR LOWER(ISNULL(pod.ItemDescription,'')) LIKE '%cartage%' OR LOWER(ISNULL(pod.ItemDescription,'')) LIKE '%brokerage%' "
           "OR LOWER(ISNULL(pdd.ItemMasterCategoryDescription,'')) LIKE '%freight%' "
           "OR LOWER(ISNULL(pdd.ItemMasterCategoryDescription,'')) LIKE '%courier%')")


def q(cur, sql):
    cur.execute(sql)
    cols = [d[0] for d in cur.description]
    return cols, [tuple(r) for r in cur.fetchall()]


def show(cur, label, sql):
    try:
        cols, rows = q(cur, sql)
        print(f"   {label}")
        print("     " + " | ".join(cols))
        for r in rows[:40]:
            print("     " + " | ".join("" if v is None else str(v) for v in r))
    except Exception as e:
        print(f"   !! {label}: {type(e).__name__}: {e}")


def main():
    from console.infra.connections import eto_connection, console_connection
    eto = eto_connection(); cur = eto.cursor()
    print(f"console_diag_feedback_250005 — {time.strftime('%Y-%m-%d %H:%M')}  project {PID}  (read-only)")

    print("\n== F1. PO lines on the project, by the filters the reports apply")
    show(cur, "base table vs view", f"""
        SELECT (SELECT COUNT(*) FROM dbo.tblPurchaseOrderDetails WHERE ProjectID = {PID}) AS TableLines,
               (SELECT COUNT(*) FROM dbo.vwPurchaseOrderDetails WHERE ProjectID = {PID}) AS ViewLines,
               (SELECT COUNT(DISTINCT PurchaseOrderID) FROM dbo.tblPurchaseOrderDetails WHERE ProjectID = {PID}) AS POs""")
    show(cur, "by PO active flag / freight / archived (view)", f"""
        SELECT poh.PurchaseActive AS Active,
               CASE WHEN {FREIGHT} THEN 1 ELSE 0 END AS FreightLike,
               ISNULL(pod.Archived, 0) AS Archived,
               COUNT(*) AS Lines, COUNT(DISTINCT pod.PurchaseOrderID) AS POs, COUNT(DISTINCT pod.ItemID) AS Parts
        FROM dbo.vwPurchaseOrderHeader poh
        JOIN dbo.vwPurchaseOrderDetails pod ON pod.PurchaseOrderID = poh.PurchaseOrderID
        LEFT JOIN dbo.vwPurchaseOrderDetailsDetailed pdd ON pdd.PurchaseDetailID = pod.PurchaseDetailID
        WHERE pod.ProjectID = {PID}
        GROUP BY poh.PurchaseActive, CASE WHEN {FREIGHT} THEN 1 ELSE 0 END, ISNULL(pod.Archived, 0)
        ORDER BY 1 DESC, 2, 3""")
    show(cur, "lines whose detail joins NO header row in the view (would be dropped by every report)", f"""
        SELECT COUNT(*) AS Orphans FROM dbo.vwPurchaseOrderDetails pod
        WHERE pod.ProjectID = {PID} AND NOT EXISTS
          (SELECT 1 FROM dbo.vwPurchaseOrderHeader poh WHERE poh.PurchaseOrderID = pod.PurchaseOrderID)""")
    show(cur, "PO lines by year entered", f"""
        SELECT YEAR(poh.PurchaseDate) AS Yr, poh.PurchaseActive AS Active, COUNT(*) AS Lines
        FROM dbo.vwPurchaseOrderHeader poh JOIN dbo.vwPurchaseOrderDetails pod ON pod.PurchaseOrderID = poh.PurchaseOrderID
        WHERE pod.ProjectID = {PID} GROUP BY YEAR(poh.PurchaseDate), poh.PurchaseActive ORDER BY 1, 2""")

    print("\n== F2. What the live reports return for the project")
    try:
        from console_web.queries import LiveQueryService
        for qid in ("po_listing", "po_exceptions", "po_to_order", "released_toorder"):
            s = LiveQueryService(); t0 = time.perf_counter()
            r = s.run(qid, [PID])
            det = [x for x in r.rows if x.get("_kind") == "detail"]
            print(f"   {r.title:44} {len(det):>6,} rows  ({time.perf_counter() - t0:.1f}s)  "
                  + " · ".join(f"{c.label} {c.value}" for c in r.cards))
    except Exception as e:
        print(f"   !! live reports: {type(e).__name__}: {e}")

    print("\n== F3. The project's BOM parts vs where they were bought")
    show(cur, "BOM parts by purchase status", f"""
        WITH bom AS (SELECT DISTINCT ItemID FROM dbo.vwEngBOM WHERE ProjectID = {PID}),
        here AS (SELECT DISTINCT pod.ItemID FROM dbo.vwPurchaseOrderDetails pod JOIN dbo.vwPurchaseOrderHeader poh
                 ON poh.PurchaseOrderID = pod.PurchaseOrderID WHERE poh.PurchaseActive = 1 AND pod.ProjectID = {PID}),
        other AS (SELECT DISTINCT pod.ItemID FROM dbo.vwPurchaseOrderDetails pod JOIN dbo.vwPurchaseOrderHeader poh
                 ON poh.PurchaseOrderID = pod.PurchaseOrderID WHERE poh.PurchaseActive = 1 AND pod.ProjectID <> {PID}
                 AND pod.ItemID IN (SELECT ItemID FROM bom))
        SELECT COUNT(*) AS BOMParts,
               SUM(CASE WHEN h.ItemID IS NOT NULL THEN 1 ELSE 0 END) AS POOnThisProject,
               SUM(CASE WHEN h.ItemID IS NULL AND o.ItemID IS NOT NULL THEN 1 ELSE 0 END) AS POOnlyOnOtherProjects,
               SUM(CASE WHEN h.ItemID IS NULL AND o.ItemID IS NULL THEN 1 ELSE 0 END) AS NoPOAnywhere
        FROM bom b LEFT JOIN here h ON h.ItemID = b.ItemID LEFT JOIN other o ON o.ItemID = b.ItemID""")
    show(cur, "BOM parts with no PO on this project, by structure category / unit type", f"""
        WITH ps AS (SELECT DISTINCT ChildID AS ItemID, CAST(CatergoryMajor AS nvarchar(50)) AS CatMajor,
                           CAST(UOMType AS nvarchar(20)) AS UOMType
                    FROM dbo.vwEngProductStructure WHERE ProjectID = {PID}),
        here AS (SELECT DISTINCT pod.ItemID FROM dbo.vwPurchaseOrderDetails pod JOIN dbo.vwPurchaseOrderHeader poh
                 ON poh.PurchaseOrderID = pod.PurchaseOrderID WHERE poh.PurchaseActive = 1 AND pod.ProjectID = {PID})
        SELECT ps.CatMajor, ps.UOMType, COUNT(*) AS PartsNoPOHere
        FROM ps LEFT JOIN here h ON h.ItemID = ps.ItemID WHERE h.ItemID IS NULL
        GROUP BY ps.CatMajor, ps.UOMType ORDER BY 3 DESC""")
    show(cur, "top other projects the project's BOM parts were bought on (no PO on this project)", f"""
        WITH bom AS (SELECT DISTINCT ItemID FROM dbo.vwEngBOM WHERE ProjectID = {PID}),
        here AS (SELECT DISTINCT pod.ItemID FROM dbo.vwPurchaseOrderDetails pod JOIN dbo.vwPurchaseOrderHeader poh
                 ON poh.PurchaseOrderID = pod.PurchaseOrderID WHERE poh.PurchaseActive = 1 AND pod.ProjectID = {PID})
        SELECT TOP 10 pod.ProjectID, COUNT(DISTINCT pod.ItemID) AS Parts, MAX(poh.PurchaseDate) AS LatestPO
        FROM dbo.vwPurchaseOrderDetails pod JOIN dbo.vwPurchaseOrderHeader poh ON poh.PurchaseOrderID = pod.PurchaseOrderID
        WHERE poh.PurchaseActive = 1 AND pod.ProjectID <> {PID}
          AND pod.ItemID IN (SELECT ItemID FROM bom) AND pod.ItemID NOT IN (SELECT ItemID FROM here)
        GROUP BY pod.ProjectID ORDER BY 2 DESC""")

    print("\n== F4. Dates for Planned Ship / Manufacture Begin")
    show(cur, f"tblSpec dates on project {PID} (per machine)", f"""
        SELECT SpecID, SDescription, BudgetShipRelease, BudgetMfgRelease, BudgetEngRelease, MfgBegin
        FROM dbo.tblSpec WHERE ProjectID = {PID} ORDER BY SpecID""")
    show(cur, "fill rate on machines of projects active in the last 12 months", """
        SELECT COUNT(*) AS Machines,
               SUM(CASE WHEN BudgetShipRelease IS NOT NULL THEN 1 ELSE 0 END) AS ShipRelease,
               SUM(CASE WHEN BudgetMfgRelease IS NOT NULL THEN 1 ELSE 0 END) AS MfgRelease,
               SUM(CASE WHEN MfgBegin IS NOT NULL THEN 1 ELSE 0 END) AS MfgBegin
        FROM dbo.tblSpec WHERE ProjectID IN
          (SELECT ProjectID FROM dbo.tblProjects WHERE PLast >= DATEADD(month, -12, GETDATE()))""")
    show(cur, "BOM line RequiredDate on the project (vwEngBOM)", f"""
        SELECT COUNT(*) AS BOMLines, SUM(CASE WHEN RequiredDate IS NOT NULL THEN 1 ELSE 0 END) AS WithRequiredDate,
               MIN(RequiredDate) AS Earliest, MAX(RequiredDate) AS Latest
        FROM dbo.vwEngBOM WHERE ProjectID = {PID}""")
    show(cur, "process schedules on the project", f"""
        SELECT COUNT(*) AS Schedules, MIN(StartDate) AS EarliestStart, MAX(FinalRequiredDate) AS LatestFinalReq
        FROM dbo.tblProcessScheduleHeader WHERE ProjectID = {PID}""")
    try:
        cc = console_connection(); c2 = cc.cursor()
        show(c2, "Console Plan page — latest Planned Ship entered by the PM", f"""
            SELECT TOP 1 PlannedShipDate, YearWeekKey FROM Reporting.tblProjectPMEntry
            WHERE ProjectID = {PID} ORDER BY YearWeekKey DESC""")
        show(c2, "Console overlay ship dates", f"""
            SELECT TOP 1 CustAgreedShipDate, POShipDate FROM Reporting.vw_Console_ManualOverlay WHERE ProjectID = {PID}""")
    except Exception as e:
        print(f"   !! console connection: {type(e).__name__}: {e}")
    print("\nDONE — paste everything above.")


if __name__ == "__main__":
    main()
