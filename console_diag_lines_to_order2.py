"""
console_diag_lines_to_order2.py — Lines to Order, take 2.  READ-ONLY.  Nothing is written.  (2026-10-09)

Take 1 (console_diag_lines_to_order.py) established:
  * tblBOMReleaseHistory has THREE row types: Prerelease 141,636 / Release 49,055 / Unrelease 59. Every
    "Release Date" in the purchasing reports (and the Lines to Order list) uses MIN(ReleasedDateTime) and
    SUM(QuantityChange) across ALL types — so a Prerelease counts as a release, and if Prerelease and
    Release rows both carry quantity, released qty may be counted twice (would inflate the 155 "partials").
  * tblEngItemMaster has NO make/buy field (PartCustom6 'Date Released Engineering' is set on 1 item).
    vwEngProductStructure carries UOMType (AS = assembly) and CatergoryMajor ('Fabrications', 'Purchased'
    seen in the sample) — a possible make/buy signal, not yet profiled.
  * ETO's OutstandingQty is NOT "still to order": on 260178 / machine 30 the 15 parts it flags that are
    not on Lines to Order all have OutstandingQty = PurchaseQty and TotalAvailable = 0 (already on a PO,
    not yet received). The proc also returns RequiredQty, OnOrder, Received, ToBeProcured,
    TotalQtyReleased, TotalQtyToBeReleased — the right "needs ordering" quantity has to be derived from
    these, and that needs evidence, not a guess.

This probe:
  P1  What Prerelease / Release / Unrelease mean in data: columns, per-(project,item) type mix, whether
      Prerelease precedes Release and whether the two carry the SAME quantity (double count), the 155
      partials re-checked with per-type sums, and today's Lines to Order split by prerelease-only.
  P2  CatergoryMajor / CategoryDescription / UOMType across Lines to Order items and across PO'd items
      (does 'Fabrications' get bought? is 'Purchased' the buy set?).
  P3  Readiness proc quantities for EVERY machine of the first project: which identities hold
      (Outstanding = Required - Available? OnOrder = PurchaseQty - Received? …), how populated
      ToBeProcured is, and a candidate "still to order" = Required - Available - OnOrder compared with
      Lines to Order. Timed per machine.
  P4  Parameters of udfEngStructuredReadiness (a set-based alternative to the per-scope proc).
  P5  Non-release PO lines, deeper: the projects carrying most of them (with names), and the
      "released on a different project" group — where the item WAS released vs where it was bought.
  P6  Where NON-BOM PO lines come from (item on no BOM, never released): PO columns that point back to a
      source document and how often they're set, ETO tables that could generate purchases (parts orders,
      process schedules, RFQs, requisitions, inventory pulls …) and how many non-BOM lines match each,
      buyers entering them, and whether the items carry an inventory minimum (stock replenishment).

RUN from the repo root where ETO is reachable:
    python console_diag_lines_to_order2.py                 # projects 260178 250005 220154 (take 1's set)
    python console_diag_lines_to_order2.py 260178 250005   # or name them
Paste the WHOLE output back.
"""
import sys, os, time

PIDS = [int(a) for a in sys.argv[1:] if a.strip().isdigit()] or [260178, 250005, 220154]
QUERY_TIMEOUT = 300
PROC_TIMEOUT = 120
READINESS_PROC = "urpEngStructuredReadinessBySpec"
QTY_COLS = ["TotalRequiredForEntireAssy", "TotalRequiredForEntireBOM", "RequiredQty", "PulledQty", "Reserved",
            "PurchaseQty", "Received", "OnOrder", "CompletedPS", "IssuedPS", "ToBeProcured",
            "TotalQtyReleased", "TotalQtyToBeReleased", "OutstandingQty", "TotalAvailable"]


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


ETO = None


def rule(t):
    print("\n" + "=" * 96 + f"\n{t}\n" + "=" * 96, flush=True)


def sub(t):
    print(f"\n--- {t}", flush=True)


def df(sql):
    import pandas as pd
    cur = ETO.cursor()
    cur.execute(sql)
    while cur.description is None:
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
    with pd.option_context("display.max_rows", max_rows, "display.max_columns", 40,
                           "display.width", 240, "display.max_colwidth", 44):
        print(frame.head(max_rows).to_string(index=False))
    if len(frame) > max_rows:
        print(f"   … {len(frame) - max_rows} more row(s)")


def ids_sql(vals):
    return ",".join(str(int(v)) for v in vals)


def pct(n, d):
    return f"{(100.0 * n / d):.1f}%" if d else "-"


# ════════════════════════════════════════════════════════════════════════════════════════════════
def p1(et):
    import pandas as pd
    rule("P1. RELEASE LOG TYPES — what Prerelease / Release / Unrelease mean in the data")
    sub("P1a. tblBOMReleaseHistory columns")
    show(safe("cols", lambda: df(
        "SELECT COLUMN_NAME, DATA_TYPE FROM INFORMATION_SCHEMA.COLUMNS WHERE TABLE_NAME='tblBOMReleaseHistory' "
        "ORDER BY ORDINAL_POSITION")), 60)

    sub("P1b. Per type: rows, sign of QuantityChange, ReleaseNote populated, first and last date")
    show(safe("types", lambda: df(
        "SELECT CAST([Type] AS nvarchar(50)) AS [Type], COUNT_BIG(*) AS Rows, "
        "SUM(CASE WHEN QuantityChange > 0 THEN 1 ELSE 0 END) AS QtyPos, "
        "SUM(CASE WHEN QuantityChange < 0 THEN 1 ELSE 0 END) AS QtyNeg, "
        "SUM(CASE WHEN ISNULL(QuantityChange,0) = 0 THEN 1 ELSE 0 END) AS QtyZeroOrNull, "
        "SUM(CASE WHEN NULLIF(LTRIM(RTRIM(CAST(ReleaseNote AS nvarchar(400)))),'') IS NOT NULL THEN 1 ELSE 0 END) AS WithNote, "
        "MIN(ReleasedDateTime) AS First, MAX(ReleasedDateTime) AS Last "
        "FROM dbo.tblBOMReleaseHistory GROUP BY CAST([Type] AS nvarchar(50)) ORDER BY Rows DESC")))

    sub(f"P1c. Per (project, machine, item) on projects {PIDS}: type mix, per-type qty, first date per type")
    per = safe("per", lambda: df(
        f"SELECT ProjectID, CAST(SpecID AS float) AS SpecID, ItemID, "
        f"SUM(CASE WHEN [Type]='Prerelease' THEN CAST(QuantityChange AS float) ELSE 0 END) AS PreQty, "
        f"SUM(CASE WHEN [Type]='Release'    THEN CAST(QuantityChange AS float) ELSE 0 END) AS RelQty, "
        f"SUM(CASE WHEN [Type]='Unrelease'  THEN CAST(QuantityChange AS float) ELSE 0 END) AS UnrelQty, "
        f"SUM(CAST(QuantityChange AS float)) AS NetAllTypes, "
        f"MIN(CASE WHEN [Type]='Prerelease' THEN ReleasedDateTime END) AS FirstPre, "
        f"MIN(CASE WHEN [Type]='Release'    THEN ReleasedDateTime END) AS FirstRel, "
        f"COUNT_BIG(*) AS Rows "
        f"FROM dbo.tblBOMReleaseHistory WHERE ProjectID IN ({ids_sql(PIDS)}) "
        f"GROUP BY ProjectID, CAST(SpecID AS float), ItemID"))
    if per is not None and not per.empty:
        has_pre = per["FirstPre"].notna()
        has_rel = per["FirstRel"].notna()
        n = len(per)
        print(f"   (project, machine, item) groups: {n:,}")
        print(f"     prerelease only        : {int((has_pre & ~has_rel).sum()):,}")
        print(f"     release only           : {int((~has_pre & has_rel).sum()):,}")
        print(f"     both                   : {int((has_pre & has_rel).sum()):,}")
        print(f"     neither (unrelease only): {int((~has_pre & ~has_rel).sum()):,}")
        both = per[has_pre & has_rel].copy()
        if not both.empty:
            both["DaysPreToRel"] = (pd.to_datetime(both["FirstRel"]) - pd.to_datetime(both["FirstPre"])).dt.days
            print(f"   for 'both': prerelease BEFORE release {int((both['DaysPreToRel'] > 0).sum()):,}; same day "
                  f"{int((both['DaysPreToRel'] == 0).sum()):,}; release BEFORE prerelease {int((both['DaysPreToRel'] < 0).sum()):,}")
            print(f"     days prerelease→release: median {both['DaysPreToRel'].median():.0f}, "
                  f"p90 {both['DaysPreToRel'].quantile(0.9):.0f}")
            eq = (both["PreQty"] - both["RelQty"]).abs() < 1e-9
            print(f"   for 'both': PreQty == RelQty {int(eq.sum()):,}; differ {int((~eq).sum()):,}  "
                  f"(if equal, summing ALL types double-counts the quantity)")
            show(both[["ProjectID", "SpecID", "ItemID", "PreQty", "RelQty", "UnrelQty", "NetAllTypes",
                       "FirstPre", "FirstRel", "DaysPreToRel"]].head(15), 15)

        sub("P1d. Full log rows for 3 'both' groups and 2 'prerelease only' groups (oldest first)")
        picks = list(both.head(3)[["ProjectID", "SpecID", "ItemID"]].itertuples(index=False)) if not both.empty else []
        picks += list(per[has_pre & ~has_rel].head(2)[["ProjectID", "SpecID", "ItemID"]].itertuples(index=False))
        for p, s, i in picks:
            print(f"   project {int(p)} machine {s:g} item {int(i)}:")
            show(safe("rows", lambda: df(
                f"SELECT * FROM dbo.tblBOMReleaseHistory WHERE ProjectID={int(p)} AND SpecID={float(s)} "
                f"AND ItemID={int(i)} ORDER BY ReleasedDateTime")), 20)

        sub("P1e. Today's Lines to Order rows split by release type (project+item level)")
        l2o = safe("l2o", lambda: df(et.query_released_to_order(PIDS)))
        if l2o is not None and not l2o.empty:
            pi = per.groupby(["ProjectID", "ItemID"]).agg(Pre=("FirstPre", "count"), Rel=("FirstRel", "count"),
                                                           PreQty=("PreQty", "sum"), RelQty=("RelQty", "sum"),
                                                           Net=("NetAllTypes", "sum")).reset_index()
            m = l2o.merge(pi, on=["ProjectID", "ItemID"], how="left")
            print(f"   Lines to Order rows: {len(m):,}")
            print(f"     item PRERELEASED only (never 'Release'): {int(((m['Pre'] > 0) & (m['Rel'] == 0)).sum()):,}")
            print(f"     item has a 'Release' row               : {int((m['Rel'] > 0).sum()):,}")
            dbl = m[(m["Pre"] > 0) & (m["Rel"] > 0) & ((m["PreQty"] - m["RelQty"]).abs() < 1e-9)]
            print(f"     both, equal qty (list qty = 2× true qty if double-counted): {len(dbl):,}")
            show(dbl[["ProjectID", "ItemNo", "Description", "Qty", "PreQty", "RelQty"]].head(10), 10)

        sub("P1f. The take-1 'partials' re-checked: PO qty vs Release-only qty vs all-types qty (project+item)")
        po = safe("po", lambda: df(
            f"SELECT pod.ProjectID, pod.ItemID, SUM(CAST(pod.PurchaseQty AS float)) AS POQty "
            f"FROM dbo.vwPurchaseOrderDetails pod JOIN dbo.vwPurchaseOrderHeader poh ON poh.PurchaseOrderID = pod.PurchaseOrderID "
            f"WHERE poh.PurchaseActive = 1 AND pod.ProjectID IN ({ids_sql(PIDS)}) AND pod.ItemID IS NOT NULL "
            f"GROUP BY pod.ProjectID, pod.ItemID"))
        if po is not None:
            pi2 = per.groupby(["ProjectID", "ItemID"], as_index=False)[["PreQty", "RelQty", "UnrelQty", "NetAllTypes"]].sum()
            j = pi2.merge(po, on=["ProjectID", "ItemID"], how="inner")
            j = j[j["NetAllTypes"] > 0]
            short_all = j[j["POQty"] < j["NetAllTypes"]]
            rel_net = j["RelQty"] + j["UnrelQty"]
            short_rel = j[(rel_net > 0) & (j["POQty"] < rel_net)]
            pre_net = j["PreQty"] + j["UnrelQty"]
            short_pre = j[(pre_net > 0) & (j["POQty"] < pre_net)]
            print(f"   items with a PO and net released qty > 0: {len(j):,}")
            print(f"     PO qty < ALL-types net (take-1 method)     : {len(short_all):,}")
            print(f"     PO qty < Release(+Unrelease) qty only      : {len(short_rel):,}")
            print(f"     PO qty < Prerelease(+Unrelease) qty only   : {len(short_pre):,}")
            show(short_all[["ProjectID", "ItemID", "PreQty", "RelQty", "UnrelQty", "NetAllTypes", "POQty"]].head(15), 15)


# ════════════════════════════════════════════════════════════════════════════════════════════════
def p2(et):
    import pandas as pd
    rule("P2. MAKE vs BUY candidates — CatergoryMajor / CategoryDescription / UOMType (vwEngProductStructure)")
    ps = safe("ps", lambda: df(
        f"SELECT DISTINCT ProjectID, CAST(SpecID AS float) AS SpecID, ChildID AS ItemID, "
        f"CAST(UOMType AS nvarchar(40)) AS UOMType, CAST(CatergoryMajor AS nvarchar(100)) AS CatMajor, "
        f"CAST(CategoryDescription AS nvarchar(100)) AS Category "
        f"FROM dbo.vwEngProductStructure WHERE ProjectID IN ({ids_sql(PIDS)})"))
    if ps is None or ps.empty:
        return
    sub(f"P2a. All BOM lines on {PIDS}: CatergoryMajor × UOMType")
    show(ps.pivot_table(index="CatMajor", columns="UOMType", values="ItemID", aggfunc="count", fill_value=0)
         .reset_index(), 40)
    sub("P2b. CatergoryMajor → its CategoryDescription values (top 8 each)")
    for cm, g in ps.groupby(ps["CatMajor"].fillna("(NULL)")):
        vc = g["Category"].fillna("(NULL)").value_counts()
        print(f"   {cm}: " + "; ".join(f"{k}={v}" for k, v in vc.head(8).items()))
    l2o = safe("l2o", lambda: df(et.query_released_to_order(PIDS)))
    if l2o is not None and not l2o.empty:
        sub("P2c. Today's Lines to Order rows by CatergoryMajor / UOMType (project+item match)")
        pi = ps.drop_duplicates(["ProjectID", "ItemID"])[["ProjectID", "ItemID", "CatMajor", "UOMType", "Category"]]
        m = l2o.merge(pi, on=["ProjectID", "ItemID"], how="left")
        show(m.groupby([m["CatMajor"].fillna("(not in structure)"), m["UOMType"].fillna("-")]).size()
             .rename("Rows").reset_index().sort_values("Rows", ascending=False), 30)
    sub("P2d. Items that WERE bought on these projects (have a PO line) by CatergoryMajor / UOMType")
    po = safe("po items", lambda: df(
        f"SELECT DISTINCT pod.ProjectID, pod.ItemID FROM dbo.vwPurchaseOrderDetails pod "
        f"JOIN dbo.vwPurchaseOrderHeader poh ON poh.PurchaseOrderID = pod.PurchaseOrderID "
        f"WHERE poh.PurchaseActive = 1 AND pod.ProjectID IN ({ids_sql(PIDS)}) AND pod.ItemID IS NOT NULL"))
    if po is not None and not po.empty:
        pi = ps.drop_duplicates(["ProjectID", "ItemID"])[["ProjectID", "ItemID", "CatMajor", "UOMType"]]
        m = pi.merge(po.assign(Bought=1), on=["ProjectID", "ItemID"], how="left")
        m["Bought"] = m["Bought"].fillna(0).astype(int)
        t = m.groupby([m["CatMajor"].fillna("(NULL)"), m["UOMType"].fillna("-")]).agg(
            BOMItems=("ItemID", "count"), Bought=("Bought", "sum")).reset_index()
        t["BoughtShare"] = [pct(b, n) for b, n in zip(t["Bought"], t["BOMItems"])]
        show(t.sort_values("BOMItems", ascending=False), 40)


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


def p3(et):
    import pandas as pd
    pid = PIDS[0]
    rule(f"P3. READINESS PROC QUANTITIES — every machine of project {pid}: which quantity means 'still to order'?")
    specs = safe("specs", lambda: df(
        f"SELECT DISTINCT CAST(SpecID AS float) AS SpecID FROM dbo.vwEngProductStructure WHERE ProjectID = {pid} ORDER BY 1"))
    if specs is None or specs.empty:
        return
    try:
        ETO.timeout = PROC_TIMEOUT
    except Exception:
        pass
    frames, t_all = [], time.time()
    for spec in specs["SpecID"].tolist():
        scopes = safe("scopes", lambda: df(
            f"WITH roots AS (SELECT DISTINCT ParentID FROM dbo.vwEngProductStructure "
            f"  WHERE ProjectID={pid} AND SpecID={spec} AND ParentID NOT IN "
            f"  (SELECT ChildID FROM dbo.vwEngProductStructure WHERE ProjectID={pid} AND SpecID={spec})) "
            f"SELECT s.StructureID FROM dbo.vwEngProductStructure s JOIN roots r ON s.ParentID = r.ParentID "
            f"WHERE s.ProjectID={pid} AND s.SpecID={spec}"))
        t0, n = time.time(), 0
        for asm in ([] if scopes is None else scopes["StructureID"].tolist()):
            one = safe(f"proc {spec:g}/{asm}", lambda: readiness_df(
                "SET NOCOUNT ON; "
                f"EXEC dbo.{READINESS_PROC} @intProjectID={pid}, @decSpecID={spec}, "
                f"@intAssemblyStructureID={int(asm)}, @bitExplodeStandardAssemblies=1, @intWeightMethod=0, "
                f"@bitAssembliesOnly=0, @bitHideFullyAvailable=0, @intNumberOfLevels=99, @intIndentSpaces=3, "
                f"@bitAverageWithBOMQty=0"))
            if one is not None and not one.empty:
                one["SpecIDq"] = spec
                frames.append(one)
                n += len(one)
        print(f"   machine {spec:g}: {0 if scopes is None else len(scopes)} scope(s), {n:,} rows, {time.time() - t0:.1f}s", flush=True)
    try:
        ETO.timeout = QUERY_TIMEOUT
    except Exception:
        pass
    print(f"   total for project {pid}: {time.time() - t_all:.1f}s")
    if not frames:
        return
    rd = pd.concat(frames, ignore_index=True)
    rd = rd[pd.to_numeric(rd.get("Depth"), errors="coerce").fillna(0) > 0]
    for c in QTY_COLS:
        if c in rd.columns:
            rd[c] = pd.to_numeric(rd[c], errors="coerce")
    is_as = rd["UOMType"].astype(str).str.upper().str.startswith("AS")
    parts = rd[~is_as]
    per = parts.groupby(["SpecIDq", "ItemCompanyID"], as_index=False)[[c for c in QTY_COLS if c in parts.columns]].max()
    sub(f"P3a. Population of each quantity column (parts only, one row per machine+item: {len(per):,})")
    for c in QTY_COLS:
        if c in per.columns:
            s = per[c]
            print(f"   {c:28} null {int(s.isna().sum()):>6,}   zero {int((s == 0).sum()):>6,}   >0 {int((s > 0).sum()):>6,}   <0 {int((s < 0).sum()):>5,}")

    sub("P3b. Which identities hold (share of machine+item rows where the equation is exact)")
    def chk(label, lhs, rhs):
        try:
            ok = ((lhs - rhs).abs() < 1e-6) | (lhs.isna() & rhs.isna())
            print(f"   {label:72} {pct(int(ok.sum()), len(ok))}")
        except Exception as e:
            print(f"   {label:72} n/a ({e})")
    g = lambda c: per[c] if c in per.columns else pd.Series([float('nan')] * len(per))
    chk("OutstandingQty = TotalRequiredForEntireBOM − TotalAvailable", g("OutstandingQty"), g("TotalRequiredForEntireBOM") - g("TotalAvailable"))
    chk("OutstandingQty = TotalRequiredForEntireAssy − TotalAvailable", g("OutstandingQty"), g("TotalRequiredForEntireAssy") - g("TotalAvailable"))
    chk("OutstandingQty = RequiredQty − TotalAvailable", g("OutstandingQty"), g("RequiredQty") - g("TotalAvailable"))
    chk("OutstandingQty = TotalRequiredForEntireBOM − Received", g("OutstandingQty"), g("TotalRequiredForEntireBOM") - g("Received"))
    chk("TotalAvailable = Received − PulledQty", g("TotalAvailable"), g("Received") - g("PulledQty"))
    chk("OnOrder = PurchaseQty − Received", g("OnOrder"), g("PurchaseQty") - g("Received"))
    chk("ToBeProcured = OutstandingQty − OnOrder", g("ToBeProcured"), g("OutstandingQty") - g("OnOrder"))
    chk("RequiredQty = TotalRequiredForEntireBOM", g("RequiredQty"), g("TotalRequiredForEntireBOM"))
    chk("TotalQtyReleased + TotalQtyToBeReleased = TotalRequiredForEntireBOM",
        g("TotalQtyReleased") + g("TotalQtyToBeReleased"), g("TotalRequiredForEntireBOM"))

    sub("P3c. Candidate 'still to order' = TotalRequiredForEntireBOM − TotalAvailable − OnOrder (parts, > 0) vs Lines to Order")
    per["Cand"] = g("TotalRequiredForEntireBOM") - g("TotalAvailable").fillna(0) - g("OnOrder").fillna(0)
    l2o = safe("l2o", lambda: df(et.query_released_to_order([pid])))
    if l2o is None:
        return
    lset = {(float(s), str(n).strip()) for s, n in l2o[["MachineCode", "ItemNo"]].dropna().itertuples(index=False)}
    cset = {(float(s), str(n).strip()) for s, n in per.loc[per["Cand"] > 0, ["SpecIDq", "ItemCompanyID"]].itertuples(index=False)}
    allset = {(float(s), str(n).strip()) for s, n in per[["SpecIDq", "ItemCompanyID"]].itertuples(index=False)}
    print(f"   Lines to Order (project {pid}): {len(lset):,}   candidate > 0: {len(cset):,}")
    print(f"     both                                   : {len(lset & cset):,}")
    print(f"     Lines to Order only                    : {len(lset - cset):,}   (not in proc output at all: {len(lset - allset):,})")
    print(f"     candidate only (needs ordering, not listed): {len(cset - lset):,}")
    key = per.assign(K=list(zip(per["SpecIDq"].astype(float), per["ItemCompanyID"].astype(str).str.strip())))
    cols = ["SpecIDq", "ItemCompanyID"] + [c for c in ("TotalRequiredForEntireBOM", "RequiredQty", "TotalAvailable",
                                                       "PurchaseQty", "Received", "OnOrder", "ToBeProcured",
                                                       "TotalQtyReleased", "OutstandingQty", "Cand") if c in key.columns]
    print("\n   sample — on Lines to Order but candidate ≤ 0:")
    show(key[key["K"].isin(lset - cset)][cols].head(15), 15)
    print("\n   sample — candidate > 0 but NOT on Lines to Order:")
    show(key[key["K"].isin(cset - lset)][cols].head(15), 15)


# ════════════════════════════════════════════════════════════════════════════════════════════════
def p4():
    rule("P4. Set-based readiness source — parameters of the readiness functions/procs")
    show(safe("params", lambda: df(
        "SELECT OBJECT_NAME(p.object_id) AS Obj, p.parameter_id AS N, p.name AS Param, TYPE_NAME(p.user_type_id) AS Type "
        "FROM sys.parameters p WHERE p.object_id IN (OBJECT_ID('dbo.udfEngStructuredReadiness'), "
        "OBJECT_ID('dbo.urpEngStructuredReadinessBySpec'), OBJECT_ID('dbo.crp0470EngStructuredReadiness'), "
        "OBJECT_ID('dbo.udfPartsOrderAssemblyAddToProcurement')) ORDER BY Obj, N")), 60)


# ════════════════════════════════════════════════════════════════════════════════════════════════
NR_LINES = """
SELECT pod.PurchaseOrderID AS PO, pod.ProjectID, p.DisplayName AS Project, pod.ItemID, pod.ItemCompanyID AS ItemNo,
       pod.ItemDescription AS Descr, pdd.ItemMasterCategoryDescription AS Category,
       CAST(poh.PurchaseDate AS date) AS PODate
FROM dbo.vwPurchaseOrderHeader poh
JOIN dbo.vwPurchaseOrderDetails pod ON pod.PurchaseOrderID = poh.PurchaseOrderID
LEFT JOIN dbo.vwPurchaseOrderDetailsDetailed pdd ON pdd.PurchaseDetailID = pod.PurchaseDetailID
LEFT JOIN dbo.tblProjects p ON p.ProjectID = pod.ProjectID
WHERE poh.PurchaseActive = 1
  AND NOT EXISTS (SELECT 1 FROM dbo.tblBOMReleaseHistory h WHERE h.ProjectID = pod.ProjectID AND h.ItemID = pod.ItemID)
"""


def p5():
    import pandas as pd
    rule("P5. PO LINES WITH NO RELEASE — which projects, and the 'released on a different project' group")
    nr = safe("nr", lambda: df(NR_LINES))
    if nr is None or nr.empty:
        return
    sub("P5a. Top 15 projects by no-release PO lines (all years), with name")
    t = nr.groupby(["ProjectID", "Project"], dropna=False).size().rename("Lines").reset_index()
    show(t.sort_values("Lines", ascending=False).head(15), 15)
    rel = safe("rel", lambda: df(
        "SELECT ItemID, COUNT(DISTINCT ProjectID) AS RelProjects, MIN(ProjectID) AS AnyRelProject "
        "FROM dbo.tblBOMReleaseHistory GROUP BY ItemID"))
    if rel is None:
        return
    m = nr.merge(rel, on="ItemID", how="inner")
    sub(f"P5b. No-release lines whose item WAS released on another project: {len(m):,} — top categories")
    show(m.groupby(m["Category"].fillna("(none)")).size().rename("Lines").reset_index()
         .sort_values("Lines", ascending=False).head(15), 15)
    print("\n   20 most recent (bought on ProjectID, released on AnyRelProject):")
    show(m.sort_values("PODate", ascending=False)[["PODate", "PO", "ProjectID", "Project", "ItemNo", "Descr",
                                                  "Category", "RelProjects", "AnyRelProject"]].head(20), 20)


# ════════════════════════════════════════════════════════════════════════════════════════════════
# NON-BOM PO lines = item on NO project's BOM and NEVER released on any project (take 1: 17,093 lines, 70% of
# the no-release lines). Bounded to POs dated in the last 2 years so the source scans stay fast.
NONBOM_CTE = """
WITH nb AS (
    SELECT pod.PurchaseOrderID, pod.PurchaseDetailID, pod.ProjectID, pod.ItemID, poh.BuyerID
    FROM dbo.vwPurchaseOrderHeader poh
    JOIN dbo.vwPurchaseOrderDetails pod ON pod.PurchaseOrderID = poh.PurchaseOrderID
    WHERE poh.PurchaseActive = 1 AND poh.PurchaseDate >= DATEADD(year, -2, GETDATE())
      AND pod.ItemID IS NOT NULL
      AND NOT EXISTS (SELECT 1 FROM dbo.vwEngBOM b WHERE b.ItemID = pod.ItemID)
      AND NOT EXISTS (SELECT 1 FROM dbo.tblBOMReleaseHistory h WHERE h.ItemID = pod.ItemID)
)"""
SRC_PAT = ("PartsOrder", "ProcessSchedule", "RFQ", "Requisition", "Inventory", "Pull", "WorkOrder", "Procure", "Kit")


def p6():
    import pandas as pd
    rule("P6. WHERE DO NON-BOM PO LINES COME FROM? (item on no BOM, never released; POs from the last 2 years)")
    n = safe("count", lambda: df(NONBOM_CTE + " SELECT COUNT_BIG(*) AS Lines, COUNT(DISTINCT ItemID) AS Items, "
                                 "COUNT(DISTINCT ProjectID) AS Projects, COUNT(DISTINCT PurchaseOrderID) AS POs FROM nb"))
    show(n)

    sub("P6a. PO detail/header columns that could point back to a SOURCE document (name match), and how often "
        "they are populated on non-BOM lines vs all lines")
    cols = safe("cols", lambda: df(
        "SELECT TABLE_NAME, COLUMN_NAME, DATA_TYPE FROM INFORMATION_SCHEMA.COLUMNS "
        "WHERE TABLE_NAME IN ('tblPurchaseOrderDetails','tblPurchaseOrderHeader') ORDER BY TABLE_NAME, ORDINAL_POSITION"))
    if cols is not None and not cols.empty:
        print("   tblPurchaseOrderDetails: " + ", ".join(cols.loc[cols.TABLE_NAME == "tblPurchaseOrderDetails", "COLUMN_NAME"]))
        print("   tblPurchaseOrderHeader : " + ", ".join(cols.loc[cols.TABLE_NAME == "tblPurchaseOrderHeader", "COLUMN_NAME"]))
        link = cols[cols["COLUMN_NAME"].str.contains(r"ID$|Source|Origin|RFQ|Req|Order|Process|Schedule|Pull|Entered|Created",
                                                    case=False, regex=True)
                    & ~cols["COLUMN_NAME"].isin(["PurchaseOrderID", "PurchaseDetailID", "ItemID", "ProjectID"])]
        for r in link.itertuples(index=False):
            alias, key = ("d", "d.PurchaseDetailID = nb.PurchaseDetailID") if r.TABLE_NAME == "tblPurchaseOrderDetails" \
                else ("h", "h.PurchaseOrderID = nb.PurchaseOrderID")
            nz = (f"NULLIF(LTRIM(RTRIM(CAST({alias}.[{r.COLUMN_NAME}] AS nvarchar(200)))),'') IS NOT NULL "
                  f"AND CAST({alias}.[{r.COLUMN_NAME}] AS nvarchar(200)) NOT IN ('0','False')")
            res = safe(r.COLUMN_NAME, lambda: df(
                NONBOM_CTE + f" SELECT SUM(CASE WHEN {nz} THEN 1 ELSE 0 END) AS NonBOMSet, COUNT_BIG(*) AS NonBOMLines "
                f"FROM nb JOIN dbo.{r.TABLE_NAME} {alias} ON {key}"))
            allr = safe(r.COLUMN_NAME + " all", lambda: df(
                f"SELECT SUM(CASE WHEN {nz} THEN 1 ELSE 0 END) AS AllSet, COUNT_BIG(*) AS AllLines FROM dbo.{r.TABLE_NAME} {alias}"))
            if res is not None and allr is not None and not res.empty and not allr.empty:
                a, b = int(res.iloc[0, 0] or 0), int(res.iloc[0, 1] or 0)
                c, d = int(allr.iloc[0, 0] or 0), int(allr.iloc[0, 1] or 0)
                print(f"   {r.TABLE_NAME[3:]:24} {r.COLUMN_NAME:34} non-BOM {pct(a, b):>7}   all {pct(c, d):>7}")

    sub("P6b. Objects that could GENERATE purchases, and how many non-BOM lines' items (same project where the "
        "object has a ProjectID) appear in each")
    objs = safe("objs", lambda: df(
        "SELECT c.TABLE_NAME, MAX(CASE WHEN c.COLUMN_NAME='ProjectID' THEN 1 ELSE 0 END) AS HasProject, t.TABLE_TYPE "
        "FROM INFORMATION_SCHEMA.COLUMNS c JOIN INFORMATION_SCHEMA.TABLES t ON t.TABLE_NAME = c.TABLE_NAME "
        "WHERE c.TABLE_NAME IN (SELECT TABLE_NAME FROM INFORMATION_SCHEMA.COLUMNS WHERE COLUMN_NAME = 'ItemID') "
        "AND (" + " OR ".join(f"c.TABLE_NAME LIKE '%{p}%'" for p in SRC_PAT) + ") "
        "AND t.TABLE_TYPE = 'BASE TABLE' GROUP BY c.TABLE_NAME, t.TABLE_TYPE ORDER BY c.TABLE_NAME"))
    if objs is not None and not objs.empty:
        for r in objs.itertuples(index=False):
            cond = "x.ItemID = nb.ItemID" + (" AND x.ProjectID = nb.ProjectID" if r.HasProject else "")
            res = safe(r.TABLE_NAME, lambda: df(
                NONBOM_CTE + f" SELECT COUNT_BIG(*) AS Matched FROM nb WHERE EXISTS "
                f"(SELECT 1 FROM dbo.[{r.TABLE_NAME}] x WHERE {cond})"))
            if res is not None and not res.empty:
                print(f"   {r.TABLE_NAME:44} {'item+project' if r.HasProject else 'item only':13} matched lines: {int(res.iloc[0, 0]):>7,}")
    else:
        print("   (no base tables matched)")

    sub("P6c. Non-BOM lines by buyer (vs BOM-sourced lines, same 2-year window)")
    show(safe("buyers", lambda: df(
        NONBOM_CTE + " SELECT COALESCE(e.EmpLastName + ', ' + e.EmpFirstName, CAST(nb.BuyerID AS varchar(20)), '(none)') AS Buyer, "
        "COUNT_BIG(*) AS NonBOMLines FROM nb LEFT JOIN dbo.tblEmployee e ON e.EmployeeID = nb.BuyerID "
        "GROUP BY COALESCE(e.EmpLastName + ', ' + e.EmpFirstName, CAST(nb.BuyerID AS varchar(20)), '(none)') "
        "ORDER BY NonBOMLines DESC")), 25)

    sub("P6d. Non-BOM items: inventory min level set? (would suggest stock replenishment)")
    show(safe("min", lambda: df(
        NONBOM_CTE + " SELECT COUNT(DISTINCT nb.ItemID) AS NonBOMItems, "
        "COUNT(DISTINCT CASE WHEN inv.QtyMinRequired > 0 THEN nb.ItemID END) AS WithMinLevel, "
        "COUNT(DISTINCT CASE WHEN inv.ItemID IS NOT NULL THEN nb.ItemID END) AS StockedAnywhere "
        "FROM nb LEFT JOIN dbo.vwInventory inv ON inv.ItemID = nb.ItemID")))


def main():
    global ETO
    et = import_etospec()
    ETO = eto_connect()
    try:
        ETO.timeout = QUERY_TIMEOUT
    except Exception:
        pass
    print(f"console_diag_lines_to_order2 — {time.strftime('%Y-%m-%d %H:%M')}  (read-only)  projects {PIDS}")
    safe("P1", lambda: p1(et))
    safe("P2", lambda: p2(et))
    safe("P3", lambda: p3(et))
    safe("P4", p4)
    safe("P5", p5)
    safe("P6", p6)
    ETO.close()
    print("\nDONE — paste everything above.")


if __name__ == "__main__":
    main()
