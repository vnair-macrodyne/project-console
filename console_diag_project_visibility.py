"""
console_diag_project_visibility.py -- why isn't a project in the console's project selector?
READ-ONLY. (2026-10-30)

Replicates LiveQueryService.list_projects exactly. A project shows in the left-panel selector iff
ALL THREE hold:
  1. it has a banked budget in Reporting.vw_Console_BudgetCurrent, AND
  2. it is NOT in Reporting.tblConsoleProjectExclusion (soft "removed from console"), AND
  3. if Reporting.tblActiveProject is seeded (non-empty), the project is ALSO in it
     (the open-projects list from the Exec Dashboard worksheet).

Run:  python console_diag_project_visibility.py [ProjectID]    (default 250299)
"""
import sys


def _console():
    from console.infra.connections import console_connection
    return console_connection()


def _eto():
    from console.infra.connections import eto_connection
    return eto_connection()


def scalar(cur, sql, *args):
    cur.execute(sql, args) if args else cur.execute(sql)
    r = cur.fetchone()
    return r[0] if r else None


def main():
    pid = int(sys.argv[1]) if len(sys.argv) > 1 else 250299
    print(f"=== visibility check for project {pid} ===\n")

    # ETO existence / status
    try:
        ec = _eto().cursor()
        ec.execute("SELECT DisplayName, PStatus, PActive, PFirst FROM dbo.tblProjects WHERE ProjectID = ?", pid)
        r = ec.fetchone()
        if r:
            print(f"ETO tblProjects: FOUND  name={r[0]!r}  PStatus={r[1]!r}  PActive={r[2]}  PFirst={r[3]}")
        else:
            print("ETO tblProjects: NOT FOUND (project number doesn't exist in ETO)")
    except Exception as e:
        print("ETO lookup ERROR:", e)

    cc = _console().cursor()

    # Gate 1 — banked budget
    try:
        n_bud = scalar(cc, "SELECT COUNT(*) FROM Reporting.vw_Console_BudgetCurrent WHERE ProjectID = ?", pid) or 0
    except Exception as e:
        n_bud = None; print("budget view ERROR:", e)
    g1 = (n_bud or 0) > 0
    print(f"\nGATE 1  banked budget (vw_Console_BudgetCurrent): {'PASS' if g1 else 'FAIL'}  (rows={n_bud})")
    try:
        cc.execute("SELECT TOP 1 * FROM Reporting.tblProjectBudget WHERE ProjectID = ? "
                   "ORDER BY 1 DESC", pid)
        row = cc.fetchone()
        if row:
            cols = [d[0] for d in cc.description]
            keep = {k: v for k, v in zip(cols, row)
                    if k.lower() in ("projectid", "version", "versionno", "enteredby", "entereddate",
                                     "createddate", "asof", "iscurrent", "active", "yearweekkey")}
            print("        latest tblProjectBudget row (key fields):", keep)
        else:
            print("        tblProjectBudget: NO rows for this project (budget was never banked)")
    except Exception as e:
        print("        tblProjectBudget probe note:", e)

    # Gate 2 — exclusion
    try:
        n_excl = scalar(cc, "SELECT COUNT(*) FROM Reporting.tblConsoleProjectExclusion WHERE ProjectID = ?", pid) or 0
    except Exception as e:
        n_excl = None; print("exclusion ERROR:", e)
    g2 = (n_excl or 0) == 0
    print(f"\nGATE 2  not excluded (tblConsoleProjectExclusion): {'PASS' if g2 else 'FAIL'}  (rows={n_excl})")

    # Gate 3 — active list
    try:
        n_active_total = scalar(cc, "SELECT COUNT(*) FROM Reporting.tblActiveProject") or 0
        n_active_me = scalar(cc, "SELECT COUNT(*) FROM Reporting.tblActiveProject WHERE ProjectID = ?", pid) or 0
    except Exception as e:
        n_active_total = n_active_me = None; print("active-list ERROR:", e)
    seeded = (n_active_total or 0) > 0
    g3 = (not seeded) or ((n_active_me or 0) > 0)
    print(f"\nGATE 3  active-projects list (tblActiveProject): {'PASS' if g3 else 'FAIL'}")
    print(f"        list seeded? {seeded} (total active={n_active_total})   this project present? {(n_active_me or 0) > 0}")

    print("\n=== VERDICT ===")
    if g1 and g2 and g3:
        print(f"  Project {pid} SHOULD appear in the selector. If it doesn't, suspect a stale app cache/"
              "restart, or a different store (staging vs prod) than you're viewing.")
    else:
        why = []
        if not g1:
            why.append("no banked budget (vw_Console_BudgetCurrent) -> run PM 'Add to Console' / bank its budget")
        if not g2:
            why.append("it's on the exclusion list -> PM 'Add to Console' clears it")
        if not g3:
            why.append("it's not on the Active Project list (tblActiveProject) -> add it to the Exec "
                       "Dashboard worksheet + re-run console_seed_active_project.py (or insert the row)")
        print(f"  Project {pid} is HIDDEN because:")
        for w in why:
            print("   -", w)


if __name__ == "__main__":
    main()
