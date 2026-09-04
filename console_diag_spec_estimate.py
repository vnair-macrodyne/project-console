"""
console_diag_spec_estimate.py — are ETO's SPEC-level (machine) labour estimates populated,
and do they roll up to machine x discipline?  (2026-08-25)

Goal: decide whether machine x discipline budgets can be SOURCED from ETO's estimate module
(no manual re-key), per the plan to move budgets from project x discipline to machine x
discipline. Many shops fill only the 3-bucket PROJECT estimate (Admin/Eng/Mfg) and leave the
per-SPEC (per-machine) by-hourtype estimate blank — so we must confirm coverage before building.

What it does (READ-ONLY):
  A. Find candidate estimate views — anything like %Spec%Estimate% / %Estimate%HourType% /
     %ProjectEstimate% — with row counts, so we use the real name on THIS ETO.
  B. For the chosen spec-by-hourtype view: list its columns, and auto-detect the Project / Spec
     (machine) / HourType / estimate-hours columns by name.
  C. Coverage: across active projects, how many have ANY spec-level estimate; per project, how
     many distinct specs (machines) carry estimate hours > 0.
  D. For one sample project: Spec (machine) x HourType estimate hours, then mapped to DISCIPLINE
     via Reporting.tlkpDisciplineCrosswalk (Console store) and rolled to machine x discipline —
     i.e. exactly the grain the new budget would store.
  E. Verdict hints.

Run:  python console_diag_spec_estimate.py [projectID]
Paste the WHOLE output.
"""
import sys

VIEW_HINTS = ("spec%estimate", "estimate%hourtype", "estimatebyhourtype", "speclabor%estimate",
              "projectestimate", "laboractualsvsestimatesbyhourtype")
PROJ_COLS = ("projectid", "project")
SPEC_COLS = ("specid", "spec", "machine", "assembly", "assemblyid")
HTYPE_COLS = ("hourtype", "hourdescription", "hourtypedescription", "hourtypename", "hrtype")
HOUR_COLS = ("estimatehours", "estimatedhours", "budgethours", "esthours", "hours", "estimatelabor")


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
    """Console store (for the HourDescription->discipline crosswalk). Optional."""
    try:
        from console.infra.connections import console_connection
        return console_connection()
    except Exception:
        try:
            from console_store import console_connection as cc
            return cc()
        except Exception:
            return None


def rule(t):
    print("\n" + "=" * 78 + f"\n{t}\n" + "=" * 78)


def rows(cur, sql, *a):
    cur.execute(sql, *a)
    cols = [d[0] for d in cur.description]
    return cols, cur.fetchall()


def pick(cols, hints):
    low = {c.lower(): c for c in cols}
    for h in hints:
        for lc, orig in low.items():
            if lc == h:
                return orig
    for h in hints:
        for lc, orig in low.items():
            if h.replace("%", "") in lc:
                return orig
    return None


def main():
    proj = sys.argv[1] if len(sys.argv) > 1 else None
    eto = eto_connect()
    cur = eto.cursor()

    rule("A. Estimate/budget/quote objects on this ETO (tables + views, row counts)")
    terms = ["estimate", "budget", "quote", "quotation"]
    like = " OR ".join(f"LOWER(TABLE_NAME) LIKE '%{t}%'" for t in terms)
    _, cand = rows(cur, "SELECT TABLE_NAME, TABLE_TYPE FROM INFORMATION_SCHEMA.TABLES "
                        f"WHERE {like} ORDER BY TABLE_NAME")
    if not cand:
        print("Nothing matched estimate/budget/quote. This ETO may not use the estimating module.")
        # last resort: show spec+labor objects so we can see what estimate-like data exists
        _, sl = rows(cur, "SELECT TABLE_NAME, TABLE_TYPE FROM INFORMATION_SCHEMA.TABLES "
                          "WHERE LOWER(TABLE_NAME) LIKE '%spec%' AND "
                          "(LOWER(TABLE_NAME) LIKE '%labor%' OR LOWER(TABLE_NAME) LIKE '%hour%') "
                          "ORDER BY TABLE_NAME")
        for name, tt in sl:
            print(f"  {name:55} {tt}")
        return

    def score(name):
        n = name.lower(); s = 0
        if any(k in n for k in ("spec", "machine", "assembly")): s += 3
        if any(k in n for k in ("hourtype", "hourdescription", "byhour")): s += 3
        if "estimate" in n: s += 1
        return s

    scored = []
    for name, tt in cand:
        try:
            cur.execute(f"SELECT COUNT(*) FROM [{name}]")
            n = cur.fetchone()[0]
        except Exception as e:
            n = f"(error: {e})"
        scored.append((name, tt, n))
        print(f"  {name:55} {tt:11} rows={n}")

    # prefer a POPULATED object scoring high on spec + hourtype
    ranked = sorted(
        [(score(nm), (isinstance(n, int) and n > 0), nm) for nm, tt, n in scored],
        key=lambda x: (x[0], x[1]), reverse=True)
    view = None
    for sc, populated, nm in ranked:
        if sc >= 3 and populated:
            view = nm; break
    if not view:
        # fall back to any populated estimate object with an hourtype dimension
        for sc, populated, nm in ranked:
            if populated and ("hour" in nm.lower()):
                view = nm; break
    if not view:
        print("\nNo populated SPEC-level (machine) by-hourtype estimate object found. Project-level "
              "estimates may still exist (see the list above) — but machine-grain budgets would "
              "then need manual entry or allocation. Tell me which object above looks like the "
              "spec/machine estimate and I'll point the probe at it.")
        return
    print(f"\n  --> probing '{view}' as the spec-by-hourtype estimate")

    rule(f"B. Columns of {view}  (+ auto-detected roles)")
    _, cols_rows = rows(cur, "SELECT COLUMN_NAME, DATA_TYPE FROM INFORMATION_SCHEMA.COLUMNS "
                            "WHERE TABLE_NAME = ? ORDER BY ORDINAL_POSITION", view)
    cols = [c for c, _ in cols_rows]
    for c, t in cols_rows:
        print(f"  {c:40} {t}")
    c_proj = pick(cols, PROJ_COLS); c_spec = pick(cols, SPEC_COLS)
    c_ht = pick(cols, HTYPE_COLS); c_hrs = pick(cols, HOUR_COLS)
    print(f"\n  detected -> project={c_proj}  spec/machine={c_spec}  hourtype={c_ht}  hours={c_hrs}")
    if not all((c_proj, c_spec, c_ht, c_hrs)):
        print("  Could not auto-detect all key columns — eyeball the column list above and tell me "
              "which is project / spec(machine) / hourtype / estimate-hours.")
        return

    rule("C. Coverage — spec-level estimate presence")
    cur.execute(f"SELECT COUNT(DISTINCT [{c_proj}]) FROM [{view}] WHERE [{c_hrs}] > 0")
    print(f"  projects with ANY spec-level estimate hours: {cur.fetchone()[0]}")
    _, cov = rows(cur,
        f"SELECT TOP 25 [{c_proj}] AS Project, COUNT(DISTINCT [{c_spec}]) AS SpecsWithEst, "
        f"CAST(SUM([{c_hrs}]) AS decimal(12,1)) AS EstHours "
        f"FROM [{view}] WHERE [{c_hrs}] > 0 GROUP BY [{c_proj}] ORDER BY EstHours DESC")
    print(f"  {'Project':>10} {'Specs w/ est':>13} {'Est hours':>12}")
    for r in cov:
        print(f"  {str(r[0]):>10} {str(r[1]):>13} {str(r[2]):>12}")
    if proj is None and cov:
        proj = str(cov[0][0])
        print(f"\n  (no project arg given — sampling the top one: {proj})")

    rule(f"D. Sample project {proj}: machine x hourtype estimate, mapped to discipline")
    # crosswalk from the Console store (HourDescription -> Discipline)
    xwalk = {}
    cc = console_connect()
    if cc:
        try:
            xc = cc.cursor()
            xc.execute("SELECT HourDescription, Discipline FROM Reporting.tlkpDisciplineCrosswalk")
            xwalk = {r[0].strip().lower(): r[1] for r in xc.fetchall() if r[0]}
            print(f"  crosswalk loaded: {len(xwalk)} HourDescription->discipline mappings")
        except Exception as e:
            print(f"  (crosswalk load failed: {e} — showing raw hourtypes only)")
        finally:
            cc.close()
    else:
        print("  (Console store not reachable — showing raw hourtypes only)")

    _, det = rows(cur,
        f"SELECT [{c_spec}] AS Spec, [{c_ht}] AS HourType, CAST(SUM([{c_hrs}]) AS decimal(12,1)) AS Hrs "
        f"FROM [{view}] WHERE [{c_proj}] = ? AND [{c_hrs}] > 0 "
        f"GROUP BY [{c_spec}], [{c_ht}] ORDER BY [{c_spec}], [{c_ht}]", proj)
    if not det:
        print(f"  No spec-level estimate rows for project {proj}.")
        return
    disc_roll = {}
    print(f"  {'Machine':>10} {'HourType':32} {'Hrs':>9}  {'Discipline'}")
    for spec, ht, hrs in det:
        disc = xwalk.get((ht or "").strip().lower(), "(unmapped)") if xwalk else "-"
        print(f"  {str(spec):>10} {str(ht)[:32]:32} {str(hrs):>9}  {disc}")
        disc_roll[(spec, disc)] = disc_roll.get((spec, disc), 0) + float(hrs or 0)
    if xwalk:
        rule(f"D2. Rolled up: machine x DISCIPLINE budget hours (project {proj})")
        print(f"  {'Machine':>10} {'Discipline':28} {'Budget hrs':>12}")
        for (spec, disc), h in sorted(disc_roll.items()):
            print(f"  {str(spec):>10} {disc:28} {round(h,1):>12}")

    rule("E. Verdict hints")
    print("  - If C shows most/all active projects with specs-with-est > 0, ETO is a viable "
          "machine x discipline budget SOURCE (no re-key).")
    print("  - If D2's disciplines look right and few/no '(unmapped)' hourtypes, the crosswalk "
          "covers the estimate hourtypes too.")
    print("  - Sparse/zero coverage => spec estimates aren't maintained; fall back to manual "
          "per-machine entry or project-level entry with machine allocation.")
    eto.close()


if __name__ == "__main__":
    main()
