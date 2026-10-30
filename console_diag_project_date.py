"""
console_diag_project_date.py -- which tblProjects date column is the "order / award date"?
READ-ONLY. (2026-10-30)

The ETO Project Types sheet carries a Date per project. The new "Hours by Discipline" report uses
tblProjects.PFirst for that Date; this probe checks that against the sheet for 16 known projects by
comparing PFirst / PNext / PLast / PDelivery to the sheet's Date and counting matches per column.

Run from the repo root:  python console_diag_project_date.py   -> paste the output.
"""
import datetime


def eto_connect():
    try:
        from console_store import eto_connection
        return eto_connection()
    except Exception:
        import pyodbc
        from console_config import TENANT
        cs = (f"Driver={{ODBC Driver 17 for SQL Server}};Server={TENANT.eto_server};"
              f"Database={TENANT.eto_database};Trusted_Connection=yes;TrustServerCertificate=yes;")
        return pyodbc.connect(cs, timeout=30)


SHEET = {
    111163: "2019-06-07", 121432: "2019-05-24", 141614: "2019-12-18", 141615: "2020-05-22",
    161665: "2020-06-01", 161672: "2018-12-04", 161674: "2020-01-21", 161679: "2019-08-12",
    161682: "2019-11-18", 161683: "2020-05-04", 161684: "2020-05-04", 161689: "2019-05-31",
    171726: "2019-10-16", 171731: "2019-07-04", 171732: "2019-12-10", 171738: "2019-05-08",
}
COLS = ["PFirst", "PNext", "PLast", "PDelivery"]


def _d(v):
    if isinstance(v, datetime.datetime):
        return v.date().isoformat()
    if isinstance(v, datetime.date):
        return v.isoformat()
    return None


def main():
    eto = eto_connect(); cur = eto.cursor()
    ids = ",".join(str(i) for i in SHEET)
    cur.execute(f"SELECT ProjectID, {', '.join(COLS)} FROM dbo.tblProjects WHERE ProjectID IN ({ids})")
    rows = {r[0]: r for r in cur.fetchall()}
    match = {c: 0 for c in COLS}
    print(f"{'Project':>8}  {'sheet Date':>11}  " + "  ".join(f"{c:>11}" for c in COLS))
    for pid in SHEET:
        r = rows.get(pid)
        if not r:
            print(f"{pid:>8}  {SHEET[pid]:>11}  (not found)"); continue
        vals = {COLS[i]: _d(r[i + 1]) for i in range(len(COLS))}
        for c in COLS:
            if vals[c] == SHEET[pid]:
                match[c] += 1
        print(f"{pid:>8}  {SHEET[pid]:>11}  " + "  ".join(f"{str(vals[c]):>11}" for c in COLS))
    print("\nmatches to the sheet Date (out of %d):" % len(SHEET))
    for c in COLS:
        print(f"  {c}: {match[c]}")
    best = max(match, key=match.get)
    print(f"\n=> best match: {best} ({match[best]}/{len(SHEET)})"
          + ("  -- PFirst confirmed" if best == "PFirst" and match[best] else ""))
    eto.close()


if __name__ == "__main__":
    main()
