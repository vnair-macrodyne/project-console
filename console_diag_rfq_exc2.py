"""
console_diag_rfq_exc2.py — run the ENRICHED exception query for real and isolate WHY it throws.
READ-ONLY.  Nothing is written.  (2026-09-12)

RFQ is NOT the culprit (probe 1 proved the join matches 38/70 open lines and every RFQ row resolves
to a real RFQDate). The report is blank because the ENRICHED query_po_exceptions(True, …) throws and
_q_po_exceptions silently falls back to the NON-enriched query, which blanks RFQDate / LeadDays / LLT
/ Oversized / EngRelease together.  The earlier probe couldn't import etospec (it lives in console_web/).

This probe:
  1. Imports etospec robustly (adds console_web to sys.path) and prints the custom-field column names
     it assumes on tblEngItemMaster (_LLT_FLAG_COL / _OVERSIZE_FLAG_COL / _ENG_RELEASE_COL).
  2. Checks tblEngItemMaster actually HAS those columns + EstimatedLeadTime (the most likely throw).
  3. Runs the FULL enriched query and prints the REAL exception (or success + how many rows got
     RFQDate / LeadDays).
  4. If it throws, runs reduced variants (lead-only, rfq-only, bom-release-only) to pinpoint the piece.

Run from the repo root where the app lives:
    python console_diag_rfq_exc2.py [projectID]
Paste the WHOLE output back.
"""
import sys, os

SAMPLE_PROJECT = int(sys.argv[1]) if len(sys.argv) > 1 else 250250


def import_etospec():
    for p in ("console_web", os.path.join(os.path.dirname(os.path.abspath(__file__)), "console_web")):
        if os.path.isdir(p) and p not in sys.path:
            sys.path.insert(0, p)
    import etospec  # noqa
    return etospec


def eto_connect():
    try:
        from console_store import eto_connection
        return eto_connection()
    except Exception:
        import pyodbc
        from console_config import TENANT
        cs = (f"Driver={{ODBC Driver 17 for SQL Server}};Server={TENANT.eto_server};"
              f"Database={TENANT.eto_database};")
        cs += ("Trusted_Connection=yes;" if TENANT.use_windows_auth
               else f"UID={os.environ.get('ETO_USER')};PWD={os.environ.get('ETO_PWD')};")
        return pyodbc.connect(cs)


def rule(t):
    print("\n" + "=" * 88 + f"\n{t}\n" + "=" * 88)


def try_exec(cur, label, sql):
    print(f"\n-- {label}")
    try:
        cur.execute(sql)
        cols = [d[0] for d in cur.description]
        rows = cur.fetchall()
        idx = {c: cols.index(c) for c in ("RFQDate", "LeadDays", "OverFlag", "EngReleaseDate") if c in cols}
        print(f"   OK — {len(rows)} rows.")
        for c, i in idx.items():
            print(f"      {c}: populated on {sum(1 for r in rows if r[i] is not None)} / {len(rows)}")
        return True
    except Exception as e:
        print(f"   !! {type(e).__name__}: {e}")
        return False


def main():
    try:
        etospec = import_etospec()
    except Exception as e:
        print(f"!! still cannot import etospec: {type(e).__name__}: {e}")
        print("   (run this from the repo root; console_web/etospec.py must exist below it)")
        return

    eto = eto_connect()
    cur = eto.cursor()

    # ── 1. The custom-field column names etospec assumes ─────────────────────────
    rule("1. Custom-field column names etospec uses on tblEngItemMaster")
    for nm in ("_LLT_FLAG_COL", "_OVERSIZE_FLAG_COL", "_ENG_RELEASE_COL"):
        print(f"   etospec.{nm} = {getattr(etospec, nm, '(missing)')!r}")

    # ── 2. Do those columns actually exist on tblEngItemMaster? ──────────────────
    rule("2. tblEngItemMaster — do the assumed columns exist?")
    cur.execute("SELECT COLUMN_NAME FROM INFORMATION_SCHEMA.COLUMNS WHERE TABLE_NAME='tblEngItemMaster'")
    have = {r[0].lower() for r in cur.fetchall()}
    wanted = ["EstimatedLeadTime",
              getattr(etospec, "_LLT_FLAG_COL", ""),
              getattr(etospec, "_OVERSIZE_FLAG_COL", ""),
              getattr(etospec, "_ENG_RELEASE_COL", "")]
    any_missing = False
    for w in wanted:
        if w:
            miss = w.lower() not in have
            any_missing = any_missing or miss
            print(f"   [{'OK ' if not miss else 'MISSING'}] {w}")
    # If any are missing, show the REAL candidate columns so we can correct the names in one pass.
    if any_missing:
        print("\n   >>> at least one assumed column is MISSING — candidate real columns on tblEngItemMaster:")
        cur.execute("""SELECT COLUMN_NAME, DATA_TYPE FROM INFORMATION_SCHEMA.COLUMNS
                       WHERE TABLE_NAME='tblEngItemMaster'
                         AND (COLUMN_NAME LIKE '%Custom%' OR COLUMN_NAME LIKE '%Lead%'
                           OR COLUMN_NAME LIKE '%Over%' OR COLUMN_NAME LIKE '%Release%'
                           OR COLUMN_NAME LIKE '%LLT%' OR COLUMN_NAME LIKE '%Long%')
                       ORDER BY COLUMN_NAME""")
        for r in cur.fetchall():
            print(f"      {r[0]} : {r[1]}")

    # ── 3. Run the full enriched query — the real error, if any ──────────────────
    rule(f"3. FULL enriched query_po_exceptions(True, [{SAMPLE_PROJECT}]) — the masked error")
    ok = try_exec(cur, "enriched (lead + rfq + oversized + eng-release)",
                  etospec.query_po_exceptions(True, [SAMPLE_PROJECT]))

    # ── 4. If it threw, isolate the piece ────────────────────────────────────────
    if not ok:
        rule("4. ISOLATE the throwing piece (reduced queries)")
        # lead/oversized/eng-release block only — no RFQ
        lead_only = f"""
            SELECT pod.ProjectID, eim.EstimatedLeadTime AS LeadDays,
                   eim.[{getattr(etospec,'_OVERSIZE_FLAG_COL','')}] AS OverFlag,
                   CAST(eim.[{getattr(etospec,'_ENG_RELEASE_COL','')}] AS date) AS EngReleaseDate
            FROM dbo.vwPurchaseOrderDetails pod
            LEFT JOIN dbo.tblEngItemMaster eim ON eim.ItemID = pod.ItemID
            WHERE pod.ProjectID = {SAMPLE_PROJECT}"""
        try_exec(cur, "4a. lead/oversized/eng-release columns only", lead_only)

        rfq_only = f"""
            SELECT pod.ProjectID, CAST(rfqh.RFQDate AS date) AS RFQDate
            FROM dbo.vwPurchaseOrderDetails pod
            LEFT JOIN dbo.vwPurchasingRFQs prq ON prq.ProjectID = pod.ProjectID
                 AND prq.ItemID = pod.ItemID AND prq.SpecID = pod.SpecID
            LEFT JOIN dbo.tblRFQHeader rfqh ON rfqh.RFQID = prq.LastRFQID
            WHERE pod.ProjectID = {SAMPLE_PROJECT}"""
        try_exec(cur, "4b. RFQ join only", rfq_only)

    eto.close()
    print("\nDONE — paste everything above.")


if __name__ == "__main__":
    main()
