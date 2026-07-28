"""
console_reconcile_budget.py — BREADTH GATE before cutting the dashboard's budget over
to ETO. Read-only. Exercises the real production DAO (console.domain.eto_budget, which
anchors 3-bucket totals to vwProjectActualsVSEstimates and uses tblSpecHours only to
split Eng into Mech/Elec/Hyd) across every project and checks:

  1. Does the DAO's 6-discipline budget reconcile to ETO's 3-bucket
     (PM==Admin, Mech+Elec+Hyd==Eng, Mfg==Mfg)?  With view-anchoring this passes by
     construction — a failure means a data surprise worth seeing.
  2. Which projects were CORRECTED by view-anchoring (their tblSpecHours line-detail did
     not sum to the rolled-up estimate) — informational, so nothing is hidden.
  3. Which projects hit the Eng-split FALLBACK (Eng hours but no Eng line-detail -> whole
     Eng defaulted to Mechanical).

Run on MACRO-ETO-SVR:
    python console_reconcile_budget.py            # capital projects (190000-499999)
    python console_reconcile_budget.py --all      # every project with an estimate
Then paste the summary back.
"""
import argparse
import sys

from console.domain.hourtype_map import HourTypeDisciplineDAO
from console.domain.eto_budget import EtoBudgetDAO

TOL = 1.0   # hours


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

    mp = {}
    if store is not None:
        mp = HourTypeDisciplineDAO(store).load_map()
    if mp:
        print(f"HourType map: {len(mp)} rows from Reporting.tlkpHourTypeDiscipline")
    else:
        mp = HourTypeDisciplineDAO.derive_from_eto(eto)
        print(f"HourType map: {len(mp)} rows derived from ETO tlkpHourTypes (store table empty)")

    cur = eto.cursor()
    band = "" if args.all else "WHERE ProjectID >= 190000 AND ProjectID < 500000"
    cur.execute(f"SELECT DISTINCT ProjectID FROM dbo.tblSpecHours {band} ORDER BY ProjectID")
    pids = [int(r[0]) for r in cur.fetchall()]
    print(f"projects with an estimate: {len(pids)}  ({'all' if args.all else 'capital band'})")

    cur.execute("SELECT ProjectID, ISNULL(EstAdminHours,0), ISNULL(EstEngHours,0), "
                "ISNULL(EstMfgHours,0) FROM dbo.vwProjectActualsVSEstimates")
    eto3 = {int(r[0]): (float(r[1]), float(r[2]), float(r[3])) for r in cur.fetchall()}

    # raw tblSpecHours mapped 3-bucket (to detect which projects view-anchoring corrects)
    raw = {}   # pid -> [pm, eng, mfg, residue]
    cur.execute("SELECT ProjectID, ISNULL(HourType,0), SUM(Hours) FROM dbo.tblSpecHours "
                "GROUP BY ProjectID, HourType")
    for pid, ht, hrs in cur.fetchall():
        pid = int(pid); h = float(hrs or 0)
        slot = raw.setdefault(pid, [0.0, 0.0, 0.0, 0.0])
        d = mp.get(int(ht))
        if d == "Project Management":
            slot[0] += h
        elif d in ("Mechanical Engineering", "Hydraulic Engineering", "Electrical Engineering"):
            slot[1] += h
        elif d == "Manufacturing":
            slot[2] += h
        elif d == "Other":
            pass                      # NC — sits inside a view bucket; ignore for the raw compare
        else:
            slot[3] += h              # residue (unmapped / HourType 0)

    dao = EtoBudgetDAO(eto, mp)

    reconciled = 0
    failed = []          # (pid, dPM, dEng, dMfg) — should be empty with view-anchoring
    corrected = []       # (pid, raw_total, view_total, delta) — line-detail != rolled-up estimate
    fallback = []        # (pid, eng) — Eng hours but no Eng line-detail
    for i in range(0, len(pids), 200):
        chunk = pids[i:i + 200]
        budgets = dao.get_current_many(chunk)
        for pid in chunk:
            b = budgets.get(pid)
            dh = (b.discipline_hours if b else {}) or {}
            pm = dh.get("Project Management", 0.0)
            eng = (dh.get("Mechanical Engineering", 0.0) + dh.get("Hydraulic Engineering", 0.0)
                   + dh.get("Electrical Engineering", 0.0))
            mfg = dh.get("Manufacturing", 0.0)
            a, e, m = eto3.get(pid, (0.0, 0.0, 0.0))
            if max(abs(pm - a), abs(eng - e), abs(mfg - m)) <= TOL:
                reconciled += 1
            else:
                failed.append((pid, pm - a, eng - e, mfg - m))
            # correction reporting (raw line-detail vs rolled-up estimate)
            r = raw.get(pid, [0.0, 0.0, 0.0, 0.0])
            raw_tot = r[0] + r[1] + r[2] + r[3]
            view_tot = a + e + m
            if abs(raw_tot - view_tot) > TOL:
                corrected.append((pid, raw_tot, view_tot, raw_tot - view_tot))
            if e > TOL and r[1] <= TOL:
                fallback.append((pid, e))

    print("\n" + "=" * 72)
    print("RECONCILIATION SUMMARY (view-anchored)")
    print("=" * 72)
    print(f"  projects checked          : {len(pids)}")
    print(f"  reconciled to 3-bucket    : {reconciled}")
    print(f"  FAILED reconciliation     : {len(failed)}   (expect 0)")
    print(f"  view-anchor CORRECTED     : {len(corrected)}   (line-detail didn't sum to estimate)")
    print(f"  Eng-split FALLBACK        : {len(fallback)}   (Eng hours, no Eng line-detail)")

    if failed:
        print("\n  FAILURES (ProjectID: dPM / dEng / dMfg):")
        for pid, dpm, deng, dmfg in sorted(failed, key=lambda r: -max(abs(r[1]), abs(r[2]), abs(r[3])))[:20]:
            print(f"      {pid}:  {dpm:+.0f} / {deng:+.0f} / {dmfg:+.0f}")
    if corrected:
        print("\n  corrected by view-anchoring (ProjectID: line-detail -> estimate, delta):")
        for pid, rt, vt, d in sorted(corrected, key=lambda r: -abs(r[3]))[:20]:
            print(f"      {pid}:  {rt:,.0f} -> {vt:,.0f}   ({d:+,.0f})")
    if fallback:
        print("\n  Eng-split fallback (ProjectID: Eng hrs defaulted to Mechanical):")
        for pid, e in sorted(fallback, key=lambda r: -r[1])[:20]:
            print(f"      {pid}:  {e:,.0f}")

    eto.close()
    if store is not None:
        try: store.close()
        except Exception: pass

    print("\n" + ("PASS — every project reconciles to ETO's estimate; safe to cut over."
                  if not failed else
                  "REVIEW — unexpected reconciliation failures above."))
    sys.exit(0 if not failed else 1)


if __name__ == "__main__":
    main()
