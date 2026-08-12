"""
console_diag_plan_readback.py — why don't the Plan inputs reach the dashboard? (2026-08-11)

Symptom: a PM saved a Planned Ship Date + per-discipline % complete, but the dashboard shows no
run-out and no ship date. This reads back the Console store to isolate WHERE it breaks:

  A. did the % complete rows actually land in tblProjectDisciplineProgress?  (+ the discipline NAMES)
  B. do those names EXACTLY match the crosswalk names the engine rolls up against?  (mismatch → 0%)
  C. did the Planned Ship Date land in tblProjectPMEntry?
  D. does the overlay view (what the dashboard reads) surface that ship date?
  E. how is vw_Console_ManualOverlay actually defined?  (does PlannedShipDate come from PMEntry?)

READ-ONLY, Console store only (no ETO). Run:
    python console_diag_plan_readback.py            # scans projects that have progress rows
    python console_diag_plan_readback.py 230219     # focus one project you just edited
"""
import sys


def console_connect():
    try:
        from console.infra.connections import console_connection
        return console_connection()
    except Exception:
        from console_store import console_connection
        return console_connection()


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
            return []
        cols = [d[0] for d in cur.description]
        rows = cur.fetchall()
        print("  " + " | ".join(cols))
        for r in rows[:max_rows]:
            print("  " + " | ".join("" if v is None else str(v) for v in r))
        if len(rows) > max_rows:
            print(f"  ... (+{len(rows) - max_rows} more)")
        if not rows:
            print("  (0 rows)")
        return rows
    except Exception as e:
        print(f"  [ERROR] {type(e).__name__}: {e}")
        return []


def main():
    pid = None
    if len(sys.argv) > 1:
        try:
            pid = int(sys.argv[1])
        except ValueError:
            pass
    conn = console_connect()
    cur = conn.cursor()
    where_pid = f"WHERE ProjectID = {pid}" if pid else ""
    and_pid = f"AND ProjectID = {pid}" if pid else ""
    print(f"Focus project: {pid if pid else '(all with progress rows)'}")
    try:
        # ── A. did the % complete rows land? ─────────────────────────────────────
        rule("A. tblProjectDisciplineProgress — the % complete rows the Plan form writes")
        prog = run(cur, "A1. latest row per project+discipline",
                   "SELECT ProjectID, Discipline, PercentComplete, YearWeekKey, EnteredBy, CapturedAt "
                   "FROM (SELECT *, ROW_NUMBER() OVER (PARTITION BY ProjectID, Discipline "
                   "      ORDER BY YearWeekKey DESC, CapturedAt DESC) rn "
                   f"      FROM Reporting.tblProjectDisciplineProgress {where_pid}) t "
                   "WHERE rn = 1 ORDER BY ProjectID, Discipline")
        prog_names = sorted({r[1] for r in prog})

        # ── B. do the names match the crosswalk the engine uses? ─────────────────
        rule("B. NAME MATCH — progress discipline names vs the crosswalk (engine roll-up key)")
        xwalk = run(cur, "B1. distinct Discipline in tlkpDisciplineCrosswalk (engine's names)",
                    "SELECT DISTINCT Discipline FROM Reporting.tlkpDisciplineCrosswalk "
                    "ORDER BY Discipline")
        xnames = sorted({r[0] for r in xwalk})
        print("\n  progress names :", prog_names or "(none)")
        print("  crosswalk names:", xnames or "(none)")
        only_prog = [n for n in prog_names if n not in xnames]
        if only_prog:
            print("  ⚠ names in progress but NOT in the crosswalk (these roll up to 0%):", only_prog)
        else:
            print("  ✓ every progress name exists in the crosswalk (roll-up will match)")

        # ── C. did the ship date land in PMEntry? ────────────────────────────────
        rule("C. tblProjectPMEntry — did the Planned Ship Date save?")
        run(cur, "C1. latest PM entry per project",
            "SELECT ProjectID, YearWeekKey, PlannedShipDate, ReworkThreshold, CapturedAt "
            "FROM (SELECT *, ROW_NUMBER() OVER (PARTITION BY ProjectID ORDER BY YearWeekKey DESC) rn "
            f"      FROM Reporting.tblProjectPMEntry {where_pid}) t WHERE rn = 1 "
            "ORDER BY ProjectID")

        # ── D. does the overlay (dashboard's source) show that ship date? ────────
        rule("D. vw_Console_ManualOverlay — what the DASHBOARD actually reads")
        run(cur, "D1. overlay ship dates",
            "SELECT ProjectID, POShipDate, CustAgreedShipDate, PlannedShipDate "
            f"FROM Reporting.vw_Console_ManualOverlay {where_pid} ORDER BY ProjectID")

        # ── E. how is the overlay defined? (is PlannedShipDate wired to PMEntry?) ─
        rule("E. DEFINITION of vw_Console_ManualOverlay (does PlannedShipDate come from PMEntry?)")
        run(cur, "E1. view SQL",
            "SELECT m.definition FROM sys.sql_modules m "
            "JOIN sys.objects o ON o.object_id = m.object_id "
            "WHERE o.name = 'vw_Console_ManualOverlay'", max_rows=1)
    finally:
        conn.close()
    print("\nDone. Paste the whole output. Reading it:\n"
          "  • A empty → the % complete never saved (save path / wrong DB). A populated → it landed.\n"
          "  • B ⚠ → discipline names don't match the crosswalk, so the roll-up is 0% and run-out\n"
          "    stays blank (the fix is aligning the names).\n"
          "  • C has PlannedShipDate but D doesn't → the overlay view isn't surfacing it (E shows\n"
          "    why); that's the ship-date bug, independent of the run-out.\n"
          "  • A+B fine but dashboard still blank → the running queries.py isn't the run-out build,\n"
          "    or the app wasn't restarted / __pycache__ is stale.")


if __name__ == "__main__":
    main()
