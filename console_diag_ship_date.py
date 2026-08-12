"""
console_diag_ship_date.py — find ETO's planned / scheduled ship date for a project (2026-08-11).

GOAL: the Plan page should read the Planned Ship Date FROM ETO if ETO holds one, so PMs don't
retype it (Reporting owns only the per-discipline % complete). The Carpedia reverse-engineering
treated all three ship dates as MANUAL because the workbook maintained them by hand — but ETO may
well carry a project ship / required / scheduled / promised date we can source instead. This probe
surfaces every candidate date field on the project master (and related schedule/milestone tables)
with SAMPLE VALUES for tracked projects, so we can pick the authoritative column.

READ-ONLY. Run:  python console_diag_ship_date.py   → paste the whole output.
"""

# Column-name hints that would mark a date as a likely ship / delivery / due date.
DATE_TYPES = ("date", "datetime", "datetime2", "smalldatetime")
SHIP_HINTS = ("ship", "deliver", "due", "required", "promis", "schedul", "complet",
              "finish", "end", "target", "planned", "agreed", "custagreed", "eta")


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


def tracked_ids(max_n=8):
    """A few tracked projects to show sample date values against (so a column is recognisable)."""
    try:
        from console.infra.connections import console_connection
        c = console_connection()
        cur = c.cursor()
        cur.execute("SELECT DISTINCT ProjectID FROM Reporting.vw_Console_BudgetCurrent "
                    "ORDER BY ProjectID")
        ids = [int(r[0]) for r in cur.fetchall()][:max_n]
        c.close()
        return ids
    except Exception as e:
        print(f"  [note] no tracked ids ({type(e).__name__}: {e})")
        return []


def rule(t):
    print("\n" + "=" * 78 + f"\n{t}\n" + "=" * 78)


def run(cur, label, sql, params=(), max_rows=40):
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


def date_columns(cur, table):
    """(name, type) for every date-typed column on a table/view, in ordinal order."""
    cur.execute("SELECT COLUMN_NAME, DATA_TYPE FROM INFORMATION_SCHEMA.COLUMNS "
                "WHERE TABLE_NAME = ? ORDER BY ORDINAL_POSITION", (table,))
    return [(n, t) for n, t in cur.fetchall() if t and t.lower() in DATE_TYPES]


def main():
    conn = eto_connect()
    cur = conn.cursor()
    ids = tracked_ids()
    sample = ids[0] if ids else 230219
    id_list = ",".join(str(i) for i in ids) if ids else str(sample)
    try:
        # ── A. all DATE columns on the project master, ship-ish ones flagged ──────
        rule("A. DATE COLUMNS ON tblProjects  (★ = name looks like a ship / due / delivery date)")
        proj_dates = date_columns(cur, "tblProjects")
        if not proj_dates:
            print("  (tblProjects has no date columns? — check the name in A0 below)")
        for n, t in proj_dates:
            star = "  ★" if any(h in n.lower() for h in SHIP_HINTS) else ""
            print(f"    {n} : {t}{star}")
        run(cur, "A0. project-master objects (in case it isn't literally 'tblProjects')",
            "SELECT TABLE_NAME, TABLE_TYPE FROM INFORMATION_SCHEMA.TABLES "
            "WHERE TABLE_NAME LIKE '%Project%' ORDER BY TABLE_NAME", max_rows=60)

        # ── B. SAMPLE VALUES of every project date column, for tracked projects ───
        # This is the key section: line the columns up against projects whose real ship
        # dates you know, and the authoritative column becomes obvious.
        rule(f"B. SAMPLE VALUES — every tblProjects date column, projects {id_list}")
        if proj_dates:
            sel = "ProjectID, " + ", ".join(f"[{n}]" for n, _ in proj_dates)
            run(cur, "B1. project × date-column matrix",
                f"SELECT {sel} FROM dbo.tblProjects WHERE ProjectID IN ({id_list}) "
                "ORDER BY ProjectID", max_rows=60)

        # ── C. schedule / milestone / delivery tables that might hold the date ────
        rule("C. SCHEDULE / MILESTONE / SHIP / DELIVERY OBJECTS (name search)")
        run(cur, "C1. tables & views named like ship/schedule/milestone/delivery/due",
            "SELECT TABLE_NAME, TABLE_TYPE FROM INFORMATION_SCHEMA.TABLES "
            "WHERE TABLE_NAME LIKE '%Ship%' OR TABLE_NAME LIKE '%Schedul%' "
            "OR TABLE_NAME LIKE '%Milestone%' OR TABLE_NAME LIKE '%Deliver%' "
            "OR TABLE_NAME LIKE '%DueDate%' OR TABLE_NAME LIKE '%Promise%' "
            "ORDER BY TABLE_NAME", max_rows=80)

        # ── D. any COLUMN anywhere named like a ship date (broad net) ─────────────
        rule("D. COLUMNS ANYWHERE NAMED LIKE A SHIP / DELIVERY / DUE DATE")
        like = " OR ".join(
            f"COLUMN_NAME LIKE '%{h}%'" for h in
            ("Ship", "Deliver", "DueDate", "Required", "Promise", "AgreedDate", "PlannedDate"))
        run(cur, "D1. date-typed columns whose name hints a ship/delivery/due date",
            "SELECT TABLE_NAME, COLUMN_NAME, DATA_TYPE FROM INFORMATION_SCHEMA.COLUMNS "
            f"WHERE ({like}) AND DATA_TYPE IN ('date','datetime','datetime2','smalldatetime') "
            "ORDER BY TABLE_NAME, COLUMN_NAME", max_rows=120)

        # ── E. full project row(s) for eyeballing (all fields, sample project) ────
        rule(f"E. FULL tblProjects ROW — sample project {sample} (all fields)")
        run(cur, "E1. everything on the project master for one project",
            f"SELECT * FROM dbo.tblProjects WHERE ProjectID = {sample}", max_rows=3)

        # ── F. what the Console overlay currently serves (for comparison) ─────────
        rule("F. WHAT THE CONSOLE OVERLAY SERVES TODAY (compare to the ETO candidates)")
        run(cur, "F1. overlay ship dates (Console store — the PM-maintained values)",
            "SELECT TOP 20 ProjectID, POShipDate, CustAgreedShipDate, PlannedShipDate "
            "FROM Reporting.vw_Console_ManualOverlay ORDER BY ProjectID")
    finally:
        conn.close()
    print("\nDone. Paste the whole output.\n"
          "  • A/B: the date columns on the project master + their VALUES for known projects —\n"
          "    match these against the ship dates you already know to spot the right column.\n"
          "  • C/D: schedule/milestone tables or ship-named columns elsewhere, if it's not on\n"
          "    tblProjects directly.\n"
          "  • E: the whole project row, to catch a ship date under a non-obvious name.\n"
          "  • F: the overlay values we serve today, to confirm the ETO column agrees.\n"
          "Then tell me the table.column to use and I'll wire the Plan page (and dashboard) to it.")


if __name__ == "__main__":
    main()
