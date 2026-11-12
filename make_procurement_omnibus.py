"""
make_procurement_omnibus.py — ONE-OFF Procurement Omnibus workbook for Jason (requested via Peter, 12 Oct 2026).
READ-ONLY against ETO. Not part of the console: it reuses the console's purchasing reports so the numbers
match what Sextant shows, and writes one Excel file.

Workbook tabs
  Omnibus                — one row per line through the whole flow, Stage first, then the Procurement
                           Exceptions columns (Peter's 27-column layout):
                             To procure            ETO's Items to Procure (released / requested, no PO yet)
                             Requisition (draft PO) PO raised in ETO, not yet printed or emailed
                             On order              PO sent, not fully received (Status: Open / Overdue / partial)
                             Received              fully received
  Lines to Order         — the console report, as run at the same moment
  Purchase Requisitions  — idem
  PO Exceptions          — idem
  All Purchase Orders    — idem
  Info                   — run time, projects, stage counts, column notes

Run from the repo root where ETO and the Reporting DB are reachable:
    python make_procurement_omnibus.py                      # the uploaded active-projects list, minus Remove-from-Console
    python make_procurement_omnibus.py 250005 260178        # or name projects
    python make_procurement_omnibus.py --all                # EVERY project, all time, all statuses
Writes Procurement_Omnibus_<YYYYMMDD>.xlsx here and prints a summary.
"""
import sys, time, datetime as _dt

STAGES = ["To procure", "Requisition (draft PO)", "On order", "Received"]


def tracked_projects():
    """The projects the console selector shows = the uploaded active-projects list
    (Reporting.tblActiveProject) minus Remove-from-Console exclusions — the same set as
    queries.py LiveQueryService.list_projects (Vijay, 2026-11-04). Falls back to the banked console
    set only if the active list is empty."""
    from console_web.queries import LiveQueryService
    return [p["id"] for p in LiveQueryService().list_projects()]


def po_order_dates(pids):
    """{PurchaseOrderID (str): order date} for every PO touching the given projects — the PO header
    PurchaseDate (one date per PO), merged onto the Omnibus PO rows by PO number."""
    from console.infra.connections import eto_connection
    where = f"WHERE pod.ProjectID IN ({','.join(str(int(p)) for p in pids)})" if pids else ""
    c = eto_connection(); cur = c.cursor()
    cur.execute("SELECT DISTINCT poh.PurchaseOrderID, CAST(poh.PurchaseDate AS date) "
                "FROM dbo.vwPurchaseOrderHeader poh "
                "JOIN dbo.vwPurchaseOrderDetails pod ON pod.PurchaseOrderID = poh.PurchaseOrderID "
                f"{where}")
    m = {str(r[0]): r[1] for r in cur.fetchall()}
    c.close()
    return m


def released_by(pids):
    """{(ProjectID str, part number): (latest releaser 'Last, First', # release events)} — who most
    recently released the part and how many times (tblBOMReleaseHistory -> tblEmployee)."""
    from console.infra.connections import eto_connection
    where = f"WHERE h.ProjectID IN ({','.join(str(int(p)) for p in pids)})" if pids else ""
    c = eto_connection(); cur = c.cursor()
    cur.execute(f"""
        WITH rw AS (
          SELECT h.ProjectID, h.ItemID, h.ReleasedByEmployeeID,
                 ROW_NUMBER() OVER (PARTITION BY h.ProjectID, h.ItemID
                     ORDER BY h.ReleasedDateTime DESC, h.BOMReleaseHistoryID DESC) AS rn,
                 COUNT(*) OVER (PARTITION BY h.ProjectID, h.ItemID) AS RelCount
          FROM dbo.tblBOMReleaseHistory h {where}
        )
        SELECT rw.ProjectID, eim.ItemCompanyID,
               e.EmpLastName + ', ' + e.EmpFirstName AS ReleasedBy, rw.RelCount
        FROM rw
        JOIN dbo.tblEngItemMaster eim ON eim.ItemID = rw.ItemID
        JOIN dbo.tblEmployee e ON e.EmployeeID = rw.ReleasedByEmployeeID
        WHERE rw.rn = 1""")
    m = {(str(r[0]), r[1]): (r[2], r[3]) for r in cur.fetchall()}
    c.close()
    return m


def num(v):
    try:
        f = float(v)
        return None if f != f else f
    except (TypeError, ValueError):
        return None


def omnibus_rows(lto, items, cols_exc, podates, relby):
    import pandas as pd
    out = []
    for r in lto.rows:
        if r.get("_kind") != "detail":
            continue
        q = num(r.get("ToOrder"))
        out.append({
            "Stage": "To procure", "Buyer": "", "ReqNo": "", "RFQDate": r.get("RFQDate") or "",
            "PO": "", "OrderDate": "", "Cost": None, "Vendor": "",
            "ProjectID": "" if r.get("ProjectID") is None else str(r.get("ProjectID")),
            "JobName": r.get("JobName") or "", "Code": r.get("Machine") or "", "Item": r.get("ItemNo") or "",
            "Description": r.get("Description") or "", "Category": r.get("Category") or "",
            "DrawingNo": r.get("DrawingNo") or "",
            "EngRelease": r.get("FirstReleaseDate") or r.get("ReleaseDate") or "",
            "LatestRelease": r.get("ReleaseDate") or "", "TotalReleased": r.get("TotalReleased"),
            "PlannedShip": "", "PlannedReceipt": "", "RevisedReceipt": "", "ReceiptDate": "",
            "Status": "To procure: " + ("" if q is None else (str(int(q)) if q.is_integer() else f"{q:g}")),
            "LastUpdated": "", "MfgBegin": r.get("MfgBegin") or "", "PermitDates": "",
            "LeadTime": num(r.get("LeadTime")), "Oversized": r.get("Oversized") or "",
            "Inspected": r.get("Inspected") or "", "Critical": r.get("Critical") or "", "LLT": r.get("LLT") or "",
            # the release behind the line (Lines to Order now carries it per machine — 2026-11-04)
            "ReleasedBy": r.get("ReleasedBy") or "", "RelCount": r.get("RelCount"),
            "QtyChange": r.get("QtyChange"),
            "ToOrder": q, "PlannedReceipt": r.get("RequiredDate") or "",   # ETO's Required qty / Required Date
        })
    if items is not None and not items.empty:
        for _, r in items.iterrows():
            st = str(r.get("Status") or "")
            if st == "To procure":      # the exception report now carries ETO's Items to Procure too;
                continue                # they come from Lines to Order above, so skip them here
            stage = "Requisition (draft PO)" if st == "Draft" else ("Received" if st == "Received" else "On order")
            row = {"Stage": stage, "Status": st}   # Status left Peter's layout (29 Oct) but the overdue count needs it
            for k, *_ in cols_exc:
                v = r.get(k)
                row[k] = None if (isinstance(v, float) and pd.isna(v)) else v
            row["OrderDate"] = podates.get(str(r.get("PO")), "")   # PO header PurchaseDate, by PO number
            # Released by / # Releases / Quantity Change come per line from the report (2026-11-04)
            if stage == "Requisition (draft PO)":
                row["PO"] = ""          # a draft is a requisition: its number shows under Purchasing Requisition #
            out.append(row)
    order = {s: i for i, s in enumerate(STAGES)}
    out.sort(key=lambda x: (str(x.get("ProjectID")), str(x.get("Code")), str(x.get("Item")), order.get(x["Stage"], 9)))
    return out


def write_workbook(path, omni, omni_cols, reports, info_lines):
    """Streams the workbook (openpyxl write-only mode) so an all-projects run of several hundred
    thousand rows fits in memory and writes in minutes, not hours. Same tabs, headers, number
    formats, filters and frozen header as before."""
    from openpyxl import Workbook
    from openpyxl.cell import WriteOnlyCell
    from openpyxl.styles import Font, PatternFill, Alignment
    from openpyxl.utils import get_column_letter
    from console_web import exporters
    head_fill = PatternFill("solid", fgColor="1F3864")
    head_font = Font(name="Arial", bold=True, color="FFFFFF", size=10)
    body_font = Font(name="Arial", size=10)
    aligns = {}
    widths = {"text": 20, "date": 12, "money": 14, "money2": 14, "num": 11, "int": 10, "id": 10}
    wb = Workbook(write_only=True)

    def table(name, cols, rows):
        # cols: list of (key, label, type, align)
        ws = wb.create_sheet(name[:31])
        for j, (k, lbl, typ, al) in enumerate(cols, 1):
            ws.column_dimensions[get_column_letter(j)].width = max(widths.get(typ, 12), min(len(lbl) + 3, 34))
        ws.freeze_panes = "B2"
        ws.auto_filter.ref = f"A1:{get_column_letter(len(cols))}{max(len(rows) + 1, 1)}"
        head = []
        for k, lbl, typ, al in cols:
            c = WriteOnlyCell(ws, value=lbl); c.fill = head_fill; c.font = head_font
            c.alignment = Alignment(horizontal=al, vertical="center"); head.append(c)
        ws.append(head)
        for row in rows:
            out = []
            for k, lbl, typ, al in cols:
                c = WriteOnlyCell(ws)
                exporters._put_cell(c, row.get(k), typ)
                c.font = body_font
                c.alignment = aligns.setdefault(al, Alignment(horizontal=al))
                out.append(c)
            ws.append(out)

    table("Omnibus", omni_cols, omni)
    for name, res in reports:
        fcols, frows = exporters._flatten(res)
        table(name, [(c.key, c.label, c.type, c.align) for c in fcols], frows)
    info = wb.create_sheet("Info")
    info.column_dimensions["A"].width = 34; info.column_dimensions["B"].width = 90
    for i, line in enumerate(info_lines, 1):
        a = WriteOnlyCell(info, value=line[0])
        a.font = Font(name="Arial", bold=(i == 1 or line[1] is not None), size=12 if i == 1 else 10)
        row = [a]
        if line[1] is not None:
            b = WriteOnlyCell(info, value=line[1]); b.font = body_font; row.append(b)
        info.append(row)
    wb.save(path)


def main():
    from console_web.queries import LiveQueryService
    from console_web import etospec
    all_mode = "--all" in sys.argv[1:]          # every project, all time, all statuses (2026-11-12)
    pids = None if all_mode else ([int(a) for a in sys.argv[1:] if a.isdigit()] or tracked_projects())
    t0 = time.perf_counter()
    print(f"make_procurement_omnibus — {time.strftime('%Y-%m-%d %H:%M')}  "
          + ("ALL projects, all time" if all_mode else f"{len(pids)} project(s)"))
    svc = LiveQueryService()
    run = lambda q, **kw: svc.run(q, pids or [], all_projects=all_mode, **kw)
    lto = run("released_toorder")
    print(f"   Lines to Order          {time.perf_counter() - t0:7.1f}s")
    req = run("po_to_order")
    exc = run("po_exceptions")
    print(f"   PO Exceptions           {time.perf_counter() - t0:7.1f}s")
    lst = run("po_listing", active_only=False)   # same project set as the To procure lines
    print(f"   All Purchase Orders     {time.perf_counter() - t0:7.1f}s")
    items = (lst.export or {}).get("items")
    podates = po_order_dates(pids)
    relby = released_by(pids)
    omni = omnibus_rows(lto, items, etospec.COLS_EXC, podates, relby)
    omni_cols = [("Stage", "Stage", "text", "left")] + \
        [(k, l, t, a) for (k, l, t, a, w) in etospec.web_columns(etospec.COLS_EXC)]
    det = lambda res: sum(1 for x in res.rows if x.get("_kind") == "detail")
    counts = {s: sum(1 for x in omni if x["Stage"] == s) for s in STAGES}
    overdue = sum(1 for x in omni if str(x.get("Status") or "").startswith("Overdue"))
    cost = sum(num(x.get("Cost")) or 0 for x in omni)
    print(f"   built in {time.perf_counter() - t0:.1f}s")
    for s in STAGES:
        print(f"   {s:24} {counts[s]:>7,}")
    print(f"   overdue (on order)       {overdue:>7,}")
    print(f"   check: To procure {counts['To procure']:,} = Lines to Order {det(lto):,}; "
          f"PO stages {sum(counts[s] for s in STAGES[1:]):,} = Exception Report PO lines "
          f"{0 if items is None else int((items['Status'].astype(str) != 'To procure').sum()):,}")
    today = _dt.date.today()
    info = [("Procurement Omnibus", None),
            ("Generated", time.strftime("%Y-%m-%d %H:%M")),
            ("Source", "ETO production database (read-only), through the Sextant purchasing reports"),
            ("Scope", ("EVERY project in ETO, all time: no project list and no date window (--all)." if all_mode else
                       "The tracked projects at run time (the same set the project selector shows). "
                       "Override by naming project numbers on the command line, or --all for every project.")),
            ("Projects", "All" if all_mode else ", ".join(str(p) for p in pids)),
            ("", None)] + [(f"{s} (lines)", f"{counts[s]:,}") for s in STAGES] + [
            ("Overdue (on order)", f"{overdue:,}"),
            ("PO value, CAD (Cost column total)", f"${cost:,.2f}"),
            ("", None),
            ("Stage", "To procure = ETO's Items to Procure: released or requested, no PO yet; Status shows the quantity still to order. "
                      "Requisition (draft PO) = PO raised in ETO but not yet printed or emailed. On order = PO sent, not fully "
                      "received. Received = fully received."),
            ("Purchasing Requisition #", "The PO number as raised in ETO. A draft PO is the requisition; ETO keeps the same number once the PO is sent."),
            ("PO #", "Shown once the PO has been printed or emailed."),
            ("Order Date", "The PO header PurchaseDate — when the PO was placed (for a draft, the date it was raised in ETO). Blank on 'To procure' lines (no PO yet)."),
            ("Cost", "PO line total in CAD. Blank until a PO exists."),
            ("First / Latest Release Date", "The earliest and latest release (or Non-BOM request) behind the line. Each machine's released "
                                            "quantity is shared out to its PO lines oldest PO first."),
            ("Released by, Quantity Change", "Who made the latest release behind the line, and its quantity."),
            ("Total Released", "All release / request quantity covering the line."),
            ("# Releases", "How many release-log entries the part has on the project."),
            ("Still to Order", "To-procure lines only: ETO's Required quantity (negative = a return)."),
            ("Potential Over Order", "PO quantity no release or Non-BOM request covers."),
            ("Mfg Begins", "The machine's Mfg Begin date in ETO, where entered."),
            ("Lead Time", "ETO estimated lead time in days; on overdue PO lines, the part's average historical order-to-receipt days where no estimate exists."),
            ("Planned Ship, Permit Dates", "Blank: rules to be set."),
            ("Oversized, Inspected, Critical, LLT", "Item flags from the ETO item master."),
            ("Left out", "Freight, courier, cartage and brokerage lines; cancelled POs."),
            ("Other tabs", "Lines to Order, Purchase Requisitions, PO Exceptions and All Purchase Orders, as run at the same moment.")]
    path = f"Procurement_Omnibus_{'ALL_' if all_mode else ''}{today:%Y%m%d}.xlsx"
    write_workbook(path, omni, omni_cols,
                   [("Lines to Order", lto), ("Purchase Requisitions", req), ("PO Exceptions", exc), ("All Purchase Orders", lst)],
                   info)
    print(f"   wrote {path} in {time.perf_counter() - t0:.1f}s total")
    print("\nDONE — paste everything above.")


if __name__ == "__main__":
    main()
