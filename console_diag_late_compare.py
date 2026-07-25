"""
console_diag_late_compare.py — EXEC ETO's urpPurchasingLateVendors and compare it,
line-for-line, against the console's lateness logic (read-only).

urpPurchasingLateVendors params (confirmed): @nvcCompanyIDIn (supplier filter, NULL = all),
@datPOCreatedLower, @datPOCreatedUpper (both required). It has NO project param, so we run it
over a wide PO-created window and filter to --project in Python.

What it shows:
  A. ETO's native output = RECEIVED lines that arrived AFTER need-by (backward-looking).
     need-by = ISNULL(DateRevised, DateRequired); DaysLate = receipt(MaxOfDate) − need-by.
  B. Algorithm check — recompute DaysLate ourselves and confirm it equals ETO's column.
  C. The console's Late Vendors = OPEN lines overdue NOW (forward-looking): same need-by
     definition, DaysLate = today − need-by, from pod.Received (no receiver log).
  D. Reconciliation — the two populations are disjoint (a line is either received or open);
     together they are every late line, past + present. Plus a vendor scorecard from ETO.

Run on the box:
    python console_diag_late_compare.py --project 230219
    python console_diag_late_compare.py --project 230219 --lower 2015-01-01 --upper 2027-12-31
Paste the WHOLE output back.
"""
import argparse
import datetime as dt


def connect():
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
    print("\n" + "=" * 84 + f"\n{t}\n" + "=" * 84)


def _d(v):
    """coerce pyodbc datetime/date/None -> date or None"""
    if v is None:
        return None
    if isinstance(v, dt.datetime):
        return v.date()
    if isinstance(v, dt.date):
        return v
    try:
        return dt.date.fromisoformat(str(v)[:10])
    except Exception:
        return None


def _f(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--project", required=True, help="ProjectID to compare (proc has no project param; we filter)")
    ap.add_argument("--lower", default="2015-01-01", help="@datPOCreatedLower (PO-created window)")
    ap.add_argument("--upper", default="2027-12-31", help="@datPOCreatedUpper")
    args = ap.parse_args()
    pid = int(args.project.split(",")[0])
    today = dt.date.today()
    conn = connect(); cur = conn.cursor()

    # ── A. EXEC the native late report over a wide window, filter to the project ──
    rule(f"A. ETO dbo.urpPurchasingLateVendors  (RECEIVED-late lines)  ·  project {pid}")
    print(f"   EXEC window: PO created {args.lower} → {args.upper} (all suppliers)")
    try:
        cur.execute(
            "SET NOCOUNT ON; EXEC dbo.urpPurchasingLateVendors "
            "@nvcCompanyIDIn=NULL, @datPOCreatedLower=?, @datPOCreatedUpper=?",
            args.lower, args.upper)
        cols = [c[0] for c in cur.description]
        raw = cur.fetchall()
    except Exception as ex:
        print(f"   !! EXEC failed: {ex}")
        conn.close()
        return
    print(f"   proc returned {len(raw)} row(s) total; columns: {', '.join(cols)}")

    idx = {c: i for i, c in enumerate(cols)}

    def g(row, name):
        return row[idx[name]] if name in idx else None

    eto = [r for r in raw if g(r, "ProjectID") == pid]
    print(f"\n   {len(eto)} received-late line(s) for project {pid}:")
    hdr = f"   {'Supplier':22} {'PO':>7} {'Item':>8} {'need-by':>11} {'receipt':>11} " \
          f"{'ETO':>5} {'recalc':>6} {'ok':>3} {'Rcvd':>7} {'ExtValue':>12}"
    print(hdr)
    mismatches = 0
    eto_total = 0.0
    for r in eto[:60]:
        req, rev = _d(g(r, "DateRequired")), _d(g(r, "DateRevised"))
        need = rev or req
        receipt = _d(g(r, "MaxOfDate"))
        eto_days = g(r, "DaysLate")
        recalc = (receipt - need).days if (receipt and need) else None
        ok = "=" if (recalc is not None and int(eto_days) == recalc) else "X"
        if ok == "X":
            mismatches += 1
        ext = _f(g(r, "ExtendedPriceExchange") if "ExtendedPriceExchange" in idx else g(r, "ExtendedPrice"))
        eto_total += ext
        sup = str(g(r, "SupplierName") or "")[:22]
        print(f"   {sup:22} {str(g(r,'PurchaseOrderID')):>7} {str(g(r,'ItemID')):>8} "
              f"{str(need):>11} {str(receipt):>11} {str(eto_days):>5} {str(recalc):>6} {ok:>3} "
              f"{_f(g(r,'QtyReceived')):>7.2f} {ext:>12,.2f}")
    if len(eto) > 60:
        print(f"   … (+{len(eto)-60} more)")
    for r in eto:      # total over ALL, not just printed
        pass
    eto_total = sum(_f(g(r, "ExtendedPriceExchange") if "ExtendedPriceExchange" in idx else g(r, "ExtendedPrice")) for r in eto)

    # ── B. algorithm check ──
    rule("B. ALGORITHM CHECK — does our need-by / DaysLate arithmetic equal ETO's?")
    print(f"   need-by = ISNULL(DateRevised, DateRequired); DaysLate = receipt − need-by")
    print(f"   rows compared: {len(eto)}   mismatches: {mismatches}   "
          f"=> {'MATCH — we replicate ETO exactly' if mismatches == 0 else 'REVIEW mismatches above'}")

    # ── C. the console's Late Vendors: OPEN lines overdue now ──
    rule(f"C. CONSOLE Late Vendors  (OPEN lines overdue as at {today})  ·  project {pid}")
    cur.execute(f"""
        SELECT poh.CName AS Supplier, poh.PurchaseOrderID AS PO, pod.ItemID AS Item,
               CAST(pod.DateRequired AS date) AS Required, CAST(pod.DateRevised AS date) AS Revised,
               DATEDIFF(d, ISNULL(pod.DateRevised, pod.DateRequired), CAST(GETDATE() AS date)) AS DaysLate,
               pod.PurchaseQty AS Qty, pod.Received AS Received, pod.ExtendedPrice AS ExtValue
        FROM vwPurchaseOrderHeader poh
        JOIN vwPurchaseOrderDetails pod ON pod.PurchaseOrderID = poh.PurchaseOrderID
        WHERE poh.PurchaseActive = 1
          AND (pod.Received IS NULL OR pod.Received < pod.PurchaseQty)
          AND ISNULL(pod.DateRevised, pod.DateRequired) < CAST(GETDATE() AS date)
          AND pod.ProjectID = ?
        ORDER BY DaysLate DESC""", pid)
    ours = cur.fetchall()
    our_total = sum(_f(r[8]) for r in ours)
    print(f"   {len(ours)} overdue open line(s):")
    print(f"   {'Supplier':22} {'PO':>7} {'Item':>8} {'need-by':>11} {'daysLate':>8} "
          f"{'Qty':>6} {'Rcvd':>6} {'ExtValue':>12}")
    for r in ours[:60]:
        need = _d(r[4]) or _d(r[3])
        print(f"   {str(r[0] or '')[:22]:22} {str(r[1]):>7} {str(r[2]):>8} {str(need):>11} "
              f"{str(r[5]):>8} {_f(r[6]):>6.1f} {_f(r[7]):>6.1f} {_f(r[8]):>12,.2f}")
    if len(ours) > 60:
        print(f"   … (+{len(ours)-60} more)")

    # ── D. reconciliation ──
    rule("D. RECONCILIATION")
    print(f"   ETO received-late (arrived late):     {len(eto):>4} line(s)   ${eto_total:>14,.2f}")
    print(f"   console overdue-open (late now):      {len(ours):>4} line(s)   ${our_total:>14,.2f}")
    eto_keys = {(str(g(r, "PurchaseOrderID")), str(g(r, "ItemID"))) for r in eto}
    our_keys = {(str(r[1]), str(r[2])) for r in ours}
    overlap = eto_keys & our_keys
    print(f"   overlap (same PO+Item in BOTH):       {len(overlap)}  "
          f"(expected 0 — a line is either received or still open)")
    if overlap:
        for k in list(overlap)[:20]:
            print(f"       PO {k[0]} item {k[1]}")

    # vendor scorecard from ETO's received-late rows
    rule("D2. VENDOR SCORECARD from ETO (received-late), project " + str(pid))
    by = {}
    for r in eto:
        sup = str(g(r, "SupplierName") or "(unknown)")
        d = by.setdefault(sup, {"n": 0, "days": 0, "val": 0.0})
        d["n"] += 1
        d["days"] += int(g(r, "DaysLate") or 0)
        d["val"] += _f(g(r, "ExtendedPriceExchange") if "ExtendedPriceExchange" in idx else g(r, "ExtendedPrice"))
    print(f"   {'Supplier':28} {'#late':>6} {'avg days':>9} {'total $':>14}")
    for sup, d in sorted(by.items(), key=lambda kv: -kv[1]["val"]):
        print(f"   {sup[:28]:28} {d['n']:>6} {d['days']/d['n']:>9.1f} {d['val']:>14,.2f}")

    conn.close()
    print("\nDone. Paste the whole output back.")


if __name__ == "__main__":
    main()
