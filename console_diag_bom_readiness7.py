"""
console_diag_bom_readiness7.py — why does BOM Readiness come back empty in the app?  READ-ONLY.
(2026-09-13)

The app calls crp0470EngStructuredReadiness and gets NO rows for every machine. Probe 6 (which would
have confirmed the explode) was never run, so the open question is: does @intNumberOfLevels=99 actually
EXPLODE the tree, or return nothing? This probe answers it definitively for 250250 / machine 10:

  1. Confirms the machine list the app uses (SELECT DISTINCT SpecID FROM vwEngProductStructure).
  2. Runs the EXACT string the app builds ("SET NOCOUNT ON; EXEC dbo.crp0470EngStructuredReadiness
     @intProjectID=…, … @intNumberOfLevels=99, …") and walks EVERY result set, printing each set's
     column-count + row-count and whether it carries ItemCompanyID — so we see what the app sees.
  3. SWEEPS @intNumberOfLevels over 0,1,2,3,5,10,25,50,99,999 (via the positional {CALL} form that
     probe 5 proved works) and prints the ROW COUNT for each — revealing which value explodes the BOM.
  4. Shows the first exploded rows for the best NumberOfLevels.

Run where the other console_diag_*.py scripts run (ETO reachable):
    python console_diag_bom_readiness7.py
Paste the WHOLE output back.
"""
SAMPLE_PROJECT = 250250
SAMPLE_MACHINE = 10
PROC = "crp0470EngStructuredReadiness"


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


def rule(t):
    print("\n" + "=" * 92 + f"\n{t}\n" + "=" * 92)


def app_exec_sql(pid, spec, levels):
    return ("SET NOCOUNT ON; "
            f"EXEC dbo.{PROC} "
            f"@intProjectID={int(pid)}, @decSpecID={float(spec)}, @intAssemblyStructureID=0, "
            f"@bitExplodeStandardAssemblies=1, @intWeightMethod=0, @bitAssembliesOnly=0, "
            f"@bitHideFullyAvailable=0, @intNumberOfLevels={levels}, @intIndentSpaces=3, "
            f"@bitAverageWithBOMQty=0")


def main():
    eto = eto_connect()
    cur = eto.cursor()

    # ── 1. the machine list the app uses ────────────────────────────────────────
    rule(f"1. Machines the app finds for project {SAMPLE_PROJECT} (vwEngProductStructure)")
    try:
        cur.execute(f"SELECT DISTINCT SpecID FROM dbo.vwEngProductStructure "
                    f"WHERE ProjectID = {SAMPLE_PROJECT} ORDER BY SpecID")
        specs = [r[0] for r in cur.fetchall()]
        print(f"   SpecIDs: {specs}")
    except Exception as e:
        print(f"   !! {type(e).__name__}: {e}")

    # ── 2. the EXACT app call — walk every result set ───────────────────────────
    rule(f"2. APP CALL string, {SAMPLE_PROJECT}/{SAMPLE_MACHINE}, NumberOfLevels=99 — every result set")
    sql = app_exec_sql(SAMPLE_PROJECT, SAMPLE_MACHINE, 99)
    print(f"   SQL: {sql}")
    try:
        cur.execute(sql)
        setno = 0
        while True:
            setno += 1
            if cur.description is not None:
                cols = [d[0] for d in cur.description]
                rows = cur.fetchall()
                has = "ItemCompanyID" in cols
                print(f"   set {setno}: {len(rows)} rows, {len(cols)} cols, hasItemCompanyID={has}")
                if has and rows:
                    print("     first rows (Depth | UOMType | ItemCompanyID | ItemDescription):")
                    ci = {c: cols.index(c) for c in ("Depth", "UOMType", "ItemCompanyID", "ItemDescription") if c in cols}
                    for r in rows[:8]:
                        print("       " + " | ".join(str(r[ci[c]]) for c in ci))
            else:
                print(f"   set {setno}: (no columns)")
            if not cur.nextset():
                break
    except Exception as e:
        print(f"   !! {type(e).__name__}: {e}")

    # ── 3. sweep NumberOfLevels (positional {CALL}) — which value EXPLODES? ──────
    rule("3. NumberOfLevels sweep — ROW COUNT per value (positional CALL, like probe 5)")
    for lv in (0, 1, 2, 3, 5, 10, 25, 50, 99, 999):
        args = [SAMPLE_PROJECT, SAMPLE_MACHINE, 0, 1, 0, 0, 0, lv, 3, 0]
        try:
            cur.execute(f"{{CALL dbo.{PROC}(?,?,?,?,?,?,?,?,?,?)}}", args)
            n = 0
            while True:
                if cur.description is not None:
                    n = len(cur.fetchall())
                    if n:
                        break
                if not cur.nextset():
                    break
            print(f"   NumberOfLevels={lv:>4} -> {n} row(s)")
        except Exception as e:
            print(f"   NumberOfLevels={lv:>4} -> !! {type(e).__name__}: {e}")

    # ── 4. also try HideFullyAvailable=0 vs AssembliesOnly, in case levels isn't it ─
    rule("4. arg variations at a mid NumberOfLevels=25 (row counts)")
    variations = {
        "explode=1, assembliesOnly=0, hideAvail=0": [SAMPLE_PROJECT, SAMPLE_MACHINE, 0, 1, 0, 0, 0, 25, 3, 0],
        "explode=0": [SAMPLE_PROJECT, SAMPLE_MACHINE, 0, 0, 0, 0, 0, 25, 3, 0],
        "assembliesOnly=1": [SAMPLE_PROJECT, SAMPLE_MACHINE, 0, 1, 0, 1, 0, 25, 3, 0],
        "weightMethod=1": [SAMPLE_PROJECT, SAMPLE_MACHINE, 0, 1, 1, 0, 0, 25, 3, 0],
    }
    for label, args in variations.items():
        try:
            cur.execute(f"{{CALL dbo.{PROC}(?,?,?,?,?,?,?,?,?,?)}}", args)
            n = 0
            while True:
                if cur.description is not None:
                    n = len(cur.fetchall())
                    if n:
                        break
                if not cur.nextset():
                    break
            print(f"   {label:44} -> {n} row(s)")
        except Exception as e:
            print(f"   {label:44} -> !! {type(e).__name__}: {e}")

    eto.close()
    print("\nDONE — paste everything above.")


if __name__ == "__main__":
    main()
