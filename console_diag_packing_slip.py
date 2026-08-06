"""
console_diag_packing_slip.py — build data for a PACKING SLIP report + trace the missing shipped
part + look for inventory transfers (round 2, 2026-08-06).

Round 1 found a full packing-slip subsystem: tblPackingSlipHeader, tblPackingSlipDetail
(ProjectID+SpecID+ItemID+Quantity+PackingSlipPartNumber/Description), tblPackingSlipNotes/Documents,
tlkpPackingSlipType, tlkpShippers, tlkpShippingPriority, plus views vwPackingSlipDetails,
vwPackingSlips_SearchResults, vwShipments. Detail is directly project-scoped. Receiving = only
tblReceiverLog/vwReceiverLog. No inventory-transfer table (only Change-Order $ adjustments).

This maps what a Packing Slip report needs and traces the flagged part:
  (A) tblPackingSlipHeader shape (doc no, dates, shipper, type, project?) + the lookups;
  (B) the ready-made VIEWS (vwPackingSlipDetails / vwPackingSlips_SearchResults / vwShipments) —
      prefer a view that already joins header+detail+lookups;
  (C) header→detail joined sample for a project (what the report rows look like);
  (D) TRACE the missing part 220154-10M* — where does it live: on-hand (incl qty 0), POs,
      packing slips?
  (E) TRANSFERS: broad search for any object with from/to location, and a peek at the
      inventory-pulls costing views (stock movement OUT to a project).

READ-ONLY. Run:
    python console_diag_packing_slip.py                    # project 220154, part 220154-10M%
    python console_diag_packing_slip.py 192085 192085-%
Paste the WHOLE output.
"""

import sys


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


def run(cur, label, sql, params=(), max_rows=25):
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
    try:
        cur.execute("SELECT COLUMN_NAME, DATA_TYPE FROM INFORMATION_SCHEMA.COLUMNS "
                    "WHERE TABLE_NAME = ? ORDER BY ORDINAL_POSITION", (name,))
        return [(r[0], r[1]) for r in cur.fetchall()]
    except Exception:
        return []


def has_col(cur, name, col):
    return any(c[0].lower() == col.lower() for c in columns_of(cur, name))


def show_cols(cur, name):
    cols = columns_of(cur, name)
    if not cols:
        print(f"\n  {name}: (not found)")
        return None
    print(f"\n  {name} ({len(cols)} cols):")
    for n, t in cols:
        print(f"    {n} : {t}")
    return cols


def main():
    args = sys.argv[1:]
    proj = next((a for a in args if a.isdigit()), "220154")
    pat = next((a for a in args if not a.isdigit()), None) or f"{proj}-10M%"
    conn = eto_connect()
    cur = conn.cursor()
    print(f"Project = {proj}   traced part pattern = '{pat}'")
    try:
        # ── A. header + lookups ───────────────────────────────────────────────
        rule("A. PACKING SLIP HEADER + LOOKUPS (columns)")
        hcols = show_cols(cur, "tblPackingSlipHeader")
        for lk in ("tlkpPackingSlipType", "tlkpShippers", "tlkpShippingPriority"):
            show_cols(cur, lk)
        if hcols:
            run(cur, "A2. tblPackingSlipHeader — sample rows",
                "SELECT TOP 10 * FROM dbo.tblPackingSlipHeader ORDER BY 1 DESC")

        # ── B. ready-made views (prefer these for the report) ─────────────────
        rule("B. PACKING-SLIP / SHIPMENT VIEWS (prefer a view that already joins everything)")
        for v in ("vwPackingSlipDetails", "vwPackingSlips_SearchResults", "vwShipments",
                  "vwQueueShipping", "vwPartsOrderDetailShippingTotal"):
            cols = show_cols(cur, v)
            if cols:
                pcol = next((c[0] for c in cols if c[0].lower() in ("projectid", "specid")), None)
                if pcol:
                    run(cur, f"B/{v} — sample for project {proj} (on {pcol})",
                        f"SELECT TOP 12 * FROM dbo.{v} WHERE [{pcol}] = ?", (proj,))
                else:
                    run(cur, f"B/{v} — TOP 8 (no ProjectID col)",
                        f"SELECT TOP 8 * FROM dbo.{v}")

        # ── C. header→detail joined sample (what report rows look like) ───────
        rule(f"C. HEADER→DETAIL JOINED SAMPLE for project {proj}")
        if hcols:
            join_key = next((c[0] for c in hcols if c[0].lower() == "packingslipid"), None)
            hdr_no = next((c[0] for c in hcols if "number" in c[0].lower()
                           or "slipno" in c[0].lower() or c[0].lower() == "packingslipid"), None)
            hdr_date = next((c[0] for c in hcols if c[1].lower() in ("datetime", "date")), None)
            if join_key:
                sel_hdr = ", ".join(f"h.[{c}]" for c in
                                    [c for c in (hdr_no, hdr_date) if c])
                run(cur, "C1. joined packing-slip lines for the project",
                    f"SELECT TOP 20 {sel_hdr + ', ' if sel_hdr else ''}"
                    "d.ItemID, d.PackingSlipPartNumber, d.PackingSlipPartDescription, d.Quantity "
                    "FROM dbo.tblPackingSlipDetail d "
                    f"JOIN dbo.tblPackingSlipHeader h ON h.[{join_key}] = d.[{join_key}] "
                    "WHERE d.ProjectID = ? ORDER BY d.PackingSlipID DESC", (proj,))

        # ── D. trace the missing part ─────────────────────────────────────────
        rule(f"D. TRACE PART LIKE '{pat}' — on-hand, POs, packing slips")
        run(cur, "D1. in vwInventory (ALL on-hand incl 0)",
            "SELECT ItemCompanyID, ItemDescription, LocationName, QtyOnHand "
            "FROM dbo.vwInventory WHERE ItemCompanyID LIKE ? ORDER BY ItemCompanyID", (pat,))
        run(cur, f"D2. on the project's PO lines",
            "SELECT TOP 20 ItemID, ItemDescription, PurchaseQty, Received "
            "FROM dbo.vwPurchaseOrderDetails WHERE ProjectID = ? AND ItemDescription LIKE ? "
            "OR ItemID IN (SELECT ItemID FROM dbo.vwInventory WHERE ItemCompanyID LIKE ?)",
            (proj, pat, pat))
        run(cur, f"D3. on packing slips (by part number)",
            "SELECT TOP 20 PackingSlipID, ProjectID, ItemID, PackingSlipPartNumber, "
            "PackingSlipPartDescription, Quantity "
            "FROM dbo.tblPackingSlipDetail WHERE PackingSlipPartNumber LIKE ? OR ProjectID = ? "
            "ORDER BY PackingSlipID DESC", (pat, proj))

        # ── E. transfers / inventory pulls ────────────────────────────────────
        rule("E. INVENTORY TRANSFERS / PULLS (stock movement)")
        run(cur, "E1. any object with BOTH a from- and to-location column",
            "SELECT DISTINCT c1.TABLE_NAME FROM INFORMATION_SCHEMA.COLUMNS c1 "
            "JOIN INFORMATION_SCHEMA.COLUMNS c2 ON c1.TABLE_NAME = c2.TABLE_NAME "
            "WHERE (c1.COLUMN_NAME LIKE '%From%Loc%' OR c1.COLUMN_NAME LIKE '%Source%Loc%') "
            "AND (c2.COLUMN_NAME LIKE '%To%Loc%' OR c2.COLUMN_NAME LIKE '%Dest%Loc%') "
            "ORDER BY c1.TABLE_NAME", max_rows=40)
        run(cur, "E2. objects named like pull / move / issue / transfer",
            "SELECT TABLE_NAME, TABLE_TYPE FROM INFORMATION_SCHEMA.TABLES "
            "WHERE TABLE_NAME LIKE '%Pull%' OR TABLE_NAME LIKE '%Move%' "
            "OR TABLE_NAME LIKE '%Issue%' OR TABLE_NAME LIKE '%Transfer%' ORDER BY TABLE_NAME",
            max_rows=40)
        # inventory pulls carry item + location + qty + project — the closest thing to a transfer
        pull = show_cols(cur, "vwCostingInventoryPullsDetailed")
        if pull:
            pcol = next((c[0] for c in pull if c[0].lower() in ("projectid", "specid")), None)
            if pcol:
                run(cur, f"E3. vwCostingInventoryPullsDetailed — sample for project {proj}",
                    f"SELECT TOP 15 * FROM dbo.vwCostingInventoryPullsDetailed WHERE [{pcol}] = ?",
                    (proj,))

    finally:
        conn.close()
    print("\nDone. Decision it drives:")
    print("  • A/B: pick the packing-slip source — a VIEW that already joins header+detail+shipper")
    print("    is ideal; else header⋈detail (C1). We need doc no, date, shipper, item, qty.")
    print("  • D: confirms the flagged part is a shipped line (D3) and/or a qty-0 on-hand row (D1)")
    print("    — i.e. it belongs on the packing-slip report, not an inventory-scope change.")
    print("  • E: whether ETO models transfers at all. If only pulls (E3), 'transfers' likely means")
    print("    stock pulled/allocated to projects — confirm the intended meaning with the team.")


if __name__ == "__main__":
    main()
