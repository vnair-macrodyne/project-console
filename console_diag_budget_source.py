"""
console_diag_budget_source.py (v2) — confirm tblSpecHours as the ETO BUDGET-HOURS
source and reconcile the 6-discipline crosswalk before we wire budgets from ETO.

v1 found the source: dbo.tblSpecHours (ProjectID, SpecID, HourDescription, Hours,
HourType, ChangeOrderID, ...). The estimate-hours column is `Hours` (v1 guessed
`BudgetHours` and errored). This version:
  1. Sums tblSpecHours.Hours for the project — all rows, and split by change-order,
     so we can see how COs affect the total.
  2. Rolls Hours up to the 6 disciplines via the store crosswalk (HourDescription).
  3. Reconciles that total against ETO's 3-bucket estimate (vwProjectActualsVSEstimates
     = 8,523 for 230219) and the current manual store budget (8,429).
  4. Reconciles the $ side: labour budget $ and material budget $ from ETO.

Read-only. Run on MACRO-ETO-SVR:
    python console_diag_budget_source.py
    python console_diag_budget_source.py --project 230219,240033,220154
Then paste the whole output back.
"""
import argparse
import sys

DISC_ORDER = ["Project Management", "Mechanical Engineering", "Hydraulic Engineering",
              "Electrical Engineering", "Manufacturing", "Other"]


def eto_connect():
    try:
        from console_store import eto_connection
        return eto_connection()
    except Exception as e1:
        try:
            import os, pyodbc
            from console_config import TENANT
            cs = (f"Driver={{ODBC Driver 17 for SQL Server}};Server={TENANT.eto_server};"
                  f"Database={TENANT.eto_database};")
            cs += ("Trusted_Connection=yes;" if TENANT.use_windows_auth
                   else f"UID={os.environ.get('ETO_USER')};PWD={os.environ.get('ETO_PWD')};")
            return pyodbc.connect(cs)
        except Exception as e2:
            print(f"COULD NOT CONNECT TO ETO.\n  via console_store: {e1}\n  via pyodbc: {e2}")
            sys.exit(1)


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


def rule(t):
    print("\n" + "=" * 78); print(t); print("=" * 78)


def load_crosswalk(store):
    if store is None:
        return {}
    try:
        cur = store.cursor()
        cur.execute("SELECT HourDescription, Discipline FROM Reporting.tlkpDisciplineCrosswalk")
        return {str(r[0]): str(r[1]) for r in cur.fetchall()}
    except Exception as e:
        print("  (could not load crosswalk:", e, ")")
        return {}


def one(cur, sql):
    cur.execute(sql)
    r = cur.fetchone()
    return r[0] if r else None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--project", default="230219")
    args = ap.parse_args()
    pids = [int(p) for p in str(args.project).split(",") if p.strip()]

    eto = eto_connect(); cur = eto.cursor()
    store = store_connect(); xwalk = load_crosswalk(store)
    print(f"crosswalk: {len(xwalk)} HourDescription->Discipline rows"
          + ("" if xwalk else "  (EMPTY — store unreachable; roll-up will fall to Other)"))

    for pid in pids:
        rule(f"PROJECT {pid}")

        # --- change-order breakdown of tblSpecHours -----------------------------
        try:
            cur.execute(f"""
                SELECT
                  COUNT(*) AS rows_all,
                  SUM(Hours) AS hours_all,
                  SUM(CASE WHEN ISNULL(ChangeOrderID,0)=0 THEN Hours ELSE 0 END) AS hours_base,
                  SUM(CASE WHEN ISNULL(ChangeOrderID,0)>0 THEN Hours ELSE 0 END) AS hours_co,
                  COUNT(DISTINCT NULLIF(ChangeOrderID,0)) AS distinct_cos
                FROM dbo.tblSpecHours WHERE ProjectID = {pid}""")
            r = cur.fetchone()
            print(f"  tblSpecHours: rows={r[0]}  Hours(all)={_n(r[1])}  "
                  f"Hours(base CO=0)={_n(r[2])}  Hours(change-orders)={_n(r[3])}  "
                  f"distinct COs={r[4]}")
        except Exception as e:
            print("  tblSpecHours CO breakdown failed:", e)

        # --- Hours by HourDescription -> crosswalk -> 6 disciplines --------------
        for label, where in (("ALL rows", ""),
                             ("BASE only (ChangeOrderID=0/NULL)", "AND ISNULL(ChangeOrderID,0)=0")):
            try:
                cur.execute(f"""
                    SELECT HourDescription, SUM(Hours) AS Hrs
                    FROM dbo.tblSpecHours
                    WHERE ProjectID = {pid} {where}
                    GROUP BY HourDescription ORDER BY SUM(Hours) DESC""")
                rows = cur.fetchall()
                by_disc, unmapped = {}, []
                for hd, hrs in rows:
                    disc = xwalk.get(str(hd))
                    if disc is None:
                        unmapped.append((str(hd), float(hrs or 0))); disc = "Other"
                    by_disc[disc] = by_disc.get(disc, 0.0) + float(hrs or 0)
                total = sum(by_disc.values())
                print(f"\n  6-discipline EST HOURS — {label}:")
                for d in DISC_ORDER:
                    print(f"      {d:<26} {by_disc.get(d,0.0):>12,.1f}")
                print(f"      {'TOTAL':<26} {total:>12,.1f}")
                if unmapped:
                    print("      unmapped HourDescriptions (fell to Other): "
                          + ", ".join(f"{h}={v:,.0f}" for h, v in unmapped[:12]))
            except Exception as e:
                print(f"  roll-up ({label}) failed:", e)

        # --- ETO reconciliation bases ------------------------------------------
        try:
            cur.execute(f"""SELECT EstAdminHours, EstEngHours, EstMfgHours,
                            (ISNULL(EstAdminHours,0)+ISNULL(EstEngHours,0)+ISNULL(EstMfgHours,0)),
                            EstTotalMaterials, ExtendedEstimate,
                            (ISNULL(AdminEstimateExtended,0)+ISNULL(EngEstimateExtended,0)+ISNULL(MfgEstimateExtended,0))
                            FROM dbo.vwProjectActualsVSEstimates WHERE ProjectID = {pid}""")
            r = cur.fetchone()
            if r:
                print(f"\n  ETO vwProjectActualsVSEstimates: Admin/Eng/Mfg hrs = "
                      f"{_n(r[0])}/{_n(r[1])}/{_n(r[2])}  TOTAL={_n(r[3])}")
                print(f"      EstTotalMaterials=${_n(r[4])}  ExtendedEstimate=${_n(r[5])}  "
                      f"LabourEstimate$(Admin+Eng+Mfg extended)=${_n(r[6])}")
        except Exception as e:
            print("  vwProjectActualsVSEstimates read failed:", e)

        try:
            lab = one(cur, f"SELECT SUM(Extended) FROM dbo.vwSpecLaborEstimateByHourType "
                           f"WHERE ProjectID = {pid}")
            print(f"      vwSpecLaborEstimateByHourType SUM(Extended) labour$ = ${_n(lab)}")
        except Exception as e:
            print("  vwSpecLaborEstimateByHourType read failed:", e)

        # --- current manual store budget (divergence) --------------------------
        if store is not None:
            try:
                sc = store.cursor()
                sc.execute("SELECT LabourBudgetHours, PMHours, MechanicalHours, ElectricalHours, "
                           "HydraulicHours, ManufacturingHours, OtherHours, MaterialBudget "
                           "FROM Reporting.vw_Console_BudgetCurrent WHERE ProjectID = ?", pid)
                r = sc.fetchone()
                if r:
                    print(f"\n  MANUAL store budget: total={_n(r[0])}  PM={_n(r[1])} Mech={_n(r[2])} "
                          f"Elec={_n(r[3])} Hyd={_n(r[4])} Mfg={_n(r[5])} Other={_n(r[6])}  "
                          f"Material=${_n(r[7])}")
                else:
                    print("\n  MANUAL store budget: (none on record)")
            except Exception as e:
                print("  store budget read failed:", e)

    eto.close()
    if store is not None:
        try: store.close()
        except Exception: pass
    print("\nDONE. Paste the whole output back.")


def _n(v):
    try:
        return f"{float(v):,.1f}"
    except (TypeError, ValueError):
        return "None"


if __name__ == "__main__":
    main()
