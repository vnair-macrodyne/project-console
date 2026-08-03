"""
console_diag_po_to_order2.py — nail the ETO "issued" signal (2026-08-03, follow-up).

Probe 1 showed: no PO status lookup; PurchaseDate + PurchaseActive are set on ALL 38,258 headers
(so neither = issued). The real issue signal at Macrodyne is almost certainly the send flags the
first probe's name list missed:  PurchasePrinted (bit) and PurchaseEmailed (bit). A PO that is
NOT printed AND NOT emailed is a draft — i.e. its lines are "to order". Two custom bits
(PurchaseOrderHeaderCustom7/8) may also carry an approval/issue flag.

This probe (READ-ONLY):
  A. dumps vwPurchaseOrderDetails columns (need the Spec/Machine field for project→machine grouping)
  B. profiles PurchasePrinted / PurchaseEmailed / Custom7 / Custom8 / PurchaseRev
  C. counts the candidate "not sent" backlog (Printed=0 AND Emailed=0), and the open part of it
  D. scoped to tracked projects: to-order lines per project + a sample + how old the un-sent POs are

Run:  python console_diag_po_to_order2.py   → paste the whole output. Nothing is written.
"""

HDR = "vwPurchaseOrderHeader"
TBL = "tblPurchaseOrderHeader"
DET = "vwPurchaseOrderDetails"


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
    try:
        from console.infra.connections import console_connection
        c = console_connection()
        cur = c.cursor()
        cur.execute("SELECT DISTINCT ProjectID FROM Reporting.vw_Console_BudgetCurrent ORDER BY ProjectID")
        ids = [int(r[0]) for r in cur.fetchall()][:max_n]
        c.close()
        return ids
    except Exception as e:
        print(f"  [note] no tracked ids ({type(e).__name__}: {e})")
        return []


def rule(t):
    print("\n" + "=" * 78 + f"\n{t}\n" + "=" * 78)


def run(cur, label, sql, params=(), max_rows=40):
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


def main():
    conn = eto_connect()
    cur = conn.cursor()
    ids = tracked_ids()
    idlist = ",".join(str(i) for i in ids) if ids else None
    NOTSENT = "(poh.PurchasePrinted = 0 AND poh.PurchaseEmailed = 0)"
    try:
        # ── A. detail columns (for project→machine grouping + line fields) ───────
        rule("A. vwPurchaseOrderDetails COLUMNS (find Spec/Machine + item/qty/date fields)")
        run(cur, "A1. columns",
            "SELECT COLUMN_NAME, DATA_TYPE FROM INFORMATION_SCHEMA.COLUMNS "
            f"WHERE TABLE_NAME = '{DET}' ORDER BY ORDINAL_POSITION", max_rows=80)

        # ── B. profile the send/issue flags ──────────────────────────────────────
        rule("B. ISSUE-FLAG PROFILING on " + TBL)
        for col in ("PurchasePrinted", "PurchaseEmailed",
                    "PurchaseOrderHeaderCustom7", "PurchaseOrderHeaderCustom8"):
            run(cur, f"B/{col} — value distribution",
                f"SELECT {col} AS value, COUNT(*) AS n FROM dbo.{TBL} GROUP BY {col} ORDER BY n DESC")
        run(cur, "B/PurchaseRev — distribution (0 may = draft rev)",
            f"SELECT PurchaseRev AS value, COUNT(*) AS n FROM dbo.{TBL} "
            "GROUP BY PurchaseRev ORDER BY n DESC", max_rows=15)
        run(cur, "B/combined Printed×Emailed matrix",
            "SELECT PurchasePrinted, PurchaseEmailed, COUNT(*) AS n "
            f"FROM dbo.{TBL} GROUP BY PurchasePrinted, PurchaseEmailed ORDER BY n DESC")

        # ── C. the candidate 'to order' backlog, whole-DB ────────────────────────
        rule("C. CANDIDATE 'TO ORDER' BACKLOG — not printed AND not emailed")
        run(cur, "C1. header count not-sent vs sent",
            "SELECT CASE WHEN PurchasePrinted = 0 AND PurchaseEmailed = 0 THEN 'not sent' "
            "ELSE 'sent' END AS state, COUNT(*) AS headers "
            f"FROM dbo.{TBL} GROUP BY CASE WHEN PurchasePrinted = 0 AND PurchaseEmailed = 0 "
            "THEN 'not sent' ELSE 'sent' END")
        run(cur, "C2. detail lines on not-sent headers (all vs still-open)",
            "SELECT COUNT(*) AS ToOrderLines, "
            "SUM(CASE WHEN ISNULL(pod.Received,0) < pod.Quantity THEN 1 ELSE 0 END) AS OpenToOrder, "
            "CAST(SUM(pod.ExtendedPrice) AS decimal(20,2)) AS ExtValue "
            f"FROM dbo.{DET} pod JOIN dbo.{HDR} poh ON poh.PurchaseOrderID = pod.PurchaseOrderID "
            f"WHERE {NOTSENT}")

        # ── D. scoped to tracked projects ────────────────────────────────────────
        rule("D. TO-ORDER, SCOPED TO TRACKED PROJECTS")
        if not idlist:
            print("  (no tracked ids — skipping)")
        else:
            run(cur, "D1. to-order lines per project (not sent)",
                "SELECT pod.ProjectID, COUNT(*) AS ToOrderLines, "
                "CAST(SUM(pod.ExtendedPrice) AS decimal(20,2)) AS ExtValue "
                f"FROM dbo.{DET} pod JOIN dbo.{HDR} poh ON poh.PurchaseOrderID = pod.PurchaseOrderID "
                f"WHERE pod.ProjectID IN ({idlist}) AND {NOTSENT} "
                "GROUP BY pod.ProjectID ORDER BY ToOrderLines DESC")
            run(cur, "D2. sample not-sent lines (eyeball realism)",
                "SELECT TOP 15 pod.ProjectID, pod.PurchaseOrderID, poh.BuyerID, poh.CName, "
                "poh.PurchaseDate, poh.PurchaseDateRequired, pod.ExtendedPrice, pod.Received "
                f"FROM dbo.{DET} pod JOIN dbo.{HDR} poh ON poh.PurchaseOrderID = pod.PurchaseOrderID "
                f"WHERE pod.ProjectID IN ({idlist}) AND {NOTSENT} ORDER BY poh.PurchaseDate DESC")
            run(cur, "D3. age of the un-sent POs (are they a live backlog or stale?)",
                "SELECT DATEDIFF(day, poh.PurchaseDate, GETDATE())/30 AS months_old, "
                "COUNT(DISTINCT poh.PurchaseOrderID) AS pos "
                f"FROM dbo.{DET} pod JOIN dbo.{HDR} poh ON poh.PurchaseOrderID = pod.PurchaseOrderID "
                f"WHERE pod.ProjectID IN ({idlist}) AND {NOTSENT} "
                "GROUP BY DATEDIFF(day, poh.PurchaseDate, GETDATE())/30 ORDER BY months_old")
    finally:
        conn.close()
    print("\nDone. Paste the whole output.\n"
          "  • B: is the split Printed/Emailed (the send flags) — and do the custom bits carry anything?\n"
          "  • C/D: size + realism of 'not sent' = to-order. D3 tells us if it's a live backlog.\n"
          "  • A: which column names to use for machine/spec + item/qty/need-by in the report.")


if __name__ == "__main__":
    main()
