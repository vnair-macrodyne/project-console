"""
console_diag_exception_fields2.py — ROUND 2: coverage of the two live candidates for the Exception
report's blank fields.  (2026-09-05)  READ-ONLY.

Round 1 concluded:
  * PermitDates / RFQDate / LeadTime → no maintained, line-linkable source → drop.
  * PlannedShip  → candidate tblSpec.BudgetShipRelease (a budgeted ship-release date ON the machine
                   /spec; joins to the PO line by ProjectID + SpecID).
  * DaysToAssembly → candidate: the process/production schedule (tblProcessScheduleHeader.StartDate /
                   FinalRequiredDate), or derive from the ship-release.

This confirms whether those are actually maintained (and how to join them).

Run:  python console_diag_exception_fields2.py [projectID]
Paste the whole output.
"""
import sys


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
    print("\n" + "=" * 78 + f"\n{t}\n" + "=" * 78)


def rows(cur, sql, *a):
    cur.execute(sql, *a)
    cols = [d[0] for d in cur.description]
    return cols, cur.fetchall()


def cols_of(cur, obj):
    _, r = rows(cur, "SELECT COLUMN_NAME, DATA_TYPE FROM INFORMATION_SCHEMA.COLUMNS "
                     "WHERE TABLE_NAME = ? ORDER BY ORDINAL_POSITION", obj)
    return r


def cov(cur, table, col):
    try:
        _, r = rows(cur, f"SELECT COUNT(*) n, "
                         f"SUM(CASE WHEN [{col}] IS NOT NULL THEN 1 ELSE 0 END) filled, "
                         f"MIN([{col}]) mn, MAX([{col}]) mx FROM [{table}]")
        n, filled, mn, mx = r[0]
        pct = (100.0 * filled / n) if n else 0
        print(f"    {table}.{col:26} {filled}/{n} ({pct:.1f}%)  min={str(mn)[:19]} max={str(mx)[:19]}")
    except Exception as e:
        print(f"    {table}.{col}: err {e}")


def main():
    proj = sys.argv[1] if len(sys.argv) > 1 else "250161"
    eto = eto_connect(); cur = eto.cursor()

    # ── PlannedShip via tblSpec.BudgetShipRelease ────────────────────────────
    rule("A. tblSpec — key columns + BudgetShipRelease coverage (PlannedShip candidate)")
    sc = cols_of(cur, "tblSpec")
    print("  key/date columns on tblSpec:")
    for c, t in sc:
        if c in ("ProjectID", "SpecID", "SpecNumber", "SDescription", "SpecName") or "date" in t.lower() \
                or "ship" in c.lower() or "release" in c.lower() or "deliver" in c.lower():
            print(f"     {c:34} {t}")
    print("  coverage:")
    for c, t in sc:
        if "date" in t.lower() or "ship" in c.lower() or "release" in c.lower() or "deliver" in c.lower():
            cov(cur, "tblSpec", c)
    rule(f"A2. tblSpec rows for project {proj} — SpecID → BudgetShipRelease (does each machine carry it?)")
    try:
        hdr, r = rows(cur, "SELECT SpecID, BudgetShipRelease FROM tblSpec WHERE ProjectID = ? ORDER BY SpecID", proj)
        print("   " + " | ".join(hdr))
        for row in r[:40]:
            print("   " + " | ".join(str(x) for x in row))
        print(f"   ({len(r)} spec rows)")
    except Exception as e:
        print("   err:", e)

    # ── DaysToAssembly via process schedule ──────────────────────────────────
    rule("B. Process-schedule tables (DaysToAssembly candidate) — columns + coverage")
    _, pst = rows(cur, "SELECT TABLE_NAME FROM INFORMATION_SCHEMA.TABLES "
                       "WHERE LOWER(TABLE_NAME) LIKE '%processschedule%' ORDER BY TABLE_NAME")
    for (tn,) in pst:
        print(f"\n  {tn}:")
        for c, t in cols_of(cur, tn):
            if c in ("ProjectID", "SpecID") or "date" in t.lower() or "start" in c.lower():
                print(f"     {c:34} {t}")
        for c, t in cols_of(cur, tn):
            if ("date" in t.lower() or "start" in c.lower()):
                cov(cur, tn, c)
    rule(f"B2. process-schedule rows for project {proj} (is it per project/spec, with a start date?)")
    for (tn,) in pst:
        cs = [c for c, _ in cols_of(cur, tn)]
        if "ProjectID" not in cs:
            print(f"  {tn}: no ProjectID column — skipping")
            continue
        keep = [c for c in cs if c in ("ProjectID", "SpecID") or c.lower().endswith("date")
                or "start" in c.lower()][:8]
        sel = ", ".join(f"[{c}]" for c in keep)
        try:
            hdr, r = rows(cur, f"SELECT TOP 10 {sel} FROM [{tn}] WHERE ProjectID = ?", proj)
            print(f"\n  {tn}:  " + " | ".join(hdr))
            for row in r:
                print("   " + " | ".join(str(x) for x in row))
            if not r:
                print("   (no rows for this project)")
        except Exception as e:
            print(f"  {tn}: err {e}")

    # ── alt PlannedShip: tblMasterQueue.ShipReleaseDate ──────────────────────
    rule("C. tblMasterQueue.ShipReleaseDate — coverage + keys (alt PlannedShip source)")
    mqc = [c for c, _ in cols_of(cur, "tblMasterQueue")]
    print("  key columns present:", [c for c in mqc if c in ("ProjectID", "SpecID", "ShipReleaseDate")])
    cov(cur, "tblMasterQueue", "ShipReleaseDate")

    # ── confirm there is NO PO-line → RFQ link ───────────────────────────────
    rule("D. Any RFQ id on the PO line? (would be the only way to attach an RFQ date)")
    for obj in ("tblPurchaseOrderDetails", "vwPurchaseOrderDetails", "vwPurchaseOrderDetailsDetailed",
                "tblPurchaseOrderHeader"):
        hits = [c for c, _ in cols_of(cur, obj) if "rfq" in c.lower()]
        print(f"  {obj}: RFQ columns = {hits or 'NONE'}")

    eto.close()
    print("\nRead: BudgetShipRelease well-filled + present per machine on the sample ⇒ wire PlannedShip "
          "from it (join tblSpec on ProjectID+SpecID). A process-schedule StartDate per project/spec ⇒ "
          "DaysToAssembly = that date − today. No RFQ id on the PO line ⇒ RFQDate stays undroppable-blank "
          "→ drop it (with PermitDates and the ~0%-filled LeadTime).")


if __name__ == "__main__":
    main()
