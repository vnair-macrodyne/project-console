"""
console_diag_budget_source.py — read-only DISCOVERY to pin the ETO BUDGET source
before we switch the dashboard's budget denominators from the manual store to ETO.

Decision it unblocks (owner, 2026-07-27): pull budgets from ETO, 6-discipline HOURS
via the existing Asset Re-Code crosswalk. The one unknown is the exact ETO view/table
that holds ESTIMATE HOURS by HourType (the discovery log flagged
`vwSpecLaborEstimateByHourType` / `tblSpecHours` as candidates — "confirm at build").
This script confirms it against live data. Nothing is written — pure SELECT.

What it prints:
  1. Existence + full column list of every candidate est-hours-by-HourType object,
     plus a DB-wide search for any column that looks like estimate/budget HOURS.
  2. For the best candidate, a sample for the validation project, crosswalked to the
     6 Project Console disciplines (using the SAME store crosswalk as the actuals),
     so we see the 6-discipline budget-hours vector the dashboard would use.
  3. Reconciliation: that vector's TOTAL vs ETO's 3-bucket estimate hours
     (EstAdminHours+EstEngHours+EstMfgHours on vwProjectActualsVSEstimates) — they
     should agree if the by-HourType source is complete.
  4. The CURRENT manual store budget (vw_Console_BudgetCurrent) for the same project,
     so we can see the ETO-vs-manual divergence we're correcting.

Run on a machine that can reach the ETO SQL Server (same creds as console_sync):
    python console_diag_budget_source.py
    python console_diag_budget_source.py --project 230219

Then paste the WHOLE output back.
"""
import argparse
import sys

# Candidate objects that may hold ESTIMATE HOURS by HourType (per project or per spec).
CANDIDATES = [
    "vwSpecLaborEstimateByHourType",
    "tblSpecHours",
    "vwSpecHours",
    "vwProjectLaborEstimateByHourType",
    "vwProjectLaborActualsVSEstimatesByHourType",   # known — but holds $ (EstLabor); check for hours cols
    "vwProjectActualsVSEstimates",                  # 3-bucket hours (Admin/Eng/Mfg) — the reconciliation base
]

# Column-name shapes that would be an ESTIMATE/BUDGET HOURS measure.
HOURS_EST_HINTS = ["budgethours", "esthours", "estimatehours", "estimatedhours",
                   "totalbudgethours", "budgetlaborhours", "estlaborhours",
                   "plannedhours", "budgethrs", "esthrs"]


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
    """Console Reporting store — only needed to load the crosswalk. Best-effort."""
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


def columns(cur, name):
    cur.execute("SELECT COLUMN_NAME, DATA_TYPE FROM INFORMATION_SCHEMA.COLUMNS "
                "WHERE TABLE_NAME = ? ORDER BY ORDINAL_POSITION", name)
    return [(r[0], r[1]) for r in cur.fetchall()]


def load_crosswalk(store):
    """{HourDescription: Discipline} from the store; {} if unavailable."""
    if store is None:
        return {}
    try:
        cur = store.cursor()
        cur.execute("SELECT HourDescription, Discipline FROM Reporting.tlkpDisciplineCrosswalk")
        return {str(r[0]): str(r[1]) for r in cur.fetchall()}
    except Exception as e:
        print("  (could not load crosswalk from store:", e, ")")
        return {}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--project", default="230219", help="validation ProjectID")
    args = ap.parse_args()
    pid = int(str(args.project).split(",")[0])

    eto = eto_connect()
    cur = eto.cursor()
    store = store_connect()
    xwalk = load_crosswalk(store)

    # 1) Candidate objects — existence + columns, flagging likely hours-estimate cols
    rule("1. CANDIDATE est-hours-by-HourType OBJECTS (columns)")
    present = {}
    for name in CANDIDATES:
        cols = columns(cur, name)
        if not cols:
            print(f"\n  {name}: (not found)")
            continue
        present[name] = [c[0] for c in cols]
        hint = [c for c, _ in cols if any(h in c.lower() for h in HOURS_EST_HINTS)]
        print(f"\n  {name}:")
        for c, dt in cols:
            star = "  <== looks like EST HOURS" if c in hint else ""
            print(f"      {c:<42} {dt}{star}")

    # 2) DB-wide search for any estimate/budget HOURS column (catches a different name)
    rule("2. DB-WIDE: columns that look like ESTIMATE/BUDGET HOURS")
    cur.execute("""
        SELECT TABLE_NAME, COLUMN_NAME, DATA_TYPE
        FROM INFORMATION_SCHEMA.COLUMNS
        WHERE COLUMN_NAME LIKE '%Hour%'
          AND (COLUMN_NAME LIKE '%Budget%' OR COLUMN_NAME LIKE '%Est%' OR COLUMN_NAME LIKE '%Plan%')
        ORDER BY TABLE_NAME, COLUMN_NAME""")
    rows = cur.fetchall()
    for t, c, dt in rows:
        print(f"      {t:<48} {c:<32} {dt}")
    if not rows:
        print("      (none found)")

    # 3) tblSpecHours (per spec) — the most likely true source; sample + crosswalk
    rule(f"3. SAMPLE + 6-DISCIPLINE CROSSWALK for project {pid}")
    print(f"  crosswalk loaded: {len(xwalk)} HourDescription->Discipline rows"
          + ("" if xwalk else "  (EMPTY — store unreachable; discipline roll-up skipped)"))

    # Try the strongest candidate shapes in order. Each block is defensive.
    def try_sample(sql, label):
        try:
            cur.execute(sql)
            hdr = [d[0] for d in cur.description]
            data = cur.fetchall()
            print(f"\n  [{label}] {len(data)} rows; columns: {', '.join(hdr)}")
            for r in data[:15]:
                print("      " + " | ".join("" if v is None else str(v) for v in r))
            return hdr, data
        except Exception as e:
            print(f"\n  [{label}] not usable: {e}")
            return None, None

    # 3a) tblSpecHours joined to hour types (est hours by HourType per project)
    hdr, data = try_sample(
        "SELECT TOP 40 sh.ProjectID, sh.SpecID, sh.HourType, ht.HourDescription, "
        "  sh.BudgetHours AS EstHours "
        "FROM dbo.tblSpecHours sh "
        "LEFT JOIN dbo.tlkpHourTypes ht ON ht.HourType = sh.HourType "
        f"WHERE sh.ProjectID = {pid}", "tblSpecHours.BudgetHours")

    # 3b) fallback: vwSpecLaborEstimateByHourType if it exists
    if data is None and "vwSpecLaborEstimateByHourType" in present:
        cset = present["vwSpecLaborEstimateByHourType"]
        hrs_col = next((c for c in cset if any(h in c.lower() for h in HOURS_EST_HINTS)), None)
        hd_col = "HourDescription" if "HourDescription" in cset else None
        ht_col = "HourType" if "HourType" in cset else None
        sel = ", ".join([c for c in ("ProjectID", ht_col, hd_col, hrs_col) if c])
        if hrs_col:
            hdr, data = try_sample(
                f"SELECT TOP 40 {sel} FROM dbo.vwSpecLaborEstimateByHourType "
                f"WHERE ProjectID = {pid}", "vwSpecLaborEstimateByHourType")

    # Roll the sample up to 6 disciplines via the crosswalk (whichever sample worked)
    if data and xwalk and hdr:
        try:
            hd_i = next(i for i, h in enumerate(hdr) if h.lower() == "hourdescription")
            hr_i = next(i for i, h in enumerate(hdr) if "hour" in h.lower()
                        and any(x in h.lower() for x in ("est", "budget")))
            # re-pull ALL rows (not just 15) for the roll-up
            by_disc = {}
            for r in data:
                hd = r[hd_i]; hrs = r[hr_i]
                disc = xwalk.get(str(hd), "Other")
                try:
                    by_disc[disc] = by_disc.get(disc, 0.0) + float(hrs or 0)
                except (TypeError, ValueError):
                    pass
            print("\n  --> 6-discipline EST HOURS (crosswalked) for this sample:")
            total = 0.0
            for d in ["Project Management", "Mechanical Engineering", "Hydraulic Engineering",
                      "Electrical Engineering", "Manufacturing", "Other"]:
                v = by_disc.get(d, 0.0); total += v
                print(f"      {d:<26} {v:>12,.1f}")
            print(f"      {'TOTAL':<26} {total:>12,.1f}")
            print("  (NOTE: sample capped at 40 rows above — totals here are indicative, "
                  "not the project's full estimate.)")
        except StopIteration:
            print("  (could not locate HourDescription / est-hours columns in the sample header)")

    # 4) Reconciliation base: ETO 3-bucket estimate hours for the project
    rule(f"4. ETO 3-BUCKET estimate hours (reconciliation base) — project {pid}")
    try_sample(
        "SELECT ProjectID, EstAdminHours, EstEngHours, EstMfgHours, "
        "(ISNULL(EstAdminHours,0)+ISNULL(EstEngHours,0)+ISNULL(EstMfgHours,0)) AS EstTotalHours "
        f"FROM dbo.vwProjectActualsVSEstimates WHERE ProjectID = {pid}",
        "vwProjectActualsVSEstimates")

    # 5) Current MANUAL store budget for the same project (the divergence we're fixing)
    rule(f"5. CURRENT MANUAL store budget — project {pid} (for divergence comparison)")
    if store is not None:
        try:
            scur = store.cursor()
            scur.execute("SELECT ProjectID, LabourBudgetHours, PMHours, MechanicalHours, "
                         "ElectricalHours, HydraulicHours, ManufacturingHours, OtherHours, "
                         "MaterialBudget, Source, EffectiveFrom "
                         "FROM Reporting.vw_Console_BudgetCurrent WHERE ProjectID = ?", pid)
            hdr = [d[0] for d in scur.description]
            rows = scur.fetchall()
            if not rows:
                print("      (no manual budget on record for this project)")
            for r in rows:
                print("      " + " | ".join(f"{h}={('' if v is None else v)}" for h, v in zip(hdr, r)))
        except Exception as e:
            print("      (store read failed:", e, ")")
    else:
        print("      (store unreachable from here)")

    eto.close()
    if store is not None:
        try:
            store.close()
        except Exception:
            pass
    print("\nDONE. Paste the whole output back.")


if __name__ == "__main__":
    main()
