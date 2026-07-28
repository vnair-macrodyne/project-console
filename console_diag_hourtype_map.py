"""
console_diag_hourtype_map.py — the DECISIVE budget-crosswalk probe. Read-only.

Finding so far: tblSpecHours.HourDescription is FREE TEXT (thousands of one-off
estimator strings) — useless as a crosswalk key (28% fell to Other). But every
estimate line also carries tblSpecHours.HourType, a CONTROLLED key (~58 types), and
ETO's tlkpHourTypes already classifies each HourType into Admin/Eng/Mfg. So the right
crosswalk is HourType -> discipline (Admin->PM, Mfg->Manufacturing, Eng->Mech/Elec/Hyd
by the controlled description), anchored to ETO's own department.

This script settles two make-or-break questions:
  A) Does grouping tblSpecHours by HourType reconcile to ETO's 3-bucket per project?
  B) How many estimate hours sit on rows with NO valid HourType (HourType=0 / not in
     tlkpHourTypes)? Those are the only genuinely unclassifiable hours.

It also prints the full HourType -> proposed-discipline map for review.

Run on MACRO-ETO-SVR:
    python console_diag_hourtype_map.py
    python console_diag_hourtype_map.py --project 230219,240033,220154,240148,250250
Then paste the whole output back.
"""
import argparse


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


DISC_ORDER = ["Project Management", "Mechanical Engineering", "Hydraulic Engineering",
              "Electrical Engineering", "Manufacturing", "Other"]


def discipline_for(dept, desc):
    """Proposed HourType -> discipline rule, anchored to ETO's department.
    Admin -> PM ; Mfg -> Manufacturing ; Eng -> Mech/Elec/Hyd by controlled desc.
    NC types (any dept) -> Other."""
    d = (desc or "").lower()
    dep = (dept or "").strip().lower()
    if "non-conformance" in d or "(nc)" in d:
        return "Other"
    if dep.startswith("admin"):
        return "Project Management"
    if dep.startswith("manuf"):
        return "Manufacturing"
    if dep.startswith("eng"):
        if "hydraul" in d:
            return "Hydraulic Engineering"
        if "electr" in d or "program" in d:
            return "Electrical Engineering"
        return "Mechanical Engineering"   # default Eng bucket
    return "Other"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--project", default="230219,240033,220154")
    args = ap.parse_args()
    pids = [int(p) for p in str(args.project).split(",") if p.strip()]

    eto = eto_connect(); cur = eto.cursor()

    # ---- full controlled HourType map + proposed discipline ---------------------
    print("=" * 90)
    print("HourType -> discipline MAP (controlled types from tlkpHourTypes)")
    print("=" * 90)
    cur.execute("SELECT HourType, HourDescription, ISNULL(HourDepartment,'') "
                "FROM dbo.tlkpHourTypes ORDER BY HourDepartment, HourDescription")
    htmap = {}
    print(f"  {'HT':>4}  {'Dept':<16} {'Controlled HourDescription':<40} -> Discipline")
    for ht, desc, dept in cur.fetchall():
        disc = discipline_for(dept, desc)
        htmap[int(ht)] = (desc, dept, disc)
        print(f"  {ht:>4}  {dept[:16]:<16} {str(desc)[:40]:<40} -> {disc}")

    # ---- per-project reconciliation --------------------------------------------
    for pid in pids:
        print("\n" + "=" * 90)
        print(f"PROJECT {pid} — tblSpecHours grouped by HourType")
        print("=" * 90)

        # hours by HourType for this project's estimate
        cur.execute("SELECT ISNULL(HourType,0) AS HourType, SUM(Hours) AS Hrs "
                     "FROM dbo.tblSpecHours WHERE ProjectID = ? GROUP BY HourType", pid)
        by_disc = {d: 0.0 for d in DISC_ORDER}
        no_ht = 0.0            # HourType 0 / null
        bad_ht = 0.0           # HourType not present in tlkpHourTypes
        total = 0.0
        for ht, hrs in cur.fetchall():
            h = float(hrs or 0); total += h; ht = int(ht)
            if ht == 0:
                no_ht += h; continue
            info = htmap.get(ht)
            if info is None:
                bad_ht += h; continue
            by_disc[info[2]] = by_disc.get(info[2], 0.0) + h

        classified = sum(by_disc.values())
        print("  6-discipline EST HOURS (via HourType -> discipline):")
        for d in DISC_ORDER:
            print(f"      {d:<26} {by_disc[d]:>12,.1f}")
        print(f"      {'--- classified':<26} {classified:>12,.1f}")
        print(f"      {'HourType=0 (free-text)':<26} {no_ht:>12,.1f}")
        print(f"      {'HourType not in lookup':<26} {bad_ht:>12,.1f}")
        print(f"      {'TOTAL tblSpecHours':<26} {total:>12,.1f}")

        # ETO 3-bucket reconciliation base
        cur.execute("SELECT ISNULL(EstAdminHours,0), ISNULL(EstEngHours,0), ISNULL(EstMfgHours,0) "
                    "FROM dbo.vwProjectActualsVSEstimates WHERE ProjectID = ?", pid)
        r = cur.fetchone()
        if r:
            admin, eng, mfg = float(r[0]), float(r[1]), float(r[2])
            my_pm = by_disc["Project Management"]
            my_eng = (by_disc["Mechanical Engineering"] + by_disc["Hydraulic Engineering"]
                      + by_disc["Electrical Engineering"])
            my_mfg = by_disc["Manufacturing"]
            print("\n  RECONCILE to ETO 3-bucket (vwProjectActualsVSEstimates):")
            print(f"      PM {my_pm:,.0f}  vs Admin {admin:,.0f}   (Δ {my_pm-admin:+,.0f})")
            print(f"      Mech+Elec+Hyd {my_eng:,.0f}  vs Eng {eng:,.0f}   (Δ {my_eng-eng:+,.0f})")
            print(f"      Mfg {my_mfg:,.0f}  vs Mfg {mfg:,.0f}   (Δ {my_mfg-mfg:+,.0f})")
            print(f"      classified {classified:,.0f} vs ETO total {admin+eng+mfg:,.0f}   "
                  f"(unclassified free-text = {no_ht+bad_ht:,.0f})")

    eto.close()
    print("\nDONE. Paste the whole output back.")


if __name__ == "__main__":
    main()
