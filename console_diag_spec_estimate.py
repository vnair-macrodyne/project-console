"""
console_diag_spec_estimate.py — ROUND 2: confirmed ETO has spec-level (machine) estimates.
Now resolve the details needed to source machine x discipline budgets from ETO.  (2026-08-25)

Confirmed objects (populated): vwSpecLaborEstimateByHourType (pure estimate),
vwSpecLaborActualsVSEstimatesByHourType (budget + actual, per SpecID per HourType),
vwSpecEstimate, vwSpecMaterialEstimateByItemCategory.

This pass answers:
  A. Exact columns of the two spec labour-estimate views (measures: is it HOURS or $?).
  B. The HourType lookup: HourType (int code) -> HourDescription (text) -> our discipline crosswalk.
  C. Sample project: SpecID (machine) x HourType, resolved to HourDescription + Discipline, rolled
     to machine x discipline — TotalBudgetLabor (+ TotalActualLabor). Raw rows shown so we can see
     whether the numbers read as hours or dollars.
  D. Coverage: how many active projects / specs carry a spec-level labour budget.

Run:  python console_diag_spec_estimate.py [projectID]
READ-ONLY. Paste the whole output.
"""
import sys

EST = "vwSpecLaborEstimateByHourType"                 # pure estimate
AVE = "vwSpecLaborActualsVSEstimatesByHourType"       # budget + actual (our primary source)


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


def console_connect():
    try:
        from console.infra.connections import console_connection
        return console_connection()
    except Exception:
        try:
            from console_store import console_connection as cc
            return cc()
        except Exception:
            return None


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


def main():
    proj = sys.argv[1] if len(sys.argv) > 1 else None
    eto = eto_connect(); cur = eto.cursor()

    rule("A. Columns of the two spec labour-estimate views (measures — hours or $?)")
    for v in (EST, AVE):
        print(f"  {v}:")
        for c, t in cols_of(cur, v):
            print(f"     {c:34} {t}")

    rule("B. HourType lookup — HourType(int) -> HourDescription(text)")
    _, htt = rows(cur, "SELECT TABLE_NAME, TABLE_TYPE FROM INFORMATION_SCHEMA.TABLES "
                       "WHERE LOWER(TABLE_NAME) LIKE '%hourtype%' ORDER BY TABLE_NAME")
    for name, tt in htt:
        print(f"  {name:45} {tt}")
    ht_tbl = None
    for name, tt in htt:
        n = name.lower()
        if "hourtype" in n and ("tbl" in n or "lkp" in n or tt == "BASE TABLE"):
            ht_tbl = name; break
    if not ht_tbl and htt:
        ht_tbl = htt[0][0]
    ht_id = ht_desc = None
    if ht_tbl:
        hc = [c for c, _ in cols_of(cur, ht_tbl)]
        print(f"\n  using lookup '{ht_tbl}' cols: {hc}")
        for c in hc:
            cl = c.lower()
            if ht_id is None and cl in ("hourtypeid", "hourtype", "id"):
                ht_id = c
            if ht_desc is None and ("description" in cl or cl in ("hourtypename", "name")):
                ht_desc = c
        print(f"  detected -> id={ht_id}  description={ht_desc}")

    rule("C. Discipline crosswalk (Console store) coverage vs the estimate hourtypes")
    xwalk = {}
    cc = console_connect()
    if cc:
        try:
            xc = cc.cursor()
            xc.execute("SELECT HourDescription, Discipline FROM Reporting.tlkpDisciplineCrosswalk")
            xwalk = {(r[0] or "").strip().lower(): r[1] for r in xc.fetchall()}
            print(f"  crosswalk: {len(xwalk)} HourDescription->discipline mappings")
        except Exception as e:
            print(f"  crosswalk load failed: {e}")
        finally:
            cc.close()
    else:
        print("  Console store not reachable — will show HourDescription without discipline.")

    # pick a sample project (most spec budget) if none passed
    if proj is None:
        _, top = rows(cur, f"SELECT TOP 1 ProjectID FROM [{AVE}] WHERE TotalBudgetLabor > 0 "
                           f"GROUP BY ProjectID ORDER BY SUM(TotalBudgetLabor) DESC")
        proj = str(top[0][0]) if top else None
        print(f"  (sampling project {proj})")

    rule(f"D. Project {proj}: machine x HourType -> discipline, with raw values")
    join_desc = ht_tbl and ht_id and ht_desc
    if join_desc:
        sql = (f"SELECT a.SpecID, a.HourType, h.[{ht_desc}] AS HourDesc, "
               f"CAST(a.TotalBudgetLabor AS decimal(14,2)) AS BudgetLabor, "
               f"CAST(a.TotalActualLabor AS decimal(14,2)) AS ActualLabor "
               f"FROM [{AVE}] a LEFT JOIN [{ht_tbl}] h ON h.[{ht_id}] = a.HourType "
               f"WHERE a.ProjectID = ? AND a.TotalBudgetLabor <> 0 "
               f"ORDER BY a.SpecID, a.HourType")
    else:
        sql = (f"SELECT a.SpecID, a.HourType, CAST(NULL AS varchar(1)) AS HourDesc, "
               f"CAST(a.TotalBudgetLabor AS decimal(14,2)) AS BudgetLabor, "
               f"CAST(a.TotalActualLabor AS decimal(14,2)) AS ActualLabor "
               f"FROM [{AVE}] a WHERE a.ProjectID = ? AND a.TotalBudgetLabor <> 0 "
               f"ORDER BY a.SpecID, a.HourType")
    _, det = rows(cur, sql, proj)
    if not det:
        print(f"  No spec-level labour budget rows for project {proj}.")
        eto.close(); return
    roll = {}
    print(f"  {'Machine':>9} {'HT':>4} {'HourDescription':30} {'Budget':>12} {'Actual':>12} {'Discipline'}")
    for spec, ht, hd, bud, act in det:
        disc = xwalk.get((hd or "").strip().lower(), "(unmapped)") if xwalk else "-"
        mach = int(spec) if spec is not None else None
        print(f"  {str(mach):>9} {str(ht):>4} {str(hd)[:30]:30} {str(bud):>12} {str(act):>12}  {disc}")
        k = (mach, disc)
        b, a = roll.get(k, (0.0, 0.0))
        roll[k] = (b + float(bud or 0), a + float(act or 0))

    rule(f"D2. Rolled up: machine x DISCIPLINE (project {proj})  [Budget / Actual 'Labor']")
    print(f"  {'Machine':>9} {'Discipline':28} {'Budget':>14} {'Actual':>14}")
    tb = ta = 0.0
    for (mach, disc), (b, a) in sorted(roll.items(), key=lambda x: (str(x[0][0]), x[0][1])):
        print(f"  {str(mach):>9} {disc:28} {round(b,1):>14} {round(a,1):>14}")
        tb += b; ta += a
    print(f"  {'':>9} {'TOTAL':28} {round(tb,1):>14} {round(ta,1):>14}")
    print("\n  Interpret 'Budget/Actual Labor': if these look like tens–hundreds they're HOURS; "
          "if thousands+ they're likely $ (labour cost). Compare against what you know for this job.")

    rule("D. Coverage — spec-level labour budget across projects")
    cur.execute(f"SELECT COUNT(DISTINCT ProjectID) FROM [{AVE}] WHERE TotalBudgetLabor > 0")
    print(f"  projects with a spec-level labour budget: {cur.fetchone()[0]}")
    _, cov = rows(cur, f"SELECT TOP 20 ProjectID, COUNT(DISTINCT SpecID) AS Machines, "
                       f"CAST(SUM(TotalBudgetLabor) AS decimal(16,1)) AS Budget "
                       f"FROM [{AVE}] WHERE TotalBudgetLabor > 0 GROUP BY ProjectID "
                       f"ORDER BY Budget DESC")
    print(f"  {'Project':>10} {'Machines':>9} {'Budget(sum)':>14}")
    for p, m, b in cov:
        print(f"  {str(p):>10} {str(m):>9} {str(b):>14}")
    eto.close()


if __name__ == "__main__":
    main()
