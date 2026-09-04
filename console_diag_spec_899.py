"""
console_diag_spec_899.py — what is SpecID 899 (the $4.2M "Management" line on 240088)?  (2026-08-25)

We need to know whether 899 (and any siblings like a 999-style code) is a project-level/overhead
bucket, a template artifact, or a data anomaly — so the machine x discipline budget report treats
it correctly instead of letting it swamp the project.

READ-ONLY. Run:  python console_diag_spec_899.py
"""
AVE = "vwSpecLaborActualsVSEstimatesByHourType"


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
    return [d[0] for d in cur.description], cur.fetchall()


def main():
    eto = eto_connect(); cur = eto.cursor()

    rule("A. Spec master candidates (tables/views with 'spec' + a number/name/description column)")
    _, sm = rows(cur, """
        SELECT c.TABLE_NAME, t.TABLE_TYPE,
               MAX(CASE WHEN LOWER(c.COLUMN_NAME) LIKE '%specnumber%' THEN c.COLUMN_NAME END) AS NumCol,
               MAX(CASE WHEN LOWER(c.COLUMN_NAME) IN ('specid') THEN c.COLUMN_NAME END) AS IdCol,
               MAX(CASE WHEN LOWER(c.COLUMN_NAME) LIKE '%specname%' OR LOWER(c.COLUMN_NAME) LIKE '%specdesc%'
                        OR LOWER(c.COLUMN_NAME) LIKE '%description%' OR LOWER(c.COLUMN_NAME) LIKE '%name%'
                        THEN c.COLUMN_NAME END) AS NameCol
        FROM INFORMATION_SCHEMA.COLUMNS c JOIN INFORMATION_SCHEMA.TABLES t ON t.TABLE_NAME=c.TABLE_NAME
        WHERE LOWER(c.TABLE_NAME) LIKE '%spec%'
        GROUP BY c.TABLE_NAME, t.TABLE_TYPE
        HAVING MAX(CASE WHEN LOWER(c.COLUMN_NAME)='specid' THEN 1 ELSE 0 END)=1
        ORDER BY c.TABLE_NAME""")
    master = None
    for name, tt, numc, idc, namec in sm:
        print(f"  {name:44} {tt:11} id={idc} number={numc} name={namec}")
        if master is None and tt == "BASE TABLE" and namec:
            master = (name, idc, numc, namec)

    rule("B. What carries SpecID 899?  (spec master lookup)")
    if master:
        mname, idc, numc, namec = master
        cols = [idc, namec] + ([numc] if numc else [])
        # try ProjectID too if present
        _, mc = rows(cur, "SELECT COLUMN_NAME FROM INFORMATION_SCHEMA.COLUMNS WHERE TABLE_NAME=?", mname)
        mcols = [c for (c,) in mc]
        extra = [c for c in ("ProjectID", "SpecStatus", "SpecType", "IsTemplate", "Active") if c in mcols]
        sel = ", ".join(f"[{c}]" for c in ([idc, numc, namec] if numc else [idc, namec]) + extra if c)
        try:
            hdr, r = rows(cur, f"SELECT TOP 20 {sel} FROM [{mname}] WHERE [{idc}] = 899")
            print(f"  from {mname} WHERE {idc}=899:")
            print("   " + " | ".join(hdr))
            for row in r:
                print("   " + " | ".join(str(x) for x in row))
            if not r:
                print("  (no row with SpecID=899 in the master — 899 may be a spec NUMBER, not the id)")
                if numc:
                    hdr, r = rows(cur, f"SELECT TOP 20 {sel} FROM [{mname}] WHERE [{numc}] = 899")
                    print(f"  from {mname} WHERE {numc}=899:  ({len(r)} rows)")
                    print("   " + " | ".join(hdr))
                    for row in r[:20]:
                        print("   " + " | ".join(str(x) for x in row))
        except Exception as e:
            print(f"  master lookup error: {e}")
    else:
        print("  No obvious spec master table found — inspect section A list.")

    rule("C. SpecID 899 in the estimate view — recurrence + what hourtypes")
    cur.execute(f"SELECT COUNT(DISTINCT ProjectID) FROM [{AVE}] WHERE SpecID=899")
    print(f"  distinct projects that have SpecID 899: {cur.fetchone()[0]}")
    _, by = rows(cur, f"""
        SELECT a.HourType, h.HourDescription,
               COUNT(DISTINCT a.ProjectID) AS Projects,
               CAST(SUM(a.TotalBudgetLabor) AS decimal(16,0)) AS BudgetSum,
               CAST(AVG(a.TotalBudgetLabor) AS decimal(16,0)) AS BudgetAvg,
               CAST(MAX(a.TotalBudgetLabor) AS decimal(16,0)) AS BudgetMax
        FROM [{AVE}] a LEFT JOIN tlkpHourTypes h ON h.HourType=a.HourType
        WHERE a.SpecID=899 AND a.TotalBudgetLabor<>0
        GROUP BY a.HourType, h.HourDescription ORDER BY BudgetSum DESC""")
    print(f"  {'HT':>4} {'HourDescription':28} {'Projs':>6} {'BudgetSum':>14} {'BudgetAvg':>12} {'BudgetMax':>14}")
    for ht, hd, pj, bs, ba, bm in by:
        print(f"  {str(ht):>4} {str(hd)[:28]:28} {str(pj):>6} {str(bs):>14} {str(ba):>12} {str(bm):>14}")

    rule("D. Other special-looking SpecIDs (>= 500) across the estimate view")
    _, sp = rows(cur, f"""
        SELECT CAST(SpecID AS int) AS Spec, COUNT(DISTINCT ProjectID) AS Projects,
               CAST(SUM(TotalBudgetLabor) AS decimal(16,0)) AS BudgetSum
        FROM [{AVE}] WHERE SpecID >= 500 AND TotalBudgetLabor<>0
        GROUP BY CAST(SpecID AS int) ORDER BY Projects DESC, Spec""")
    print(f"  {'SpecID':>8} {'Projects':>9} {'BudgetSum':>16}")
    for s, pj, bs in sp:
        print(f"  {str(s):>8} {str(pj):>9} {str(bs):>16}")

    rule("E. The 240088 / 899 outlier vs the cross-project norm")
    _, o = rows(cur, f"SELECT a.HourType, h.HourDescription, "
                     f"CAST(a.TotalBudgetLabor AS decimal(16,0)) AS Budget, "
                     f"CAST(a.TotalActualLabor AS decimal(16,0)) AS Actual "
                     f"FROM [{AVE}] a LEFT JOIN tlkpHourTypes h ON h.HourType=a.HourType "
                     f"WHERE a.ProjectID=240088 AND a.SpecID=899")
    print("  240088 / SpecID 899 rows:")
    for ht, hd, b, a in o:
        print(f"    HT {ht} {str(hd)[:26]:26} budget={b}  actual={a}")
    cur.execute(f"SELECT CAST(AVG(TotalBudgetLabor) AS decimal(16,0)), "
                f"CAST(MAX(TotalBudgetLabor) AS decimal(16,0)) FROM [{AVE}] "
                f"WHERE SpecID=899 AND ProjectID<>240088 AND TotalBudgetLabor<>0")
    avg, mx = cur.fetchone()
    print(f"  899 budget on OTHER projects: avg={avg}  max={mx}  "
          f"(if 240088's 4.2M dwarfs these, it's an anomaly, not a real overhead figure)")
    eto.close()


if __name__ == "__main__":
    main()
