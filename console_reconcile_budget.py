"""
console_reconcile_budget.py — BREADTH GATE before cutting the dashboard's budget over
to ETO. Read-only. Exercises the real production DAO (console.domain.eto_budget) across
every project and checks two things per project:

  1. Does the HourType-mapped 6-discipline estimate reconcile to ETO's 3-bucket
     (PM==Admin, Mech+Elec+Hyd==Eng, Mfg==Mfg)?
  2. Is there any free-text residue (hours on lines whose HourType isn't in the map /
     is 0)? That's the only thing that can make a project's budget under-count.

If all projects reconcile and residue is ~0, the ETO budget source is safe to go live.
Prints the worst offenders so we can fix a HourType mapping (or handle a project) first.

Run on MACRO-ETO-SVR:
    python console_reconcile_budget.py            # capital projects (190000-499999)
    python console_reconcile_budget.py --all      # every project with an estimate
Then paste the summary back.
"""
import argparse
import sys

from console.domain.hourtype_map import HourTypeDisciplineDAO
from console.domain.eto_budget import EtoBudgetDAO

TOL = 1.0   # hours; deltas within this are "reconciled" (rounding)


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


def store_connect():
    for how in ("console_store.console_connection",
                "console.infra.connections.console_connection"):
        try:
            mod, fn = how.rsplit(".", 1)
            m = __import__(mod, fromlist=[fn])
            return getattr(m, fn)()
        except Exception:
            continue
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--all", action="store_true", help="every project, incl. service (>=500000)")
    args = ap.parse_args()

    eto = eto_connect()
    store = store_connect()

    # map: prefer the seeded store table; fall back to deriving from ETO.
    mp = {}
    if store is not None:
        mp = HourTypeDisciplineDAO(store).load_map()
    if mp:
        print(f"HourType map: {len(mp)} rows from Reporting.tlkpHourTypeDiscipline")
    else:
        mp = HourTypeDisciplineDAO.derive_from_eto(eto)
        print(f"HourType map: {len(mp)} rows derived from ETO tlkpHourTypes (store table empty)")

    cur = eto.cursor()

    # projects with an estimate
    band = "" if args.all else "WHERE ProjectID >= 190000 AND ProjectID < 500000"
    cur.execute(f"SELECT DISTINCT ProjectID FROM dbo.tblSpecHours {band} ORDER BY ProjectID")
    pids = [int(r[0]) for r in cur.fetchall()]
    print(f"projects with an estimate: {len(pids)}  ({'all' if args.all else 'capital band'})")

    # ETO 3-bucket for all
    cur.execute("SELECT ProjectID, ISNULL(EstAdminHours,0), ISNULL(EstEngHours,0), "
                "ISNULL(EstMfgHours,0) FROM dbo.vwProjectActualsVSEstimates")
    eto3 = {int(r[0]): (float(r[1]), float(r[2]), float(r[3])) for r in cur.fetchall()}

    # residue (hours on HourTypes not in the map, or 0) per project — one pass
    cur.execute("SELECT ProjectID, ISNULL(HourType,0), SUM(Hours) FROM dbo.tblSpecHours "
                "GROUP BY ProjectID, HourType")
    residue = {}
    for pid, ht, hrs in cur.fetchall():
        if int(ht) not in mp:
            residue[int(pid)] = residue.get(int(pid), 0.0) + float(hrs or 0)

    dao = EtoBudgetDAO(eto, mp)

    ok = 0
    mism = []          # (pid, dPM, dEng, dMfg, residue)
    no_eto = 0
    total_residue = 0.0
    projects_with_residue = 0

    # batch through the DAO (the real production path)
    for i in range(0, len(pids), 200):
        chunk = pids[i:i + 200]
        budgets = dao.get_current_many(chunk)
        for pid in chunk:
            b = budgets.get(pid)
            dh = (b.discipline_hours if b else {}) or {}
            my_pm = dh.get("Project Management", 0.0)
            my_eng = (dh.get("Mechanical Engineering", 0.0) + dh.get("Hydraulic Engineering", 0.0)
                      + dh.get("Electrical Engineering", 0.0))
            my_mfg = dh.get("Manufacturing", 0.0)
            res = residue.get(pid, 0.0)
            total_residue += res
            if res > TOL:
                projects_with_residue += 1
            if pid not in eto3:
                no_eto += 1
                continue
            a, e, m = eto3[pid]
            d = (my_pm - a, my_eng - e, my_mfg - m)
            if max(abs(x) for x in d) <= TOL:
                ok += 1
            else:
                mism.append((pid, d[0], d[1], d[2], res))

    print("\n" + "=" * 72)
    print("RECONCILIATION SUMMARY")
    print("=" * 72)
    print(f"  projects checked        : {len(pids)}")
    print(f"  reconciled to 3-bucket  : {ok}")
    print(f"  mismatched              : {len(mism)}")
    print(f"  no ETO estimate row     : {no_eto}")
    print(f"  projects with residue   : {projects_with_residue}")
    print(f"  TOTAL residue hours     : {total_residue:,.1f}  (free-text / HourType not in map)")

    if mism:
        mism.sort(key=lambda r: -max(abs(r[1]), abs(r[2]), abs(r[3])))
        print("\n  worst mismatches (ProjectID: dPM / dEng / dMfg | residue):")
        for pid, dpm, deng, dmfg, res in mism[:20]:
            print(f"      {pid}:  {dpm:+.0f} / {deng:+.0f} / {dmfg:+.0f}   | residue {res:,.0f}")

    eto.close()
    if store is not None:
        try: store.close()
        except Exception: pass

    clean = (len(mism) == 0 and total_residue <= TOL)
    print("\n" + ("PASS — ETO budget reconciles across all projects; safe to cut over."
                  if clean else
                  "REVIEW — see mismatches/residue above before cutover."))
    sys.exit(0 if clean else 1)


if __name__ == "__main__":
    main()
