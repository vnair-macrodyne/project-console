"""
console_diag_lines_to_order.py — what SHOULD "Lines to Order" contain, and why do some PO lines
carry no Release Date?  READ-ONLY.  Nothing is written.  (2026-10-09)

Vijay's expected flow per project: engineering RELEASES a part → a requisition is raised because it
NEEDS ORDERING → RFQ → PO → fulfilment → closure. So (a) every PO line should trace back to a release,
and (b) Lines to Order should list only lines that actually need to be ordered, not every released part.

Today, Lines to Order (etospec.query_released_to_order) = items in tblBOMReleaseHistory with net released
qty > 0, still on the current BOM (vwEngBOM), and NO PO line for that (ProjectID, ItemID). It has no
make/buy test, no stock test, is existence-based (a partial PO hides the item) and project-level (a PO
on one machine hides the same item released on another). This probe measures each of those, plus the
missing-release question, against live data before anything is changed.

SECTIONS
  A. PO lines with NO release date (all active POs, whole database)
     A0  release-log coverage window (when does tblBOMReleaseHistory start?)
     A1  every active PO line bucketed: no ItemID / release log / eng date only (PartCustom6) / NONE
     A2  buckets by PO year (is "no release" historical, i.e. before the log existed?)
     A3  the NO-RELEASE lines profiled: project present? item on this project's BOM? on any BOM?
         released on a DIFFERENT project? does the project have any release log at all? freight-like?
     A4  NO-RELEASE top categories, and 25 most recent sample lines
  B. Lines to Order today, for the chosen projects
     B1  run the exact current query; rows per project
     B2  make/buy discovery: item-master + vwEngBOM columns that could mark made vs bought, their
         captions, and their value spread across the Lines to Order items
     B3  assemblies / project-made parts among Lines to Order rows (structure parent; project-prefix naming)
     B4  stock: Lines to Order items with on-hand (vwInventory) or an unfulfilled pull on the project
         (vwInventoryUnfulfilledPulls = design demand allocated to stock)
     B5  lines the CURRENT rule hides: partially ordered items, and machine-level gaps
     B6  age since release of Lines to Order rows
  C. ETO's own "to be procured" (readiness proc OutstandingQty, as used by BOM Readiness) vs Lines to
     Order, for the busiest machine of the first project — agreement cross-tab, samples, proc timing,
     and a search for a set-based source of OutstandingQty.

RUN where the other console_diag_*.py run (ETO reachable), from the repo root:
    python console_diag_lines_to_order.py                 # auto-picks the 3 most release-active projects
    python console_diag_lines_to_order.py 250250 260101   # or name the projects
Paste the WHOLE output back. Section A scans every active PO line and can take a minute or two.
"""
import sys, os, re, time

ARG_PIDS = [int(a) for a in sys.argv[1:] if a.strip().isdigit()]
QUERY_TIMEOUT = 300           # seconds per statement
PROC_TIMEOUT = 120            # seconds per readiness-proc call
READINESS_PROC = "urpEngStructuredReadinessBySpec"   # same proc + params as queries._bom_readiness_sql


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
    print("\n" + "=" * 96 + f"\n{t}\n" + "=" * 96, flush=True)


def sub(t):
    print(f"\n--- {t}", flush=True)


ETO = None


def df(sql):
    import pandas as pd
    cur = ETO.cursor()
    cur.execute(sql)
    while cur.description is None:            # skip rowcount-only sets (SET NOCOUNT off etc.)
        if not cur.nextset():
            return pd.DataFrame()
    cols = [d[0] for d in cur.description]
    return pd.DataFrame([tuple(r) for r in cur.fetchall()], columns=cols)


def safe(label, fn):
    try:
        return fn()
    except Exception as e:
        print(f"   !! {label} failed — {type(e).__name__}: {e}", flush=True)
        return None


def show(frame, max_rows=40):
    import pandas as pd
    if frame is None:
        return
    if frame.empty:
        print("   (no rows)")
        return
    with pd.option_context("display.max_rows", max_rows, "display.max_columns", 30,
                           "display.width", 220, "display.max_colwidth", 48):
        print(frame.head(max_rows).to_string(index=False))
    if len(frame) > max_rows:
        print(f"   … {len(frame) - max_rows} more row(s)")


def chunks(seq, n=900):
    seq = list(seq)
    for i in range(0, len(seq), n):
        yield seq[i:i + n]


def ids_sql(vals):
    return ",".join(str(int(v)) for v in vals)


def pct(n, d):
    return f"{(100.0 * n / d):.1f}%" if d else "-"


# eng release date as a real date (NULL / unparsable / '' → NULL, so an empty string never counts as a date)
ENG_DATE = "NULLIF(TRY_CAST(eim.[PartCustom6] AS date), '19000101')"   # works for date or text storage; '' casts to 1900-01-01
FREIGHT = ("(LOWER(ISNULL(pod.ItemDescription,'')) LIKE '%freight%' OR LOWER(ISNULL(pod.ItemDescription,'')) LIKE '%courier%' "
           "OR LOWER(ISNULL(pod.ItemDescription,'')) LIKE '%cartage%' OR LOWER(ISNULL(pod.ItemDescription,'')) LIKE '%brokerage%')")

# One row per ACTIVE PO line (same population as All Purchase Orders: PurchaseActive = 1, all statuses)
PO_LINES = f"""
SELECT pod.PurchaseOrderID AS PO, pod.ProjectID, pod.SpecID, pod.ItemID,
       pod.ItemCompanyID AS ItemNo, pod.ItemDescription AS Descr,
       pdd.ItemMasterCategoryDescription AS Category,
       CAST(poh.PurchaseDate AS date) AS PODate, YEAR(poh.PurchaseDate) AS POYear,
       CASE WHEN poh.PurchasePrinted = 0 AND poh.PurchaseEmailed = 0 THEN 1 ELSE 0 END AS IsDraft,
       CASE WHEN pod.ItemID IS NULL                 THEN '1 no ItemID (free-text line)'
            WHEN rl.ItemID IS NOT NULL              THEN '2 release log'
            WHEN {ENG_DATE} IS NOT NULL             THEN '3 eng date only (PartCustom6)'
            ELSE                                         '4 NO RELEASE DATE' END AS Bucket,
       CASE WHEN p.ProjectID IS NULL THEN 0 ELSE 1 END AS ProjExists,
       CASE WHEN rp.ProjectID IS NULL THEN 0 ELSE 1 END AS ProjHasReleaseLog,
       CASE WHEN pb.ItemID IS NULL THEN 0 ELSE 1 END AS OnThisProjBOM,
       CASE WHEN ab.ItemID IS NULL THEN 0 ELSE 1 END AS OnAnyBOM,
       CASE WHEN ri.ItemID IS NULL THEN 0 ELSE 1 END AS ReleasedOnAnyProject,
       CASE WHEN {FREIGHT} THEN 1 ELSE 0 END AS FreightLike
FROM dbo.vwPurchaseOrderHeader poh
JOIN dbo.vwPurchaseOrderDetails pod ON pod.PurchaseOrderID = poh.PurchaseOrderID
LEFT JOIN dbo.vwPurchaseOrderDetailsDetailed pdd ON pdd.PurchaseDetailID = pod.PurchaseDetailID
LEFT JOIN dbo.tblEngItemMaster eim ON eim.ItemID = pod.ItemID
LEFT JOIN dbo.tblProjects p ON p.ProjectID = pod.ProjectID
LEFT JOIN (SELECT DISTINCT ProjectID, ItemID FROM dbo.tblBOMReleaseHistory) rl
       ON rl.ProjectID = pod.ProjectID AND rl.ItemID = pod.ItemID
LEFT JOIN (SELECT DISTINCT ProjectID FROM dbo.tblBOMReleaseHistory) rp ON rp.ProjectID = pod.ProjectID
LEFT JOIN (SELECT DISTINCT ItemID FROM dbo.tblBOMReleaseHistory) ri ON ri.ItemID = pod.ItemID
LEFT JOIN (SELECT DISTINCT ProjectID, ItemID FROM dbo.vwEngBOM) pb
       ON pb.ProjectID = pod.ProjectID AND pb.ItemID = pod.ItemID
LEFT JOIN (SELECT DISTINCT ItemID FROM dbo.vwEngBOM) ab ON ab.ItemID = pod.ItemID
WHERE poh.PurchaseActive = 1
"""


# ════════════════════════════════════════════════════════════════════════════════════════════════
def section_a():
    rule("A. PO LINES WITH NO RELEASE DATE — all active POs (PurchaseActive = 1), every status")

    sub("A0. Release log (dbo.tblBOMReleaseHistory) coverage window")
    show(safe("A0", lambda: df(
        "SELECT COUNT_BIG(*) AS LogRows, COUNT(DISTINCT ProjectID) AS Projects, "
        "MIN(ReleasedDateTime) AS FirstRelease, MAX(ReleasedDateTime) AS LastRelease "
        "FROM dbo.tblBOMReleaseHistory")))
    show(safe("A0 by year", lambda: df(
        "SELECT YEAR(ReleasedDateTime) AS Yr, COUNT_BIG(*) AS LogRows, COUNT(DISTINCT ProjectID) AS Projects "
        "FROM dbo.tblBOMReleaseHistory GROUP BY YEAR(ReleasedDateTime) ORDER BY Yr")))
    show(safe("A0 PartCustom6 storage", lambda: df(
        "SELECT DATA_TYPE FROM INFORMATION_SCHEMA.COLUMNS WHERE TABLE_NAME='tblEngItemMaster' AND COLUMN_NAME='PartCustom6'")))
    show(safe("A0 PartCustom6 population on items that appear on POs", lambda: df(
        "SELECT SUM(CASE WHEN eim.PartCustom6 IS NULL THEN 1 ELSE 0 END) AS NullValue, "
        "SUM(CASE WHEN eim.PartCustom6 IS NOT NULL AND TRY_CAST(eim.PartCustom6 AS date) = '19000101' THEN 1 ELSE 0 END) AS BlankOr1900, "
        "SUM(CASE WHEN eim.PartCustom6 IS NOT NULL AND TRY_CAST(eim.PartCustom6 AS date) IS NULL THEN 1 ELSE 0 END) AS NotADate, "
        "SUM(CASE WHEN TRY_CAST(eim.PartCustom6 AS date) > '19000101' THEN 1 ELSE 0 END) AS ValidDate "
        "FROM dbo.tblEngItemMaster eim WHERE eim.ItemID IN (SELECT DISTINCT ItemID FROM dbo.vwPurchaseOrderDetails)")))
    show(safe("A0 Type values", lambda: df(
        "SELECT CAST([Type] AS nvarchar(100)) AS [Type], COUNT_BIG(*) AS N FROM dbo.tblBOMReleaseHistory "
        "GROUP BY CAST([Type] AS nvarchar(100)) ORDER BY N DESC")))

    t0 = time.time()
    lines = safe("A1 base scan", lambda: df(PO_LINES))
    if lines is None or lines.empty:
        print("   (no PO lines returned — section A stops here)")
        return
    print(f"\n   scanned {len(lines):,} active PO lines in {time.time() - t0:.1f}s")

    sub("A1. Every active PO line, by where its Release Date would come from")
    tot = len(lines)
    b = lines.groupby("Bucket").size().rename("Lines").reset_index()
    b["Share"] = [pct(n, tot) for n in b["Lines"]]
    show(b)

    sub("A2. Buckets by PO year (columns = bucket)")
    show(lines.pivot_table(index="POYear", columns="Bucket", values="PO", aggfunc="count", fill_value=0)
         .reset_index(), 60)

    nr = lines[lines["Bucket"] == "4 NO RELEASE DATE"]
    eo = lines[lines["Bucket"] == "3 eng date only (PartCustom6)"]
    sub(f"A3. Profile of the {len(nr):,} NO-RELEASE lines (and, for contrast, the {len(eo):,} eng-date-only lines)")
    for name, part in (("NO RELEASE DATE", nr), ("eng date only", eo)):
        n = len(part)
        if not n:
            continue
        print(f"\n   [{name}]  {n:,} line(s)")
        for col, label in (("ProjExists", "project exists in tblProjects"),
                           ("ProjHasReleaseLog", "project has ANY release-log rows"),
                           ("OnThisProjBOM", "item is on THIS project's current BOM"),
                           ("OnAnyBOM", "item is on ANY project's BOM"),
                           ("ReleasedOnAnyProject", "item was released on SOME project (log)"),
                           ("FreightLike", "freight/courier/cartage/brokerage text (report hides these)"),
                           ("IsDraft", "PO is a draft (not printed, not emailed)")):
            k = int(part[col].sum())
            print(f"     {label:62} {k:>8,}  ({pct(k, n)})")
        combo = (part.groupby(["ProjHasReleaseLog", "OnThisProjBOM", "OnAnyBOM", "ReleasedOnAnyProject"])
                 .size().rename("Lines").reset_index().sort_values("Lines", ascending=False))
        print("     combinations (1 = yes):")
        show(combo)
        recent = part[part["POYear"] >= (part["POYear"].max() - 1)] if part["POYear"].notna().any() else part
        print(f"     of which on POs dated in the last two calendar years: {len(recent):,}")

    sub("A4. NO-RELEASE lines — top categories (all years / last two calendar years)")
    if not nr.empty:
        cats = nr.groupby(nr["Category"].fillna("(none)")).size().rename("AllYears")
        maxy = nr["POYear"].max()
        rec = nr[nr["POYear"] >= maxy - 1]
        cats = cats.to_frame().join(rec.groupby(rec["Category"].fillna("(none)")).size().rename("Last2Yrs"),
                                    how="left").fillna(0).astype(int)
        show(cats.sort_values("AllYears", ascending=False).reset_index().rename(columns={"index": "Category"}), 25)
        print("\n   25 most recent NO-RELEASE lines:")
        show(nr.sort_values("PODate", ascending=False)[
            ["PODate", "PO", "ProjectID", "SpecID", "ItemNo", "Descr", "Category", "IsDraft",
             "OnThisProjBOM", "OnAnyBOM", "ReleasedOnAnyProject", "ProjHasReleaseLog"]].head(25), 25)


# ════════════════════════════════════════════════════════════════════════════════════════════════
def pick_projects():
    if ARG_PIDS:
        return ARG_PIDS
    top = safe("project pick", lambda: df(
        "SELECT TOP 3 h.ProjectID, COUNT_BIG(*) AS ReleaseRows180d FROM dbo.tblBOMReleaseHistory h "
        "JOIN dbo.tblProjects p ON p.ProjectID = h.ProjectID "
        "WHERE h.ReleasedDateTime >= DATEADD(day, -180, GETDATE()) "
        "GROUP BY h.ProjectID ORDER BY COUNT_BIG(*) DESC"))
    if top is None or top.empty:
        return []
    print("   auto-picked the 3 projects with the most release-log rows in the last 180 days:")
    show(top)
    return [int(x) for x in top["ProjectID"]]


def columns_of(obj):
    return safe(f"columns of {obj}", lambda: df(
        f"SELECT COLUMN_NAME, DATA_TYPE FROM INFORMATION_SCHEMA.COLUMNS WHERE TABLE_NAME = '{obj}' "
        f"ORDER BY ORDINAL_POSITION"))


CAND = re.compile(r"make|buy|purch|manuf|fab|source|stock|inv|type|categ|class|uom|phantom|kit|procure|"
                  r"supply|vendor|supplier|outside|inhouse|in_house|machined|bought", re.I)


def section_b(et, pids):
    import pandas as pd
    rule(f"B. LINES TO ORDER TODAY — projects {pids}")
    if not pids:
        print("   (no projects — pass project IDs on the command line)")
        return None

    sub("B1. Current Lines to Order query (etospec.query_released_to_order), exactly as the report runs it")
    t0 = time.time()
    l2o = safe("B1", lambda: df(et.query_released_to_order(pids)))
    if l2o is None:
        return None
    print(f"   {len(l2o):,} row(s) in {time.time() - t0:.1f}s")
    if l2o.empty:
        return l2o
    show(l2o.groupby("ProjectID").size().rename("Rows").reset_index())
    item_ids = sorted({int(i) for i in l2o["ItemID"].dropna()})

    sub("B2a. tblEngItemMaster columns that could mark MADE vs BOUGHT (name match) + all Part captions")
    im_cols = columns_of("tblEngItemMaster")
    cand_im = []
    if im_cols is not None and not im_cols.empty:
        cand_im = [c for c in im_cols["COLUMN_NAME"] if CAND.search(c) and not c.lower().startswith("partcustom")]
        show(im_cols[im_cols["COLUMN_NAME"].isin(cand_im)], 60)
        print(f"   ({len(im_cols)} columns in total on tblEngItemMaster)")
    caps = safe("captions", lambda: df(
        "SELECT FieldName, Object, Caption FROM dbo.tlkpCaption WHERE Object LIKE 'Part%' ORDER BY FieldName"))
    if caps is not None:
        print("   tlkpCaption 'Part' captions (custom-field meanings):")
        show(caps, 80)
        cand_im += [str(r.FieldName) for r in caps.itertuples()
                    if str(r.FieldName).lower().startswith("partcustom") and r.Caption
                    and CAND.search(str(r.Caption)) and im_cols is not None
                    and str(r.FieldName) in set(im_cols["COLUMN_NAME"])]

    sub("B2b. Value spread of those columns across the Lines to Order items (top values per column)")
    if cand_im and item_ids:
        frames = []
        sel = ", ".join(f"CAST([{c}] AS nvarchar(200)) AS [{c}]" for c in cand_im)
        for ch in chunks(item_ids):
            f = safe("B2b chunk", lambda: df(f"SELECT ItemID, {sel} FROM dbo.tblEngItemMaster WHERE ItemID IN ({ids_sql(ch)})"))
            if f is not None:
                frames.append(f)
        im = pd.concat(frames) if frames else pd.DataFrame()
        for c in cand_im:
            if c in im.columns:
                vc = im[c].fillna("(NULL)").value_counts()
                print(f"   {c}: {vc.size} distinct — " +
                      "; ".join(f"{k!s}={v}" for k, v in vc.head(10).items()))

    sub("B2c. vwEngBOM — full column list, then candidate columns' spread across Lines to Order rows")
    bom_cols = columns_of("vwEngBOM")
    if bom_cols is not None and not bom_cols.empty:
        print("   " + ", ".join(f"{r.COLUMN_NAME}({r.DATA_TYPE})" for r in bom_cols.itertuples()))
        cand_b = [c for c in bom_cols["COLUMN_NAME"] if CAND.search(c)]
        if cand_b and item_ids:
            sel = ", ".join(f"CAST([{c}] AS nvarchar(200)) AS [{c}]" for c in cand_b)
            frames = []
            for ch in chunks(item_ids):
                f = safe("B2c chunk", lambda: df(
                    f"SELECT ProjectID, ItemID, {sel} FROM dbo.vwEngBOM "
                    f"WHERE ProjectID IN ({ids_sql(pids)}) AND ItemID IN ({ids_sql(ch)})"))
                if f is not None:
                    frames.append(f)
            bm = pd.concat(frames) if frames else pd.DataFrame()
            for c in cand_b:
                if c in bm.columns:
                    vc = bm[c].fillna("(NULL)").value_counts()
                    print(f"   {c}: {vc.size} distinct — " +
                          "; ".join(f"{k!s}={v}" for k, v in vc.head(10).items()))

    sub("B3. Assemblies / project-made parts among Lines to Order rows")
    ps_cols = columns_of("vwEngProductStructure")
    if ps_cols is not None and not ps_cols.empty:
        print("   vwEngProductStructure columns: " + ", ".join(ps_cols["COLUMN_NAME"]))
    smp = safe("B3 sample", lambda: df(
        f"SELECT TOP 3 * FROM dbo.vwEngProductStructure WHERE ProjectID = {int(pids[0])}"))
    show(smp)
    par = safe("B3 parents", lambda: df(
        f"SELECT DISTINCT ProjectID, ParentID FROM dbo.vwEngProductStructure WHERE ProjectID IN ({ids_sql(pids)})"))
    if par is not None and not par.empty:
        pset = {(int(a), int(b)) for a, b in par[["ProjectID", "ParentID"]].dropna().itertuples(index=False)}
        hit = sum((int(p), int(i)) in pset for p, i in l2o[["ProjectID", "ItemID"]].dropna().itertuples(index=False))
        print(f"   Lines to Order rows whose ItemID is a PARENT in the project structure (has children → "
              f"an assembly, built not bought) — valid only if ParentID is an ItemID, check the sample above: "
              f"{hit:,} of {len(l2o):,}")
    pref = sum(str(n or "").startswith(str(int(p))) for p, n in l2o[["ProjectID", "ItemNo"]].itertuples(index=False))
    print(f"   rows whose part number starts with the project number (suspected project-made naming, "
          f"e.g. 220154-10M0 — unconfirmed convention): {pref:,} of {len(l2o):,}")

    sub("B4. Stock: Lines to Order items with on-hand, or an unfulfilled stock pull on the project")
    frames = []
    for ch in chunks(item_ids):
        f = safe("B4 onhand", lambda: df(
            f"SELECT ItemID, SUM(CAST(QtyOnHand AS float)) AS OnHand FROM dbo.vwInventory "
            f"WHERE ItemID IN ({ids_sql(ch)}) GROUP BY ItemID"))
        if f is not None:
            frames.append(f)
    oh = pd.concat(frames) if frames else pd.DataFrame(columns=["ItemID", "OnHand"])
    m = l2o.merge(oh, on="ItemID", how="left")
    m["OnHand"] = m["OnHand"].fillna(0.0)
    covered = m[m["OnHand"] >= m["Qty"].astype(float)]
    some = m[(m["OnHand"] > 0) & (m["OnHand"] < m["Qty"].astype(float))]
    print(f"   on-hand ≥ released qty (could be pulled from stock): {len(covered):,} of {len(m):,}")
    print(f"   some on-hand but less than released qty            : {len(some):,}")
    up = safe("B4 pulls", lambda: df(
        f"SELECT ProjectID, ItemCompanyID AS ItemNo, SUM(CAST(PullQty AS float)) AS PullQty "
        f"FROM dbo.vwInventoryUnfulfilledPulls WHERE ProjectID IN ({ids_sql(pids)}) "
        f"GROUP BY ProjectID, ItemCompanyID"))
    if up is not None:
        up["ProjectID"] = up["ProjectID"].astype(int)
        mp = l2o.assign(ProjectID=l2o["ProjectID"].astype(int)).merge(up, on=["ProjectID", "ItemNo"], how="inner")
        print(f"   rows with an UNFULFILLED STOCK PULL on the same project (demand allocated to stock): {len(mp):,}")
        show(mp[["ProjectID", "ItemNo", "Description", "Qty", "PullQty"]].head(15), 15)
    if not covered.empty:
        print("   sample — on-hand covers the released qty:")
        show(covered[["ProjectID", "ItemNo", "Description", "Qty", "OnHand"]].head(15), 15)

    sub("B5. Lines the CURRENT rule hides (existence- and project-level PO test)")
    rel = safe("B5 rel", lambda: df(
        f"SELECT ProjectID, CAST(SpecID AS float) AS SpecID, ItemID, SUM(CAST(QuantityChange AS float)) AS RelQty "
        f"FROM dbo.tblBOMReleaseHistory WHERE ProjectID IN ({ids_sql(pids)}) "
        f"GROUP BY ProjectID, CAST(SpecID AS float), ItemID HAVING SUM(CAST(QuantityChange AS float)) > 0"))
    po = safe("B5 po", lambda: df(
        f"SELECT pod.ProjectID, CAST(pod.SpecID AS float) AS SpecID, pod.ItemID, "
        f"SUM(CAST(pod.PurchaseQty AS float)) AS POQty "
        f"FROM dbo.vwPurchaseOrderDetails pod JOIN dbo.vwPurchaseOrderHeader poh ON poh.PurchaseOrderID = pod.PurchaseOrderID "
        f"WHERE poh.PurchaseActive = 1 AND pod.ProjectID IN ({ids_sql(pids)}) AND pod.ItemID IS NOT NULL "
        f"GROUP BY pod.ProjectID, CAST(pod.SpecID AS float), pod.ItemID"))
    cb = safe("B5 curbom", lambda: df(
        f"SELECT DISTINCT ProjectID, ItemID FROM dbo.vwEngBOM WHERE ProjectID IN ({ids_sql(pids)})"))
    if rel is not None and po is not None and cb is not None:
        cbs = {(int(a), int(b)) for a, b in cb.dropna().itertuples(index=False)}
        rel = rel[[(int(p), int(i)) in cbs for p, i in rel[["ProjectID", "ItemID"]].itertuples(index=False)]]
        # item level (what the current rule sees)
        ri = rel.groupby(["ProjectID", "ItemID"], as_index=False)["RelQty"].sum()
        pi = po.groupby(["ProjectID", "ItemID"], as_index=False)["POQty"].sum()
        j = ri.merge(pi, on=["ProjectID", "ItemID"], how="left")
        partial = j[j["POQty"].notna() & (j["POQty"] < j["RelQty"])]
        print(f"   released items on the current BOM: {len(j):,}; with NO PO (= today's list): "
              f"{int(j['POQty'].isna().sum()):,}")
        print(f"   PARTIALLY ordered (PO qty < released qty) — hidden today: {len(partial):,}")
        show(partial.assign(Short=partial["RelQty"] - partial["POQty"]).head(15), 15)
        # machine level
        js = rel.merge(po, on=["ProjectID", "SpecID", "ItemID"], how="left")
        nospec = js[js["POQty"].isna()]
        pis = {(int(a), int(b)) for a, b in pi[["ProjectID", "ItemID"]].itertuples(index=False)}
        hidden = nospec[[(int(p), int(i)) in pis for p, i in nospec[["ProjectID", "ItemID"]].itertuples(index=False)]]
        print(f"   releases with NO PO on THAT machine but a PO for the item on ANOTHER machine — hidden today: {len(hidden):,}")
        show(hidden.head(15), 15)
        shortspec = js[js["POQty"].notna() & (js["POQty"] < js["RelQty"])]
        print(f"   machine-level PARTIALS (PO qty on that machine < released qty on that machine): {len(shortspec):,}")

    sub("B6. Age since release of today's Lines to Order rows")
    rd = pd.to_datetime(l2o["ReleaseDate"], errors="coerce")
    age = (pd.Timestamp.today().normalize() - rd).dt.days
    bins = [(-1, 30, "≤30d"), (30, 90, "31–90d"), (90, 180, "91–180d"), (180, 365, "181–365d"), (365, 10 ** 6, ">1yr")]
    for lo, hi, lab in bins:
        print(f"   {lab:9} {int(((age > lo) & (age <= hi)).sum()):>7,}")
    print(f"   no date  {int(age.isna().sum()):>7,}")
    return l2o


# ════════════════════════════════════════════════════════════════════════════════════════════════
def readiness_df(sql):
    import pandas as pd
    cur = ETO.cursor()
    cur.execute(sql)
    best = None
    while True:
        if cur.description is not None:
            cols = [d[0] for d in cur.description]
            rows = cur.fetchall()
            if rows and ("ItemCompanyID" in cols or "PercentageComplete_Absolute_Assy" in cols):
                return pd.DataFrame([tuple(r) for r in rows], columns=cols)
            if rows and best is None:
                best = pd.DataFrame([tuple(r) for r in rows], columns=cols)
        if not cur.nextset():
            break
    return best if best is not None else pd.DataFrame()


def section_c(l2o, pids):
    import pandas as pd
    rule("C. ETO's OWN 'TO BE PROCURED' (readiness proc OutstandingQty) vs LINES TO ORDER")
    if l2o is None or l2o.empty or not pids:
        print("   (no Lines to Order rows to compare)")
        return
    pid = int(pids[0])
    mine = l2o[l2o["ProjectID"].astype(int) == pid]
    if mine.empty:
        print(f"   project {pid} has no Lines to Order rows — nothing to compare")
        return
    spec = float(mine["MachineCode"].value_counts().idxmax())
    print(f"   project {pid}, machine {spec:g} (the machine with the most Lines to Order rows: "
          f"{int((mine['MachineCode'].astype(float) == spec).sum())})")

    scopes = safe("scopes", lambda: df(
        f"WITH roots AS (SELECT DISTINCT ParentID FROM dbo.vwEngProductStructure "
        f"  WHERE ProjectID={pid} AND SpecID={spec} AND ParentID NOT IN "
        f"  (SELECT ChildID FROM dbo.vwEngProductStructure WHERE ProjectID={pid} AND SpecID={spec})) "
        f"SELECT s.StructureID, s.ItemCompanyID, s.ItemDescription "
        f"FROM dbo.vwEngProductStructure s JOIN roots r ON s.ParentID = r.ParentID "
        f"WHERE s.ProjectID={pid} AND s.SpecID={spec} ORDER BY s.ItemCompanyID, s.StructureID"))
    if scopes is None or scopes.empty:
        print("   (no scope assemblies found for that machine)")
        return
    print(f"   {len(scopes)} scope assembl(ies) — running the proc once per scope (timed):")
    try:
        ETO.timeout = PROC_TIMEOUT
    except Exception:
        pass
    frames, t_all = [], time.time()
    for asm in scopes["StructureID"].tolist():
        t0 = time.time()
        one = safe(f"proc scope {asm}", lambda: readiness_df(
            "SET NOCOUNT ON; "
            f"EXEC dbo.{READINESS_PROC} "
            f"@intProjectID={pid}, @decSpecID={spec}, @intAssemblyStructureID={int(asm)}, "
            f"@bitExplodeStandardAssemblies=1, @intWeightMethod=0, @bitAssembliesOnly=0, "
            f"@bitHideFullyAvailable=0, @intNumberOfLevels=99, @intIndentSpaces=3, "
            f"@bitAverageWithBOMQty=0"))
        n = 0 if one is None else len(one)
        print(f"     scope {asm}: {n:,} rows, {time.time() - t0:.1f}s", flush=True)
        if one is not None and not one.empty:
            frames.append(one)
    try:
        ETO.timeout = QUERY_TIMEOUT
    except Exception:
        pass
    print(f"   total proc time for this one machine: {time.time() - t_all:.1f}s")
    if not frames:
        return
    rd = pd.concat(frames, ignore_index=True)
    print("   proc columns: " + ", ".join(rd.columns))
    if "Depth" in rd.columns:
        rd = rd[pd.to_numeric(rd["Depth"], errors="coerce").fillna(0) > 0]
    for c in ("OutstandingQty", "TotalRequiredForEntireAssy", "TotalAvailable", "PurchaseQty"):
        if c in rd.columns:
            rd[c] = pd.to_numeric(rd[c], errors="coerce")
    uom = "UOMType" if "UOMType" in rd.columns else None
    agg = {c: "max" for c in ("OutstandingQty", "TotalRequiredForEntireAssy", "TotalAvailable", "PurchaseQty") if c in rd.columns}
    if uom:
        agg[uom] = "first"
    per = rd.groupby("ItemCompanyID", as_index=False).agg(agg)
    if uom:
        sub("C1. UOMType spread in the proc output (all lines / lines with OutstandingQty > 0)")
        print("   all : " + "; ".join(f"{k}={v}" for k, v in per[uom].fillna("(NULL)").value_counts().items()))
        pos = per[per["OutstandingQty"] > 0]
        print("   >0  : " + "; ".join(f"{k}={v}" for k, v in pos[uom].fillna("(NULL)").value_counts().items()))

    sub("C2. Agreement: Lines to Order (this machine) vs ETO OutstandingQty > 0  (matched on part number)")
    lm = mine[mine["MachineCode"].astype(float) == spec]
    l_set = set(str(x).strip() for x in lm["ItemNo"].dropna())
    o_set = set(str(x).strip() for x in per.loc[per["OutstandingQty"] > 0, "ItemCompanyID"].dropna())
    all_set = set(str(x).strip() for x in per["ItemCompanyID"].dropna())
    both = l_set & o_set
    l_only = l_set - o_set
    o_only = o_set - l_set
    print(f"   on Lines to Order AND ETO says still to procure : {len(both):,}")
    print(f"   on Lines to Order but ETO says NOT to procure   : {len(l_only):,}"
          f"   (of which not in the proc output at all: {len(l_only - all_set):,})")
    print(f"   ETO says to procure but NOT on Lines to Order   : {len(o_only):,}")
    cols = ["ItemCompanyID"] + [c for c in ("OutstandingQty", "TotalRequiredForEntireAssy", "TotalAvailable",
                                            "PurchaseQty", uom) if c]
    print("\n   sample — on Lines to Order but ETO says NOT to procure (why: available / on order / other):")
    show(per[per["ItemCompanyID"].astype(str).str.strip().isin(l_only)][cols].head(20), 20)
    print("\n   sample — ETO says to procure but NOT on Lines to Order:")
    show(per[per["ItemCompanyID"].astype(str).str.strip().isin(o_only)][cols].head(20), 20)

    sub("C3. Is there a set-based source for OutstandingQty? (objects named like readiness/outstanding/procure)")
    show(safe("C3 objects", lambda: df(
        "SELECT name, type_desc FROM sys.objects WHERE name LIKE '%Readiness%' OR name LIKE '%Outstanding%' "
        "OR name LIKE '%Procure%' OR name LIKE '%ToBeProc%' ORDER BY type_desc, name")), 60)
    d = safe("C3 proc definition", lambda: df(f"SELECT OBJECT_DEFINITION(OBJECT_ID('dbo.{READINESS_PROC}')) AS D"))
    if d is not None and not d.empty and d.iloc[0, 0]:
        text = str(d.iloc[0, 0])
        print(f"   proc definition: {len(text):,} chars. Lines mentioning Outstanding / FROM / JOIN / EXEC:")
        for ln in text.splitlines():
            s = ln.strip()
            if re.search(r"outstanding|\bfrom\b|\bjoin\b|\bexec\b", s, re.I) and len(s) < 220:
                print("     " + s)
    else:
        print("   (definition not readable with this account — VIEW DEFINITION may be denied)")


def main():
    global ETO
    et = import_etospec()
    ETO = eto_connect()
    try:
        ETO.timeout = QUERY_TIMEOUT
    except Exception:
        pass
    print(f"console_diag_lines_to_order — {time.strftime('%Y-%m-%d %H:%M')}  (read-only)")
    safe("section A", section_a)
    rule("Project selection for B and C")
    pids = pick_projects()
    l2o = safe("section B", lambda: section_b(et, pids))
    safe("section C", lambda: section_c(l2o, pids))
    ETO.close()
    print("\nDONE — paste everything above.")


if __name__ == "__main__":
    main()
