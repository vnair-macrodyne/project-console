"""
console_diag_exc_release_match.py — live check of the two fixes for Peter's 3 Nov 2026 email.  READ-ONLY.

Problem 1 (rule revised 2026-11-04: releases shared out to PO lines oldest PO first; uncovered qty = Potential Over Order; Returns included with negative Still to Order).
Problem 1 was: a part released more than once showed the same Release Date and the latest releaser on every PO
line (240148 / E00067: four lines, all 2026-07-20, all "Ariza, Juan"). Fix: each line is matched to ONE
release-log entry — same project + part, same machine where it has one, the latest release on or before
the PO date (earliest if the PO came first); To-procure lines take the latest release. Quantity Change =
that entry's quantity.
Problem 2: the Purchasing Exception Report showed no Items to Procure. Fix: ETO's own Items to Procure
(uspPurchasingItemsToPurchase, Action = Procure) are added as lines with no buyer / PO.

  A  240148 / E00067: every release-log entry, every PO line, and what the report now shows per line.
  B  240148: ETO's Items to Procure rows (ALL Action values) — compare with ETO's Procurement (Filtered)
     grid, which Peter says shows 3 items to procure.
  C  The report live for the given projects (default: 240148): timing, cards, the To-procure lines.
  D  Across all active projects: PO lines matched to a release, matched on their own machine, and
     lines whose part was released more than once on the project (the ones Problem 1 affected).

Run:  py console_diag_exc_release_match.py            (or name projects: ... 240148 250005)
Paste the whole output back.
"""
import sys, time, warnings
warnings.simplefilter("ignore", FutureWarning)

PIDS = [int(a) for a in sys.argv[1:] if a.isdigit()] or [240148]


def show(cur, label, sql, n=40):
    try:
        cur.execute(sql)
        while cur.description is None and cur.nextset():
            pass
        cols = [d[0] for d in cur.description]
        rows = cur.fetchall()
        print(f"\n   {label}  ({len(rows)} row(s))")
        print("     " + " | ".join(cols))
        for r in rows[:n]:
            print("     " + " | ".join("" if v is None else str(v) for v in r))
        return cols, rows
    except Exception as e:
        print(f"   !! {label}: {type(e).__name__}: {e}")
        return [], []


def main():
    from console.infra.connections import eto_connection
    from console_web.queries import LiveQueryService
    from console_web import etospec
    print(f"console_diag_exc_release_match — {time.strftime('%Y-%m-%d %H:%M')}  projects {PIDS}  (read-only)")
    cur = eto_connection().cursor()

    print("\n== A. 240148 / E00067")
    show(cur, "release log", """
        SELECT h.SpecID, h.[Type], h.QuantityChange, h.ReleasedDateTime,
               e.EmpLastName + ', ' + e.EmpFirstName AS ReleasedBy
        FROM dbo.tblBOMReleaseHistory h
        JOIN dbo.tblEngItemMaster m ON m.ItemID = h.ItemID
        LEFT JOIN dbo.tblEmployee e ON e.EmployeeID = h.ReleasedByEmployeeID
        WHERE h.ProjectID = 240148 AND m.ItemCompanyID = 'E00067'
        ORDER BY h.ReleasedDateTime""")
    show(cur, "PO lines", """
        SELECT pod.SpecID, poh.PurchaseOrderID, CAST(poh.PurchaseDate AS date) AS PODate, pod.PurchaseQty,
               pod.Received, poh.PurchaseActive, poh.PurchasePrinted, poh.PurchaseEmailed
        FROM dbo.vwPurchaseOrderDetails pod
        JOIN dbo.vwPurchaseOrderHeader poh ON poh.PurchaseOrderID = pod.PurchaseOrderID
        WHERE pod.ProjectID = 240148 AND pod.ItemCompanyID = 'E00067'
        ORDER BY poh.PurchaseDate, pod.SpecID""")

    print("\n== B. 240148: ETO Items to Procure (all Action values)")
    s = LiveQueryService()
    usp = s._readiness_df("SET NOCOUNT ON; EXEC dbo.uspPurchasingItemsToPurchase")
    u = usp[usp["ProjectID"] == 240148]
    print(f"   {len(u)} row(s); Action: " + ", ".join(f"{k} {v}" for k, v in u["Action"].astype(str).str.strip().value_counts().items()))
    for _, r in u.iterrows():
        print(f"     m{r.get('SpecID')} {r.get('ItemCompanyID')} | {str(r.get('ItemDescription'))[:30]} | "
              f"Requested {r.get('PurchaseQty')} Procured {r.get('Assigned')} Required {r.get('ToPurchase')} | Action {r.get('Action')}")

    print("\n== C. Purchasing Exception Report, live")
    t0 = time.perf_counter()
    r = s.run("po_listing", PIDS)
    r.to_dict()
    print(f"   built in {time.perf_counter() - t0:.1f}s")
    print("   cards: " + " · ".join(f"{c.label} {c.value}" for c in r.cards))
    det = [x for x in r.rows if x.get("_kind") == "detail"]
    tp = [x for x in det if not x.get("Buyer") and not x.get("ReqNo")]
    print(f"   To-procure lines: {len(tp)}")
    for x in tp[:15]:
        print(f"     {x.get('ProjectID')} m{x.get('Code')} {x.get('Item')} | rel {x.get('EngRelease')} by {x.get('ReleasedBy')} "
              f"qty {x.get('QtyChange')} | still to order {x.get('ToOrder')} | planned {x.get('PlannedReceipt')}")
    print("   E00067 lines:")
    for x in det:
        if x.get("Item") == "E00067":
            print(f"     m{x.get('Code')} PO {x.get('ReqNo')} ordered {x.get('PODate')} | rel {x.get('EngRelease')} "
                  f"by {x.get('ReleasedBy')} qty {x.get('QtyChange')} | # rel {x.get('RelCount')} | over order {x.get('OverOrder')}")
    ov = [x for x in det if x.get("OverOrder") is not None and x.get("OverOrder") == x.get("OverOrder")]   # skip NaN
    print(f"   Potential over-order lines: {len(ov)} (first 15)")
    for x in ov[:15]:
        print(f"     {x.get('ProjectID')} m{x.get('Code')} {x.get('Item')} PO {x.get('ReqNo')} ordered {x.get('PODate')} | "
              f"over {x.get('OverOrder')} | credited rel {x.get('EngRelease')} qty {x.get('QtyChange')}")

    print("\n== D. All active projects")
    act = sorted(s._active_ids() or [])
    if act:
        t0 = time.perf_counter()
        raw = s._df(etospec.query_po_exceptions(False, act, None, None, all_statuses=True))
        ev = s._df(etospec.query_release_events(act))
        alloc = etospec.allocate_line_releases(ev, s._df(etospec.query_po_line_keys(act)),
                                               s._df(etospec.query_nonbom_events(act)))
        m = etospec.apply_line_releases(raw, alloc, ev)
        print(f"   potential over order: {int(m['OverOrder'].notna().sum()):,} lines, "
              f"{m['OverOrder'].fillna(0).sum():,.0f} units; no release covers any of it: "
              f"{int((m['OverOrder'].notna() & m['QtyChange'].isna()).sum()):,} lines")
        pos = ev[(ev["QtyChange"] > 0) & ev["RelType"].astype(str).isin(["Prerelease", "Release"])]
        npos = pos.groupby(["ProjectID", "ItemID"]).size()
        onmach = set(zip(pos["ProjectID"], pos["ItemID"], pos["SpecKey"]))
        n = len(m)
        matched = int(m["QtyChange"].notna().sum())
        own = sum(1 for p, i, c in zip(m["ProjectID"], m["ItemID"], m["Code"]) if (p, i, float(c)) in onmach)
        multi = sum(1 for p, i in zip(m["ProjectID"], m["ItemID"]) if npos.get((p, i), 0) > 1)
        print(f"   {len(act)} active project(s), {n:,} PO lines, {time.perf_counter() - t0:.1f}s")
        print(f"   matched to a release {matched:,} · on the line's own machine {own:,} · "
              f"part released more than once on the project {multi:,}")
        print("\n== E. What sits behind the potential over orders (all active projects)")
        import pandas as pd
        o = m[m["OverOrder"].notna()].copy()
        nb = s._df(f"SELECT DISTINCT ProjectID, ItemID FROM dbo.vwPurchasingNonBOM WHERE ProjectID IN ({','.join(map(str, act))})")
        nbset = set(zip(nb["ProjectID"], nb["ItemID"])) if nb is not None and not nb.empty else set()
        o["HasNonBOM"] = [(p, i) in nbset for p, i in zip(o["ProjectID"], o["ItemID"])]
        o["OwnMachine"] = [(p, i, float(c)) in onmach for p, i, c in zip(o["ProjectID"], o["ItemID"], o["Code"])]
        relq = pos.groupby(["ProjectID", "ItemID"])["QtyChange"].sum().to_dict()
        poq = m.groupby(["ProjectID", "ItemID"])["Qty"].sum().to_dict()
        for lab, mask in (("part also has a Non-BOM request on the project", o["HasNonBOM"]),
                          ("no Non-BOM request, line on a machine with no release", ~o["HasNonBOM"] & ~o["OwnMachine"]),
                          ("no Non-BOM request, on a released machine", ~o["HasNonBOM"] & o["OwnMachine"])):
            print(f"   {lab}: {int(mask.sum()):,} lines, {o.loc[mask, 'OverOrder'].sum():,.0f} units")
        print("   largest 15 by units:")
        for _, x in o.sort_values("OverOrder", ascending=False).head(15).iterrows():
            k = (x["ProjectID"], x["ItemID"])
            print(f"     {x['ProjectID']} m{x['Code']} {x['Item']} PO {x['PO']} ordered {x['Ordered']} qty {x['Qty']} | over {x['OverOrder']:g} | "
                  f"project released {relq.get(k, 0):g} vs ordered {poq.get(k, 0):g} | NonBOM {x['HasNonBOM']} | {str(x['Category'])[:18]}")
    print("\nDONE — paste everything above.")


if __name__ == "__main__":
    main()
