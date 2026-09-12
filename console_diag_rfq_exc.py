"""
console_diag_rfq_exc.py — why is the Exception report's RFQ Date (and maybe Lead/Oversized)
blank?  READ-ONLY.  Nothing is written.  (2026-09-12)

Hypothesis: _q_po_exceptions wraps the ENRICHED query (lead-time + RFQ + oversized + eng-release)
in try/except and, on ANY error, silently falls back to the NON-enriched query that blanks all of
those columns. So a single bad column/view name in the RFQ join makes RFQ Date blank across the
whole report. This probe:

  1. Runs the EXACT enriched query_po_exceptions(True, [project]) and prints the REAL exception if
     it throws (that error is what _q_po_exceptions is swallowing).
  2. If it succeeds, counts how many rows actually got an RFQDate, so we can tell a "query failed"
     problem from a "join matched nothing" problem.
  3. Independently measures the RFQ join COVERAGE for the project's open PO lines at three grains —
     (ProjectID, SpecID, ItemID)  vs  (ProjectID, ItemID)  vs  (ItemID) — and checks LastRFQID /
     tblRFQHeader resolution, so we know whether the 3-key join is too strict.
  4. Confirms vwPurchasingRFQs actually exposes the columns the join assumes.

Run where the other console_diag_*.py scripts run (ETO reachable, repo importable):
    python console_diag_rfq_exc.py [projectID]
Paste the WHOLE output back.
"""
import sys

SAMPLE_PROJECT = int(sys.argv[1]) if len(sys.argv) > 1 else 250250


def eto_connect():
    try:
        from console_store import eto_connection
        return eto_connection()
    except Exception:
        import os, pyodbc
        from console_config import TENANT
        cs = (f"Driver={{ODBC Driver 17 for SQL Server}};Server={TENANT.eto_server};"
              f"Database={TENANT.eto_database};")
        cs += ("Trusted_Connection=yes;" if TENANT.use_windows_auth
               else f"UID={os.environ.get('ETO_USER')};PWD={os.environ.get('ETO_PWD')};")
        return pyodbc.connect(cs)


def rule(t):
    print("\n" + "=" * 88 + f"\n{t}\n" + "=" * 88)


def run(cur, label, sql, cap=25):
    print(f"\n-- {label}")
    try:
        cur.execute(sql)
        if cur.description is None:
            print("   (no result set)"); return [], []
        cols = [d[0] for d in cur.description]
        rows = cur.fetchall()
        print("   " + " | ".join(cols))
        for r in rows[:cap]:
            print("   " + " | ".join("" if v is None else str(v) for v in r))
        print(f"   ({len(rows)} row(s){', showing '+str(cap) if len(rows) > cap else ''})")
        return cols, rows
    except Exception as e:
        print(f"   !! {type(e).__name__}: {e}")
        return [], []


def main():
    eto = eto_connect()
    cur = eto.cursor()

    # ── 1. Run the EXACT enriched query and surface the masked exception ─────────
    rule(f"1. ENRICHED query_po_exceptions(True, [{SAMPLE_PROJECT}]) — the REAL error if it throws")
    try:
        import etospec
        sql = etospec.query_po_exceptions(True, [SAMPLE_PROJECT])
        print("   (built SQL OK; executing…)")
        try:
            cur.execute(sql)
            cols = [d[0] for d in cur.description]
            rows = cur.fetchall()
            ri = cols.index("RFQDate") if "RFQDate" in cols else None
            have = sum(1 for r in rows if ri is not None and r[ri] is not None)
            print(f"   SUCCESS: {len(rows)} rows, RFQDate populated on {have} of them.")
            if ri is not None:
                print("   sample rows (Item | SpecID(Code) | RFQDate | LeadDays):")
                ci = {c: cols.index(c) for c in ("Item", "Code", "RFQDate", "LeadDays") if c in cols}
                for r in rows[:20]:
                    print("     " + " | ".join(str(r[ci[c]]) for c in ci))
            if have == 0:
                print("   >>> query ran but RFQDate matched NOTHING → join-grain/coverage issue (see §3).")
        except Exception as e:
            print(f"   !! ENRICHED QUERY FAILED — this is what _q_po_exceptions silently swallows:")
            print(f"   !! {type(e).__name__}: {e}")
            print("   >>> because it throws, the report falls back to the NON-enriched query that")
            print("   >>> blanks RFQDate / LeadDays / LLT / Oversized / EngRelease together.")
    except Exception as e:
        print(f"   !! could not import/build etospec.query_po_exceptions: {type(e).__name__}: {e}")

    # ── 2. Does vwPurchasingRFQs expose the columns the join assumes? ────────────
    rule("2. vwPurchasingRFQs columns (join assumes ProjectID, SpecID, ItemID, LastRFQID)")
    run(cur, "2. INFORMATION_SCHEMA.COLUMNS for vwPurchasingRFQs",
        "SELECT COLUMN_NAME, DATA_TYPE FROM INFORMATION_SCHEMA.COLUMNS "
        "WHERE TABLE_NAME = 'vwPurchasingRFQs' ORDER BY ORDINAL_POSITION", cap=60)

    # ── 3. RFQ join COVERAGE for this project's OPEN PO lines, at 3 grains ───────
    rule(f"3. RFQ coverage for OPEN PO lines on project {SAMPLE_PROJECT} (is the 3-key join too strict?)")
    base = f"""
        WITH openlines AS (
            SELECT pod.ProjectID, pod.SpecID, pod.ItemID
            FROM dbo.vwPurchaseOrderHeader poh
            JOIN dbo.vwPurchaseOrderDetails pod ON pod.PurchaseOrderID = poh.PurchaseOrderID
            WHERE poh.PurchaseActive = 1 AND pod.ProjectID = {SAMPLE_PROJECT}
              AND (pod.Received IS NULL OR pod.Received < pod.PurchaseQty)
        )
        SELECT
          COUNT(*) AS open_lines,
          SUM(CASE WHEN k3.ItemID IS NOT NULL THEN 1 ELSE 0 END) AS match_proj_spec_item,
          SUM(CASE WHEN k2.ItemID IS NOT NULL THEN 1 ELSE 0 END) AS match_proj_item,
          SUM(CASE WHEN k1.ItemID IS NOT NULL THEN 1 ELSE 0 END) AS match_item_only
        FROM openlines ol
        OUTER APPLY (SELECT TOP 1 ItemID FROM dbo.vwPurchasingRFQs r
                     WHERE r.ProjectID = ol.ProjectID AND r.SpecID = ol.SpecID AND r.ItemID = ol.ItemID) k3
        OUTER APPLY (SELECT TOP 1 ItemID FROM dbo.vwPurchasingRFQs r
                     WHERE r.ProjectID = ol.ProjectID AND r.ItemID = ol.ItemID) k2
        OUTER APPLY (SELECT TOP 1 ItemID FROM dbo.vwPurchasingRFQs r
                     WHERE r.ItemID = ol.ItemID) k1
    """
    run(cur, "3. match counts at each join grain", base)

    # ── 4. Do the matched rows carry a LastRFQID that resolves to an RFQDate? ────
    rule(f"4. LastRFQID → tblRFQHeader.RFQDate resolution for project {SAMPLE_PROJECT}")
    run(cur, "4. RFQ rows for this project: how many have LastRFQID, and does RFQDate resolve?",
        f"""
        SELECT
          COUNT(*) AS rfq_rows,
          SUM(CASE WHEN prq.LastRFQID IS NOT NULL THEN 1 ELSE 0 END) AS have_lastrfqid,
          SUM(CASE WHEN rfqh.RFQID IS NOT NULL THEN 1 ELSE 0 END) AS resolve_header,
          SUM(CASE WHEN rfqh.RFQDate IS NOT NULL THEN 1 ELSE 0 END) AS have_rfqdate
        FROM dbo.vwPurchasingRFQs prq
        LEFT JOIN dbo.tblRFQHeader rfqh ON rfqh.RFQID = prq.LastRFQID
        WHERE prq.ProjectID = {SAMPLE_PROJECT}
        """)
    run(cur, "4b. sample resolved rows",
        f"""
        SELECT TOP 15 prq.ProjectID, prq.SpecID, prq.ItemID, prq.LastRFQID,
                      CAST(rfqh.RFQDate AS date) AS RFQDate
        FROM dbo.vwPurchasingRFQs prq
        LEFT JOIN dbo.tblRFQHeader rfqh ON rfqh.RFQID = prq.LastRFQID
        WHERE prq.ProjectID = {SAMPLE_PROJECT}
        ORDER BY prq.ItemID
        """)

    eto.close()
    print("\nDONE — paste everything above.")


if __name__ == "__main__":
    main()
