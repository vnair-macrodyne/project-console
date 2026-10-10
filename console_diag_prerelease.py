"""
console_diag_prerelease.py — is PRERELEASE the long-lead release to purchasing?  READ-ONLY.  (2026-10-10)

Vijay: a Prerelease is generally the mechanism to release LONG LEAD items to purchasing; if we
differentiate it accurately, we can show purchasing the long-lead items to follow up and track.

What we already know (probes 2026-10-09):
  * tblBOMReleaseHistory types: Prerelease 141,636 rows / Release 49,055 / Unrelease 59 (unused since 2019-06).
  * Long Lead flag (tblEngItemMaster.PartCustom7, caption 'Long Lead Item'): 81 items tagged, 71 on POs.
  * On 260178/250005/220154, (project, machine, item) groups: 1,479 prerelease-only, 3,094 release-only,
    159 both — and in all 159 the Prerelease came first (median 47 days).
The volume gap (141k prerelease rows vs 81 flagged items) has to be explained before the reports rely on
"prerelease = long lead". This probe tests it from several independent angles:

  Q1  Type mix by year (is prerelease a recent practice or always the bulk?).
  Q2  Coverage: what share of each project's BOM parts get a Prerelease at all (selective vs whole-BOM).
  Q3  Batches: rows per release action (same person, project, minute) — whole-BOM dumps vs hand-picked items.
  Q4  Who: prerelease / release rows by person (last 2 years), with names.
  Q5  Long Lead flag vs type: of flagged items, how many were prereleased; of prereleased items, how many flagged.
  Q6  Lead time vs type: maintained EstimatedLeadTime and historical PO lead time (order → last receipt) for
      prerelease-only / both / release-only items. If prerelease = long lead, its lead times should be longer.
  Q7  Timing: on the sample projects, when was the first PO placed relative to the first Prerelease and the
      first Release? (Does purchasing actually order on the prerelease?)
  Q8  Quantity double-count test: per machine + part, net logged qty (all types / Release only / Prerelease
      only) vs the BOM's own required qty (readiness proc TotalRequiredForEntireBOM) — which one matches.

RUN from the repo root where ETO is reachable:
    python console_diag_prerelease.py                    # sample projects 260178 250005 220154
    python console_diag_prerelease.py 260178 250005      # or name them
Paste the WHOLE output back.
"""
import sys, os, time

PIDS = [int(a) for a in sys.argv[1:] if a.strip().isdigit()] or [260178, 250005, 220154]
QUERY_TIMEOUT = 300
PROC_TIMEOUT = 120
READINESS_PROC = "urpEngStructuredReadinessBySpec"
LLT = "PartCustom7"


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
    with pd.option_context("display.max_rows", max_rows, "display.max_columns", 30,
                           "display.width", 230, "display.max_colwidth", 44):
        print(frame.head(max_rows).to_string(index=False))
    if len(frame) > max_rows:
        print(f"   … {len(frame) - max_rows} more row(s)")


def ids_sql(vals):
    return ",".join(str(int(v)) for v in vals)


def pct(n, d):
    return f"{(100.0 * n / d):.1f}%" if d else "-"


# per (project, item): which types it has — whole database
ITEM_TYPES = """
SELECT ProjectID, ItemID,
       MAX(CASE WHEN [Type]='Prerelease' THEN 1 ELSE 0 END) AS HasPre,
       MAX(CASE WHEN [Type]='Release'    THEN 1 ELSE 0 END) AS HasRel,
       MIN(CASE WHEN [Type]='Prerelease' THEN ReleasedDateTime END) AS FirstPre,
       MIN(CASE WHEN [Type]='Release'    THEN ReleasedDateTime END) AS FirstRel
FROM dbo.tblBOMReleaseHistory
WHERE [Type] IN ('Prerelease','Release')
GROUP BY ProjectID, ItemID
"""


def q1():
    rule("Q1. Release-log rows by TYPE and YEAR (positive-quantity rows only = actual releases)")
    show(safe("q1", lambda: df(
        "SELECT YEAR(ReleasedDateTime) AS Yr, "
        "SUM(CASE WHEN [Type]='Prerelease' AND QuantityChange > 0 THEN 1 ELSE 0 END) AS Prerelease, "
        "SUM(CASE WHEN [Type]='Release'    AND QuantityChange > 0 THEN 1 ELSE 0 END) AS Release, "
        "COUNT(DISTINCT CASE WHEN [Type]='Prerelease' THEN ProjectID END) AS ProjWithPre, "
        "COUNT(DISTINCT CASE WHEN [Type]='Release'    THEN ProjectID END) AS ProjWithRel "
        "FROM dbo.tblBOMReleaseHistory GROUP BY YEAR(ReleasedDateTime) ORDER BY Yr")))


def q2():
    rule("Q2. COVERAGE — share of each project's current-BOM parts that were prereleased / released")
    show(safe("q2", lambda: df(f"""
        WITH bom AS (SELECT DISTINCT ProjectID, ItemID FROM dbo.vwEngBOM WHERE ProjectID IN ({ids_sql(PIDS)})),
        t AS ({ITEM_TYPES})
        SELECT bom.ProjectID, COUNT(*) AS BOMParts,
               SUM(CASE WHEN t.HasPre=1 AND t.HasRel=0 THEN 1 ELSE 0 END) AS PrereleaseOnly,
               SUM(CASE WHEN t.HasPre=1 AND t.HasRel=1 THEN 1 ELSE 0 END) AS Both,
               SUM(CASE WHEN t.HasPre=0 AND t.HasRel=1 THEN 1 ELSE 0 END) AS ReleaseOnly,
               SUM(CASE WHEN t.ItemID IS NULL THEN 1 ELSE 0 END) AS NotInLog
        FROM bom LEFT JOIN t ON t.ProjectID = bom.ProjectID AND t.ItemID = bom.ItemID
        GROUP BY bom.ProjectID ORDER BY bom.ProjectID""")))
    print("\n   All projects with release-log activity since 2024 (how common is a mostly-prerelease project?):")
    d = safe("q2b", lambda: df(f"""
        WITH t AS ({ITEM_TYPES}),
        p AS (SELECT DISTINCT ProjectID FROM dbo.tblBOMReleaseHistory WHERE ReleasedDateTime >= '20240101')
        SELECT t.ProjectID, COUNT(*) AS LoggedParts,
               SUM(CASE WHEN t.HasPre=1 THEN 1 ELSE 0 END) AS WithPre,
               SUM(CASE WHEN t.HasRel=1 THEN 1 ELSE 0 END) AS WithRel
        FROM t JOIN p ON p.ProjectID = t.ProjectID GROUP BY t.ProjectID"""))
    if d is not None and not d.empty:
        d["PreShare"] = d["WithPre"] / d["LoggedParts"]
        bins = [(-0.01, 0.0, "0%"), (0.0, 0.25, "1–25%"), (0.25, 0.5, "26–50%"), (0.5, 0.75, "51–75%"),
                (0.75, 0.999, "76–99%"), (0.999, 1.0, "100%")]
        for lo, hi, lab in bins:
            print(f"     projects where {lab:7} of logged parts were prereleased: {int(((d.PreShare > lo) & (d.PreShare <= hi)).sum()):>5}")
        print(f"     (projects: {len(d)})")


def q3():
    rule("Q3. BATCHES — rows per release action (same person + project + type + minute), since 2024")
    d = safe("q3", lambda: df("""
        SELECT [Type], ReleasedByEmployeeID, ProjectID,
               DATEADD(minute, DATEDIFF(minute, 0, ReleasedDateTime), 0) AS Minute, COUNT_BIG(*) AS Rows
        FROM dbo.tblBOMReleaseHistory
        WHERE ReleasedDateTime >= '20240101' AND QuantityChange > 0 AND [Type] IN ('Prerelease','Release')
        GROUP BY [Type], ReleasedByEmployeeID, ProjectID, DATEADD(minute, DATEDIFF(minute, 0, ReleasedDateTime), 0)"""))
    if d is None or d.empty:
        return
    for typ, g in d.groupby("Type"):
        r = g["Rows"]
        print(f"   {typ:10} actions {len(g):>6,}   rows {int(r.sum()):>7,}   rows/action median {r.median():.0f}  "
              f"p90 {r.quantile(.9):.0f}  max {int(r.max())}   single-item actions {int((r == 1).sum()):,} "
              f"({pct(int((r == 1).sum()), len(g))})   actions with ≥50 items {int((r >= 50).sum()):,}")


def q4():
    rule("Q4. WHO — prerelease / release rows by person since 2024")
    show(safe("q4", lambda: df("""
        SELECT COALESCE(e.EmpLastName + ', ' + e.EmpFirstName, CAST(h.ReleasedByEmployeeID AS varchar(20))) AS Person,
               h.ReleasedByEmployeeID AS EmpID,
               SUM(CASE WHEN h.[Type]='Prerelease' AND h.QuantityChange > 0 THEN 1 ELSE 0 END) AS Prerelease,
               SUM(CASE WHEN h.[Type]='Release'    AND h.QuantityChange > 0 THEN 1 ELSE 0 END) AS Release
        FROM dbo.tblBOMReleaseHistory h LEFT JOIN dbo.tblEmployee e ON e.EmployeeID = h.ReleasedByEmployeeID
        WHERE h.ReleasedDateTime >= '20240101'
        GROUP BY COALESCE(e.EmpLastName + ', ' + e.EmpFirstName, CAST(h.ReleasedByEmployeeID AS varchar(20))), h.ReleasedByEmployeeID
        ORDER BY Prerelease + Release DESC""")), 30)


def q5():
    rule(f"Q5. LONG LEAD FLAG ({LLT}) vs release type — per (project, item), whole log")
    d = safe("q5", lambda: df(f"""
        WITH t AS ({ITEM_TYPES})
        SELECT CASE WHEN CAST(eim.[{LLT}] AS int) = 1 THEN 'Long Lead' ELSE 'not flagged' END AS Flag,
               SUM(CASE WHEN t.HasPre=1 AND t.HasRel=0 THEN 1 ELSE 0 END) AS PrereleaseOnly,
               SUM(CASE WHEN t.HasPre=1 AND t.HasRel=1 THEN 1 ELSE 0 END) AS Both,
               SUM(CASE WHEN t.HasPre=0 AND t.HasRel=1 THEN 1 ELSE 0 END) AS ReleaseOnly,
               COUNT(*) AS ProjectItems
        FROM t LEFT JOIN dbo.tblEngItemMaster eim ON eim.ItemID = t.ItemID
        GROUP BY CASE WHEN CAST(eim.[{LLT}] AS int) = 1 THEN 'Long Lead' ELSE 'not flagged' END"""))
    show(d)
    print("\n   Flagged Long Lead items with their release history (all projects):")
    show(safe("q5b", lambda: df(f"""
        WITH t AS ({ITEM_TYPES})
        SELECT eim.ItemCompanyID, LEFT(eim.ItemDescription, 40) AS Description,
               COUNT(t.ProjectID) AS Projects, SUM(t.HasPre) AS PreProjects, SUM(t.HasRel) AS RelProjects
        FROM dbo.tblEngItemMaster eim LEFT JOIN t ON t.ItemID = eim.ItemID
        WHERE CAST(eim.[{LLT}] AS int) = 1
        GROUP BY eim.ItemCompanyID, LEFT(eim.ItemDescription, 40) ORDER BY Projects DESC""")), 40)


def q6():
    rule("Q6. LEAD TIME by release type — maintained EstimatedLeadTime and historical PO lead time (days)")
    d = safe("q6", lambda: df(f"""
        WITH t AS ({ITEM_TYPES}),
        hist AS (
            SELECT pod.ItemID, AVG(CAST(DATEDIFF(day, poh.PurchaseDate, pdd.LastReceivedDate) AS float)) AS HistLead
            FROM dbo.vwPurchaseOrderHeader poh
            JOIN dbo.vwPurchaseOrderDetails pod ON pod.PurchaseOrderID = poh.PurchaseOrderID
            JOIN dbo.vwPurchaseOrderDetailsDetailed pdd ON pdd.PurchaseDetailID = pod.PurchaseDetailID
            WHERE pdd.LastReceivedDate IS NOT NULL
              AND DATEDIFF(day, poh.PurchaseDate, pdd.LastReceivedDate) BETWEEN 0 AND 730
            GROUP BY pod.ItemID)
        SELECT CASE WHEN t.HasPre=1 AND t.HasRel=0 THEN 'prerelease only'
                    WHEN t.HasPre=1 AND t.HasRel=1 THEN 'both'
                    ELSE 'release only' END AS Kind,
               CAST(eim.EstimatedLeadTime AS float) AS EstLead, hist.HistLead
        FROM t LEFT JOIN dbo.tblEngItemMaster eim ON eim.ItemID = t.ItemID
        LEFT JOIN hist ON hist.ItemID = t.ItemID
        WHERE t.FirstPre >= '20240101' OR t.FirstRel >= '20240101'"""))
    if d is None or d.empty:
        return
    import pandas as pd
    rows = []
    for k, g in d.groupby("Kind"):
        e = pd.to_numeric(g["EstLead"], errors="coerce")
        h = pd.to_numeric(g["HistLead"], errors="coerce")
        rows.append({"Kind": k, "ProjectItems": len(g),
                     "EstLeadSet": int((e > 0).sum()), "EstMedian": e[e > 0].median(),
                     "HistSet": int(h.notna().sum()), "HistMedian": h.median(), "HistP75": h.quantile(.75),
                     "Hist>=56d": pct(int((h >= 56).sum()), int(h.notna().sum())),
                     "Hist>=90d": pct(int((h >= 90).sum()), int(h.notna().sum()))})
    show(pd.DataFrame(rows))
    print("   (project-items first logged since 2024-01-01; historical = average order→last-receipt days across the item's POs)")


def q7():
    rule(f"Q7. TIMING on {PIDS} — first PO vs first Prerelease vs first Release, per (project, item)")
    d = safe("q7", lambda: df(f"""
        WITH t AS ({ITEM_TYPES}),
        po AS (SELECT pod.ProjectID, pod.ItemID, MIN(poh.PurchaseDate) AS FirstPO
               FROM dbo.vwPurchaseOrderHeader poh JOIN dbo.vwPurchaseOrderDetails pod ON pod.PurchaseOrderID = poh.PurchaseOrderID
               WHERE poh.PurchaseActive = 1 AND pod.ProjectID IN ({ids_sql(PIDS)}) GROUP BY pod.ProjectID, pod.ItemID)
        SELECT t.*, po.FirstPO FROM t LEFT JOIN po ON po.ProjectID = t.ProjectID AND po.ItemID = t.ItemID
        WHERE t.ProjectID IN ({ids_sql(PIDS)})"""))
    if d is None or d.empty:
        return
    import pandas as pd
    for c in ("FirstPre", "FirstRel", "FirstPO"):
        d[c] = pd.to_datetime(d[c], errors="coerce")
    def kind(r):
        return "prerelease only" if r.HasPre and not r.HasRel else ("both" if r.HasPre else "release only")
    d["Kind"] = [kind(r) for r in d.itertuples()]
    for k, g in d.groupby("Kind"):
        has_po = g["FirstPO"].notna()
        print(f"\n   [{k}]  {len(g):,} project-items, {int(has_po.sum()):,} with a PO ({pct(int(has_po.sum()), len(g))})")
        gp = g[has_po]
        first = gp["FirstPre"].where(gp["FirstPre"].notna(), gp["FirstRel"])
        before = int((gp["FirstPO"] < first.dt.normalize()).sum())
        print(f"     PO placed BEFORE any release entry: {before:,}")
        if k == "both":
            between = int(((gp["FirstPO"] >= gp["FirstPre"].dt.normalize()) & (gp["FirstPO"] < gp["FirstRel"].dt.normalize())).sum())
            after = int((gp["FirstPO"] >= gp["FirstRel"].dt.normalize()).sum())
            print(f"     PO between Prerelease and Release (ordered on the prerelease): {between:,}")
            print(f"     PO on/after the Release                                     : {after:,}")
        days = (gp["FirstPO"] - first.dt.normalize()).dt.days
        if len(days):
            print(f"     days from first release entry to first PO: median {days.median():.0f}, p75 {days.quantile(.75):.0f}")


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


def q8():
    import pandas as pd
    rule(f"Q8. DOUBLE-COUNT TEST — logged qty vs BOM required qty, per machine + part, projects {PIDS}")
    try:
        ETO.timeout = PROC_TIMEOUT
    except Exception:
        pass
    frames = []
    for pid in PIDS:
        specs = safe("specs", lambda: df(
            f"SELECT DISTINCT CAST(SpecID AS float) AS SpecID FROM dbo.vwEngProductStructure WHERE ProjectID = {pid}"))
        t0 = time.time()
        for spec in ([] if specs is None else specs["SpecID"].tolist()):
            scopes = safe("scopes", lambda: df(
                f"WITH roots AS (SELECT DISTINCT ParentID FROM dbo.vwEngProductStructure "
                f"  WHERE ProjectID={pid} AND SpecID={spec} AND ParentID NOT IN "
                f"  (SELECT ChildID FROM dbo.vwEngProductStructure WHERE ProjectID={pid} AND SpecID={spec})) "
                f"SELECT s.StructureID FROM dbo.vwEngProductStructure s JOIN roots r ON s.ParentID = r.ParentID "
                f"WHERE s.ProjectID={pid} AND s.SpecID={spec}"))
            for asm in ([] if scopes is None else scopes["StructureID"].tolist()):
                one = safe(f"proc {pid}/{spec:g}/{asm}", lambda: readiness_df(
                    "SET NOCOUNT ON; "
                    f"EXEC dbo.{READINESS_PROC} @intProjectID={pid}, @decSpecID={spec}, "
                    f"@intAssemblyStructureID={int(asm)}, @bitExplodeStandardAssemblies=1, @intWeightMethod=0, "
                    f"@bitAssembliesOnly=0, @bitHideFullyAvailable=0, @intNumberOfLevels=99, @intIndentSpaces=3, "
                    f"@bitAverageWithBOMQty=0"))
                if one is not None and not one.empty:
                    one = one[pd.to_numeric(one["Depth"], errors="coerce").fillna(0) > 0]
                    frames.append(pd.DataFrame({"ProjectID": pid, "SpecID": float(spec),
                                                "ItemCompanyID": one["ItemCompanyID"].astype(str).str.strip(),
                                                "BOMQty": pd.to_numeric(one["TotalRequiredForEntireBOM"], errors="coerce")}))
        print(f"   project {pid}: proc done in {time.time() - t0:.1f}s", flush=True)
    try:
        ETO.timeout = QUERY_TIMEOUT
    except Exception:
        pass
    if not frames:
        return
    bom = pd.concat(frames).groupby(["ProjectID", "SpecID", "ItemCompanyID"], as_index=False)["BOMQty"].max()
    log = safe("log", lambda: df(f"""
        SELECT h.ProjectID, CAST(h.SpecID AS float) AS SpecID, LTRIM(RTRIM(eim.ItemCompanyID)) AS ItemCompanyID,
               SUM(CAST(h.QuantityChange AS float)) AS NetAll,
               SUM(CASE WHEN h.[Type]='Release'    THEN CAST(h.QuantityChange AS float) ELSE 0 END) AS NetRel,
               SUM(CASE WHEN h.[Type]='Prerelease' THEN CAST(h.QuantityChange AS float) ELSE 0 END) AS NetPre,
               MAX(CASE WHEN h.[Type]='Prerelease' THEN 1 ELSE 0 END) AS HasPre,
               MAX(CASE WHEN h.[Type]='Release'    THEN 1 ELSE 0 END) AS HasRel
        FROM dbo.tblBOMReleaseHistory h JOIN dbo.tblEngItemMaster eim ON eim.ItemID = h.ItemID
        WHERE h.ProjectID IN ({ids_sql(PIDS)})
        GROUP BY h.ProjectID, CAST(h.SpecID AS float), LTRIM(RTRIM(eim.ItemCompanyID))"""))
    if log is None or log.empty:
        return
    j = log.merge(bom, on=["ProjectID", "SpecID", "ItemCompanyID"], how="inner")
    print(f"   machine+part groups in both the log and the BOM: {len(j):,} (log groups: {len(log):,})")
    eq = lambda a, b: (a - b).abs() < 1e-6
    for label, mask in (("prerelease only", (j.HasPre == 1) & (j.HasRel == 0)),
                        ("both", (j.HasPre == 1) & (j.HasRel == 1)),
                        ("release only", (j.HasPre == 0) & (j.HasRel == 1))):
        g = j[mask]
        if g.empty:
            continue
        print(f"\n   [{label}] {len(g):,} groups — logged qty equals BOM required qty when counting:")
        print(f"     ALL types (current reports) : {int(eq(g.NetAll, g.BOMQty).sum()):>6,}  ({pct(int(eq(g.NetAll, g.BOMQty).sum()), len(g))})")
        print(f"     Release rows only           : {int(eq(g.NetRel, g.BOMQty).sum()):>6,}  ({pct(int(eq(g.NetRel, g.BOMQty).sum()), len(g))})")
        print(f"     Prerelease rows only        : {int(eq(g.NetPre, g.BOMQty).sum()):>6,}  ({pct(int(eq(g.NetPre, g.BOMQty).sum()), len(g))})")
        print(f"     ALL types EXCEEDS BOM qty   : {int((g.NetAll > g.BOMQty + 1e-6).sum()):>6,}")
        if label == "both":
            show(g[["ProjectID", "SpecID", "ItemCompanyID", "BOMQty", "NetPre", "NetRel", "NetAll"]].head(15), 15)


def main():
    global ETO
    ETO = eto_connect()
    try:
        ETO.timeout = QUERY_TIMEOUT
    except Exception:
        pass
    print(f"console_diag_prerelease — {time.strftime('%Y-%m-%d %H:%M')}  (read-only)  sample projects {PIDS}")
    for f in (q1, q2, q3, q4, q5, q6, q7, q8):
        safe(f.__name__, f)
    ETO.close()
    print("\nDONE — paste everything above.")


if __name__ == "__main__":
    main()
