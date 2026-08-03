"""
console_diag_step_timing.py — break the dashboard build into its sub-steps (2026-08-03).

Correction from the last probe: the financials rollup views are FAST for a single project
(~0.05s) and only slow as a 22-id IN-list. So single-project slowness is elsewhere. This times
each internal step of the exec/scorecard build directly, for 1 project AND the full scope, so we
target the real cost. READ-ONLY.

Run on the app host:  python console_diag_step_timing.py   → paste the whole output.
"""
import time


def _t(label, fn):
    t0 = time.perf_counter()
    err, n = None, None
    try:
        r = fn()
        n = len(r) if hasattr(r, "__len__") else None
    except Exception as e:
        err = f"{type(e).__name__}: {e}"
    dt = time.perf_counter() - t0
    line = f"    {dt:7.3f}s  {label}"
    if n is not None:
        line += f"   ({n})"
    if err:
        line += f"   [ERR] {err}"
    print(line)


def tracked_ids():
    from console.infra.connections import console_connection
    c = console_connection()
    cur = c.cursor()
    cur.execute("SELECT DISTINCT ProjectID FROM Reporting.vw_Console_BudgetCurrent ORDER BY ProjectID")
    ids = [int(r[0]) for r in cur.fetchall()]
    c.close()
    return ids


def main():
    from console_web.queries import LiveQueryService
    allids = tracked_ids()
    for label, ids in [("SINGLE project", allids[:1]), (f"FULL scope ({len(allids)} projects)", allids)]:
        print(f"\n== {label} ==  ids={ids if len(ids) <= 3 else str(ids[:3])+'…'}")
        s = LiveQueryService()
        _t("setup: open conns + crosswalk + overlay + hour maps", lambda:
           (s._eto_conn(), s._console_conn(), s._crosswalk(), s._overlay_map(),
            s._hourtype_map(), s._hourdesc_map()) and [])
        _t("_financials (memoised after 1st)", lambda: s._financials(ids))
        _t("_nc_by_project  (NC costing)", lambda: s._nc_by_project(ids))
        _t("_procurement_actuals", lambda: s._procurement_actuals(ids))
        _t("_two_week_actuals", lambda: s._two_week_actuals(ids))
        _t("_project_meta", lambda: s._project_meta(ids))
        # whole-board wall clock (fresh service = realistic first-request cost)
        s2 = LiveQueryService()
        _t("== whole scorecard (fresh service)", lambda: s2.run("scorecard", ids))
        s3 = LiveQueryService()
        _t("== whole exec (fresh service)", lambda: s3.run("exec", ids))
        for x in (s, s2, s3):
            try:
                x.close()
            except Exception:
                pass
    print("\nDone. Paste the whole output.\n"
          "  • The biggest single-project step is the real target (I expect _nc_by_project).\n"
          "  • 'setup' is per-request overhead — reused across the 4 boards within one refresh.\n"
          "  • Compare single vs full: steps that barely grow are fixed-cost (cache/snapshot);\n"
          "    steps that grow with the IN-list may just need per-project or batched querying.")


if __name__ == "__main__":
    main()
