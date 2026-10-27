"""console_diag_project_flow.py - READ-ONLY probe for the per-project FLOW timeline.

No guesses: before we build a milestone timeline, confirm which milestone dates ETO
actually maintains and collect the flow spine per active project.

  A. Is there a usable "manufacturing / build start" date?
     - tblProcessScheduleHeader (StartDate) column list + population on active projects
     - tblSpec date/schedule columns (MfgBegin / *Release* / *Ship* / *Begin*) + population
       (prior finding: these are ~empty; this re-confirms on the active set)
  B. The flow spine per active project:
     - design released  : first/last tblBOMReleaseHistory.ReleasedDateTime, # released items
     - RFQ              : first tblRFQHeader.RFQDate (via tblRFQDetails.ProjectID)
     - PO raised        : first vwPurchaseOrderHeader.PurchaseDate (all, and first ISSUED)
     - received         : first/last vwPurchaseOrderDetailsDetailed.LastReceivedDate
     - build start      : first tblProcessScheduleHeader.StartDate (if maintained)
  C. Day-gaps between stages (release -> first PO, release -> first RFQ, PO -> first receipt).

No writes. Run from the repo root with the same Python as the other console_diag_* scripts:
    python console_diag_project_flow.py
"""
import console_config                      # loads .env / TENANT
from console_store import eto_connection, console_connection


def run(cur, sql, params=None):
    cur.execute(sql, params or [])
    cols = [d[0] for d in cur.description]
    return cols, cur.fetchall()


def d(v):
    """date-only string, '' if None."""
    if v is None:
        return ""
    try:
        return v.date().isoformat()
    except Exception:
        return str(v)[:10]


def days(a, b):
    """whole days a->b, '' if either missing."""
    if a is None or b is None:
        return ""
    try:
        return (b - a).days
    except Exception:
        return ""


def main():
    # ---- active projects (the open-projects list) --------------------------------
    active = []
    try:
        ccur = console_connection().cursor()
        ccur.execute("SELECT ProjectID FROM Reporting.tblActiveProject ORDER BY ProjectID")
        active = [int(r[0]) for r in ccur.fetchall()]
    except Exception as e:
        print("(could not read Reporting.tblActiveProject:", e, ")")
    print("active projects:", len(active), active)
    ids = ",".join(str(p) for p in active)
    scope = f" WHERE ProjectID IN ({ids})" if active else ""
    pscope = f" WHERE pod.ProjectID IN ({ids})" if active else ""

    conn = eto_connection()
    cur = conn.cursor()

    print("\n" + "=" * 80)
    print("A1. tblProcessScheduleHeader - columns + population on active projects")
    print("=" * 80)
    try:
        _, cols = run(cur, """SELECT COLUMN_NAME, DATA_TYPE FROM INFORMATION_SCHEMA.COLUMNS
                              WHERE TABLE_NAME='tblProcessScheduleHeader' ORDER BY ORDINAL_POSITION""")
        for c in cols:
            print("   ", c[0], "|", c[1])
        _, r = run(cur, f"""SELECT COUNT(*) AS rows_, COUNT(DISTINCT ProjectID) AS projs,
                                   COUNT(StartDate) AS startdate_pop,
                                   CAST(MIN(StartDate) AS date) AS min_start,
                                   CAST(MAX(StartDate) AS date) AS max_start
                            FROM tblProcessScheduleHeader{scope}""")
        print("   population (active):", dict(zip([x for x in ['rows_','projs','startdate_pop','min_start','max_start']], r[0])))
    except Exception as e:
        print("   !! tblProcessScheduleHeader probe failed:", e)

    print("\n" + "=" * 80)
    print("A2. tblSpec date / schedule columns - population on active projects")
    print("=" * 80)
    try:
        _, scols = run(cur, """SELECT COLUMN_NAME, DATA_TYPE FROM INFORMATION_SCHEMA.COLUMNS
                               WHERE TABLE_NAME='tblSpec'
                                 AND (DATA_TYPE LIKE '%date%' OR COLUMN_NAME LIKE '%Release%'
                                      OR COLUMN_NAME LIKE '%Mfg%' OR COLUMN_NAME LIKE '%Begin%'
                                      OR COLUMN_NAME LIKE '%Ship%' OR COLUMN_NAME LIKE '%Date%')
                               ORDER BY COLUMN_NAME""")
        cand = [c[0] for c in scols]
        print("   candidate columns:", cand)
        _, tot = run(cur, f"SELECT COUNT(*) FROM tblSpec{scope}")
        nspec = tot[0][0]
        print(f"   specs on active projects: {nspec}")
        for c in cand:
            try:
                _, r = run(cur, f"SELECT COUNT([{c}]) AS pop, CAST(MIN([{c}]) AS date), CAST(MAX([{c}]) AS date) FROM tblSpec{scope}")
                pop, mn, mx = r[0]
                pct = (100.0 * pop / nspec) if nspec else 0
                print(f"     {c:28} pop {pop:>5} / {nspec} ({pct:4.1f}%)  range {d(mn)} .. {d(mx)}")
            except Exception as e:
                print(f"     {c:28} (count failed: {e})")
    except Exception as e:
        print("   !! tblSpec probe failed:", e)

    print("\n" + "=" * 80)
    print("B. Per-project flow spine (active projects)")
    print("=" * 80)
    rel, rfq, po, recv, sched = {}, {}, {}, {}, {}
    try:
        _, rows = run(cur, f"""SELECT ProjectID, MIN(ReleasedDateTime), MAX(ReleasedDateTime),
                                      COUNT(DISTINCT ItemID)
                               FROM tblBOMReleaseHistory{scope} GROUP BY ProjectID""")
        rel = {int(r[0]): (r[1], r[2], r[3]) for r in rows}
    except Exception as e:
        print("   release query failed:", e)
    try:
        _, rows = run(cur, f"""SELECT dd.ProjectID, MIN(h.RFQDate)
                               FROM tblRFQDetails dd JOIN tblRFQHeader h ON h.RFQID = dd.RFQID
                               {('WHERE dd.ProjectID IN (' + ids + ')') if active else ''}
                               GROUP BY dd.ProjectID""")
        rfq = {int(r[0]): r[1] for r in rows}
    except Exception as e:
        print("   rfq query failed:", e)
    try:
        _, rows = run(cur, f"""SELECT pod.ProjectID, MIN(poh.PurchaseDate) AS po_first,
                                      MIN(CASE WHEN poh.PurchasePrinted=1 OR poh.PurchaseEmailed=1
                                               THEN poh.PurchaseDate END) AS po_issued,
                                      COUNT(DISTINCT poh.PurchaseOrderID) AS n_pos
                               FROM vwPurchaseOrderHeader poh
                               JOIN vwPurchaseOrderDetails pod ON pod.PurchaseOrderID = poh.PurchaseOrderID
                               WHERE poh.PurchaseActive = 1{(' AND pod.ProjectID IN (' + ids + ')') if active else ''}
                               GROUP BY pod.ProjectID""")
        po = {int(r[0]): (r[1], r[2], r[3]) for r in rows}
    except Exception as e:
        print("   po query failed:", e)
    try:
        _, rows = run(cur, f"""SELECT pod.ProjectID, MIN(pdd.LastReceivedDate), MAX(pdd.LastReceivedDate)
                               FROM vwPurchaseOrderDetails pod
                               JOIN vwPurchaseOrderDetailsDetailed pdd ON pdd.PurchaseDetailID = pod.PurchaseDetailID
                               WHERE pdd.LastReceivedDate IS NOT NULL{(' AND pod.ProjectID IN (' + ids + ')') if active else ''}
                               GROUP BY pod.ProjectID""")
        recv = {int(r[0]): (r[1], r[2]) for r in rows}
    except Exception as e:
        print("   receipt query failed:", e)
    try:
        _, rows = run(cur, f"""SELECT ProjectID, MIN(StartDate) FROM tblProcessScheduleHeader{scope} GROUP BY ProjectID""")
        sched = {int(r[0]): r[1] for r in rows}
    except Exception as e:
        print("   schedule query failed:", e)

    hdr = ("Proj", "#rel", "rel_first", "rel_last", "rfq_first", "po_first", "po_issued",
           "recv_first", "recv_last", "build_start")
    print("   " + " ".join(f"{h:>11}" for h in hdr))
    for p in active:
        rf = rel.get(p, (None, None, 0))
        pr = po.get(p, (None, None, 0))
        rc = recv.get(p, (None, None))
        line = (str(p), str(rf[2]), d(rf[0]), d(rf[1]), d(rfq.get(p)),
                d(pr[0]), d(pr[1]), d(rc[0]), d(rc[1]), d(sched.get(p)))
        print("   " + " ".join(f"{c:>11}" for c in line))

    print("\n" + "=" * 80)
    print("C. Stage gaps (days)  release_first -> first RFQ / first PO ; first PO -> first receipt")
    print("=" * 80)
    print("   " + " ".join(f"{h:>14}" for h in ("Proj", "rel->rfq", "rel->po", "rel->po_iss", "po->recv")))
    for p in active:
        rf0 = rel.get(p, (None,))[0]
        pr = po.get(p, (None, None))
        rc0 = recv.get(p, (None, None))[0]
        line = (str(p), str(days(rf0, rfq.get(p))), str(days(rf0, pr[0])),
                str(days(rf0, pr[1])), str(days(pr[0], rc0)))
        print("   " + " ".join(f"{c:>14}" for c in line))

    print("\nDONE (read-only).")


if __name__ == "__main__":
    main()
