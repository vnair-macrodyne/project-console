"""
console_diag_ship_date2.py — sample the ETO ship-date CANDIDATES by value (2026-08-11).

Probe #1 showed the project master (tblProjects) has only PDelivery, and it's NULL for the tracked
projects. The real ship date lives at the SALES-ORDER or SPEC (machine) level. This probe pulls the
ACTUAL VALUES of every serious candidate for the tracked projects, side by side, so the authoritative
one is obvious when matched against ship dates you already know.

Candidates sampled:
  • vwProjects.SalesDelivery / .PDelivery         (project-level, from the sales order)
  • tblSpec.BudgetShipRelease, vwSpecActualsVSEstimates.ShipReleaseDate  (per machine/spec, + per-project MIN/MAX)
  • tblSpecDelivery / vwSpecDelivery              (dedicated spec-delivery table)
  • vwProcessScheduleHeaderDetailed.FinalRequiredDate
  • the Console overlay's PlannedShipDate         (what we serve today — the target to match)

READ-ONLY. Run:  python console_diag_ship_date2.py   → paste the whole output.
"""


def eto_connect():
    try:
        from console_store import eto_connection
        return eto_connection()
    except Exception:
        import os
        import pyodbc
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
            from console_store import console_connection
            return console_connection()
        except Exception as e:
            print(f"  [note] no console store connection ({type(e).__name__}: {e})")
            return None


def tracked_ids(max_n=10):
    c = console_connect()
    if not c:
        return [230219, 210065, 220154]
    try:
        cur = c.cursor()
        cur.execute("SELECT DISTINCT ProjectID FROM Reporting.vw_Console_BudgetCurrent "
                    "ORDER BY ProjectID")
        ids = [int(r[0]) for r in cur.fetchall()][:max_n]
        c.close()
        return ids
    except Exception as e:
        print(f"  [note] tracked ids failed ({type(e).__name__}: {e})")
        return [230219, 210065, 220154]


def rule(t):
    print("\n" + "=" * 78 + f"\n{t}\n" + "=" * 78)


def run(cur, label, sql, params=(), max_rows=60):
    print("\n" + "-" * 78 + f"\n{label}\n" + "-" * 78)
    try:
        cur.execute(sql, params)
        while cur.description is None and cur.nextset():
            pass
        if cur.description is None:
            print("  (no result set)")
            return
        cols = [d[0] for d in cur.description]
        rows = cur.fetchall()
        print("  " + " | ".join(cols))
        for r in rows[:max_rows]:
            print("  " + " | ".join("" if v is None else str(v) for v in r))
        if len(rows) > max_rows:
            print(f"  ... (+{len(rows) - max_rows} more)")
        if not rows:
            print("  (0 rows)")
    except Exception as e:
        print(f"  [ERROR] {type(e).__name__}: {e}")


def columns_of(cur, name):
    cur.execute("SELECT COLUMN_NAME, DATA_TYPE FROM INFORMATION_SCHEMA.COLUMNS "
                "WHERE TABLE_NAME = ? ORDER BY ORDINAL_POSITION", (name,))
    return [(r[0], r[1]) for r in cur.fetchall()]


def has_col(cur, table, col):
    return any(n.lower() == col.lower() for n, _ in columns_of(cur, table))


def main():
    conn = eto_connect()
    cur = conn.cursor()
    ids = tracked_ids()
    idl = ",".join(str(i) for i in ids) if ids else "230219"
    sample = ids[0] if ids else 230219
    print(f"Tracked projects sampled: {idl}")
    try:
        # ── A. project-level sales-order delivery date ───────────────────────────
        rule("A. vwProjects — project-level delivery / sales-delivery (the top candidate)")
        run(cur, "A1. PDelivery vs SalesDelivery per tracked project",
            "SELECT ProjectID, PStatus, PDelivery, SalesDelivery "
            f"FROM dbo.vwProjects WHERE ProjectID IN ({idl}) ORDER BY ProjectID")

        # ── B. spec (machine) level ship-release dates ───────────────────────────
        rule("B. SPEC-LEVEL SHIP DATES (a project has 1..n specs / machines)")
        print("\n  vwSpec columns (find the ProjectID + date keys):")
        for n, t in columns_of(cur, "vwSpec"):
            star = "  ★" if any(h in n.lower() for h in
                                ("ship", "deliver", "budget", "project", "spec")) else ""
            print(f"    {n} : {t}{star}")
        run(cur, "B1. per-spec BudgetShipRelease for tracked projects",
            "SELECT ProjectID, SpecID, BudgetShipRelease FROM dbo.vwSpec "
            f"WHERE ProjectID IN ({idl}) ORDER BY ProjectID, SpecID")
        run(cur, "B2. per-project MIN/MAX/COUNT of BudgetShipRelease (roll-up candidate)",
            "SELECT ProjectID, COUNT(*) AS specs, MIN(BudgetShipRelease) AS min_ship, "
            "MAX(BudgetShipRelease) AS max_ship FROM dbo.vwSpec "
            f"WHERE ProjectID IN ({idl}) GROUP BY ProjectID ORDER BY ProjectID")
        run(cur, "B3. vwSpecActualsVSEstimates.ShipReleaseDate per tracked project",
            "SELECT ProjectID, SpecID, ShipReleaseDate FROM dbo.vwSpecActualsVSEstimates "
            f"WHERE ProjectID IN ({idl}) ORDER BY ProjectID, SpecID")

        # ── C. dedicated spec-delivery table ─────────────────────────────────────
        rule("C. tblSpecDelivery / vwSpecDelivery (dedicated delivery table)")
        print("\n  vwSpecDelivery columns:")
        for n, t in columns_of(cur, "vwSpecDelivery"):
            print(f"    {n} : {t}")
        run(cur, "C1. vwSpecDelivery sample (scoped to tracked projects if it carries ProjectID)",
            f"SELECT TOP 40 * FROM dbo.vwSpecDelivery WHERE ProjectID IN ({idl})"
            if has_col(cur, "vwSpecDelivery", "ProjectID")
            else "SELECT TOP 20 * FROM dbo.vwSpecDelivery")

        # ── D. process schedule final-required date ──────────────────────────────
        rule("D. vwProcessScheduleHeaderDetailed.FinalRequiredDate")
        pshd = columns_of(cur, "vwProcessScheduleHeaderDetailed")
        print("\n  vwProcessScheduleHeaderDetailed columns:")
        for n, t in pshd:
            print(f"    {n} : {t}")
        if any(n.lower() == "projectid" for n, _ in pshd):
            run(cur, "D1. FinalRequiredDate per tracked project",
                "SELECT ProjectID, FinalRequiredDate FROM dbo.vwProcessScheduleHeaderDetailed "
                f"WHERE ProjectID IN ({idl}) ORDER BY ProjectID")
        else:
            run(cur, "D1. sample (no ProjectID column — showing shape)",
                "SELECT TOP 15 * FROM dbo.vwProcessScheduleHeaderDetailed")

        # ── E. full project row for one project (catch a non-obvious field) ──────
        rule(f"E. vwProjects full row — project {sample}")
        run(cur, "E1. all vwProjects fields for one project",
            f"SELECT * FROM dbo.vwProjects WHERE ProjectID = {sample}", max_rows=3)

        # ── F. the value to MATCH — Console overlay's PlannedShipDate ─────────────
        rule("F. TARGET — Console overlay ship dates (what we serve today; match a column above)")
        c2 = console_connect()
        if c2:
            cur2 = c2.cursor()
            run(cur2, "F1. overlay PO / Customer-Agreed / Planned ship dates",
                "SELECT ProjectID, POShipDate, CustAgreedShipDate, PlannedShipDate "
                f"FROM Reporting.vw_Console_ManualOverlay WHERE ProjectID IN ({idl}) "
                "ORDER BY ProjectID")
            c2.close()
    finally:
        conn.close()
    print("\nDone. Paste the whole output.\n"
          "  Match the F1 PlannedShipDate (and Customer-Agreed) values to A1 / B / C / D above —\n"
          "  whichever column reproduces the ship dates you know is the one to wire.\n"
          "  Likely shapes: a single project date (vwProjects.SalesDelivery) → use directly; a\n"
          "  per-spec date (BudgetShipRelease / ShipReleaseDate) → roll up per project (MAX = the\n"
          "  last machine to ship, usually the project ship date). Tell me the winner + roll-up rule.")


if __name__ == "__main__":
    main()
