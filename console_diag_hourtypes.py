"""
console_diag_hourtypes.py — enumerate ETO's HourType vocabulary + department, with
estimate and actual hours behind each, so we can rebuild tlkpDisciplineCrosswalk to
cover EVERYTHING (budget from tblSpecHours + actuals from vwTimecards), anchored to
ETO's own Admin/Eng/Mfg department. Read-only.

Why: the current crosswalk (39 rows, from the Budgets spreadsheet) misses ~28% of the
estimate hours (they fall to "Other"). ETO's tlkpHourTypes.HourDepartment is the
authoritative 3-bucket; we subdivide Eng into Mechanical/Electrical/Hydraulic by
keyword. This dump is the worklist + materiality to do that and validate it.

Run on MACRO-ETO-SVR:  python console_diag_hourtypes.py
Then paste the whole output back.
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


def store_crosswalk():
    for how in ("console_store.console_connection",
                "console.infra.connections.console_connection"):
        try:
            mod, fn = how.rsplit(".", 1)
            m = __import__(mod, fromlist=[fn])
            c = getattr(m, fn)()
            cur = c.cursor()
            cur.execute("SELECT HourDescription, Discipline FROM Reporting.tlkpDisciplineCrosswalk")
            out = {str(r[0]): str(r[1]) for r in cur.fetchall()}
            c.close()
            return out
        except Exception:
            continue
    return {}


def main():
    eto = eto_connect(); cur = eto.cursor()
    xwalk = store_crosswalk()
    print(f"current crosswalk rows: {len(xwalk)}")

    # 1) distinct department vocabulary
    print("\n" + "=" * 78)
    print("1. tlkpHourTypes.HourDepartment — distinct values (and #hour types each)")
    print("=" * 78)
    try:
        cur.execute("SELECT ISNULL(HourDepartment,'(null)'), COUNT(*) "
                    "FROM dbo.tlkpHourTypes GROUP BY HourDepartment ORDER BY 1")
        for dept, n in cur.fetchall():
            print(f"    {dept:<28} {n}")
    except Exception as e:
        print("   failed:", e)

    # 2) estimate hours by HourDescription (all projects) from tblSpecHours
    est = {}
    try:
        cur.execute("SELECT HourDescription, SUM(Hours) FROM dbo.tblSpecHours "
                    "GROUP BY HourDescription")
        est = {str(r[0]): float(r[1] or 0) for r in cur.fetchall()}
    except Exception as e:
        print("est by description failed:", e)

    # 3) actual hours by HourDescription (all projects) from vwTimecards
    act = {}
    try:
        cur.execute("SELECT HourDescription, SUM(HourTime) FROM dbo.vwTimecards "
                    "GROUP BY HourDescription")
        act = {str(r[0]): float(r[1] or 0) for r in cur.fetchall()}
    except Exception as e:
        print("act by description failed:", e)

    # 4) HourDescription -> HourDepartment from tlkpHourTypes
    dept = {}
    try:
        cur.execute("SELECT HourDescription, MAX(ISNULL(HourDepartment,'')) "
                    "FROM dbo.tlkpHourTypes GROUP BY HourDescription")
        dept = {str(r[0]): str(r[1]) for r in cur.fetchall()}
    except Exception as e:
        print("dept map failed:", e)

    # 5) master table: every HourDescription seen anywhere
    names = set(est) | set(act) | set(dept) | set(xwalk)
    rows = []
    for hd in names:
        rows.append((hd, dept.get(hd, ""), est.get(hd, 0.0), act.get(hd, 0.0),
                     xwalk.get(hd, "*** UNMAPPED ***")))
    rows.sort(key=lambda r: -(r[2] + r[3]))   # by materiality (est+act hours)

    print("\n" + "=" * 78)
    print("2. EVERY HourDescription — ETO dept | est hrs | actual hrs | current mapping")
    print("=" * 78)
    print(f"    {'HourDescription':<36} {'Dept':<16} {'EstHrs':>11} {'ActHrs':>12}  Mapping")
    print("    " + "-" * 92)
    tot_est = tot_act = un_est = un_act = 0.0
    for hd, dp, e, a, mp in rows:
        tot_est += e; tot_act += a
        if mp == "*** UNMAPPED ***":
            un_est += e; un_act += a
        print(f"    {hd[:36]:<36} {dp[:16]:<16} {e:>11,.0f} {a:>12,.0f}  {mp}")

    print("\n" + "=" * 78)
    print("3. COVERAGE")
    print("=" * 78)
    print(f"    total est hrs   : {tot_est:>14,.0f}")
    print(f"    unmapped est hrs: {un_est:>14,.0f}  ({(un_est/tot_est*100 if tot_est else 0):.1f}%)")
    print(f"    total act hrs   : {tot_act:>14,.0f}")
    print(f"    unmapped act hrs: {un_act:>14,.0f}  ({(un_act/tot_act*100 if tot_act else 0):.1f}%)")

    eto.close()
    print("\nDONE. Paste the whole output back.")


if __name__ == "__main__":
    main()
