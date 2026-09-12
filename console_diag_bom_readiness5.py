"""
console_diag_bom_readiness5.py — call the readiness report proc directly (exploded rows), and get
the real BOM-view columns + TVF explode arg.  READ-ONLY (only EXECs vendor report procs that SELECT).
(2026-09-12)

Probe 4 showed: the readiness objects exist and are NOT encrypted (IsEncrypted=0), but our read-only
login can't read their source (OBJECT_DEFINITION NULL = no VIEW DEFINITION permission). We don't need
the source — we can EXECUTE the per-spec report proc and capture its result set, which IS the exploded
readiness report. Also, vwEngProductStructure has no 'ItemID' column, so probe 4's root lookup failed
and every TVF call fell back to AssemblyStructureID=0 (top node only).

This probe:
  1. Prints sys.parameters for the candidate report procs + the TVF (how to call each — works without
     VIEW DEFINITION; parameter metadata is readable).
  2. Dumps the REAL columns of vwEngProductStructure and vwEngBOM (so we use correct names).
  3. Adaptively EXECUTEs the per-spec report procs for 250250/machine 10 — reads each proc's params,
     fills ProjectID=250250, SpecID=10, explode/indent sensibly, 0/NULL otherwise — and reports, for
     every result set, the columns + row count + a sample (the one with many rows is the exploded BOM).
  4. Re-tries the TVF using the top assembly's real StructureID once we can see the view's columns.

Run from the repo root where the app lives:
    python console_diag_bom_readiness5.py
Paste the WHOLE output back.
"""
SAMPLE_PROJECT = 250250
SAMPLE_MACHINE = 10
PROCS = ["urpEngStructuredReadinessBySpec", "urpEngStructuredReadiness_ForReferenceOnly",
         "crp0470EngStructuredReadiness", "crp0470StructuredBOMReadinessDetailedPS"]
PARAM_OBJS = PROCS + ["udfEngStructuredReadiness"]


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
    print("\n" + "=" * 88 + f"\n{t}\n" + "=" * 88)


def run(cur, label, sql, cap=80):
    print(f"\n-- {label}")
    try:
        cur.execute(sql)
        if cur.description is None:
            print("   (no result set)"); return []
        cols = [d[0] for d in cur.description]
        rows = cur.fetchall()
        print("   " + " | ".join(cols))
        for r in rows[:cap]:
            print("   " + " | ".join("" if v is None else str(v) for v in r))
        print(f"   ({len(rows)} row(s))")
        return rows
    except Exception as e:
        print(f"   !! {type(e).__name__}: {e}")
        return []


def proc_params(cur, name):
    cur.execute("""SELECT p.name, t.name AS dtype, p.parameter_id, p.is_output
                   FROM sys.parameters p JOIN sys.types t ON t.user_type_id = p.user_type_id
                   JOIN sys.objects o ON o.object_id = p.object_id
                   WHERE o.name = ? ORDER BY p.parameter_id""", (name,))
    return [(r[0], r[1], r[3]) for r in cur.fetchall()]


def value_for(pname, dtype):
    n = (pname or "").lower().lstrip("@")
    if "project" in n:
        return SAMPLE_PROJECT
    if "spec" in n:
        return SAMPLE_MACHINE
    if "explode" in n:
        return 1
    if "indent" in n:
        return 3
    if dtype in ("int", "bigint", "smallint", "tinyint", "bit", "decimal", "numeric", "float", "money"):
        return 0
    return None


def exec_proc(cur, name):
    params = proc_params(cur, name)
    inp = [p for p in params if not p[2]]  # non-output
    vals = [value_for(pn, dt) for (pn, dt, _o) in inp]
    placeholders = ", ".join("?" for _ in inp)
    call = f"{{CALL dbo.{name}({placeholders})}}" if inp else f"{{CALL dbo.{name}}}"
    print(f"\n-- EXEC {name}  params={[(pn, dt) for pn, dt, _ in inp]}  values={vals}")
    try:
        cur.execute(call, vals) if inp else cur.execute(call)
        setno = 0
        while True:
            setno += 1
            if cur.description is not None:
                cols = [d[0] for d in cur.description]
                rows = cur.fetchall()
                print(f"   result set {setno}: {len(rows)} rows, {len(cols)} cols")
                print("     cols: " + " | ".join(cols))
                for r in rows[:12]:
                    print("     " + " | ".join("" if v is None else str(v) for v in r))
                if len(rows) > 1:
                    print(f"   >>> {name} set {setno} is EXPLODED ({len(rows)} rows).")
            else:
                print(f"   result set {setno}: (no columns)")
            if not cur.nextset():
                break
    except Exception as e:
        print(f"   !! {type(e).__name__}: {e}")


def main():
    eto = eto_connect()
    cur = eto.cursor()

    # ── 1. parameters of each candidate ──────────────────────────────────────────
    rule("1. PARAMETERS of the readiness procs + TVF (how to call them)")
    for nm in PARAM_OBJS:
        ps = proc_params(cur, nm)
        print(f"\n   {nm}:")
        for pn, dt, isout in ps:
            print(f"      {pn} : {dt}{' OUTPUT' if isout else ''}")
        if not ps:
            print("      (no parameters)")

    # ── 2. real columns of the BOM views ─────────────────────────────────────────
    rule("2. REAL columns of vwEngProductStructure / vwEngBOM")
    for v in ("vwEngProductStructure", "vwEngBOM"):
        run(cur, f"2. columns of {v}",
            f"SELECT COLUMN_NAME, DATA_TYPE FROM INFORMATION_SCHEMA.COLUMNS "
            f"WHERE TABLE_NAME='{v}' ORDER BY ORDINAL_POSITION", cap=120)

    # ── 3. EXECUTE the per-spec report procs (capture exploded result set) ───────
    rule(f"3. EXEC the report procs for {SAMPLE_PROJECT}/machine {SAMPLE_MACHINE}")
    for nm in PROCS:
        exec_proc(cur, nm)

    # ── 4. TVF with the real top StructureID (now that we can see the columns) ───
    rule(f"4. udfEngStructuredReadiness with the real top StructureID for {SAMPLE_PROJECT}/{SAMPLE_MACHINE}")
    # show the structure rows so we can see parent/child/structure id names
    run(cur, "4a. top-level structure rows for this machine (ParentID=0)",
        f"SELECT TOP 20 * FROM dbo.vwEngProductStructure "
        f"WHERE ProjectID={SAMPLE_PROJECT} AND SpecID={SAMPLE_MACHINE} "
        f"ORDER BY ParentID", cap=20)

    eto.close()
    print("\nDONE — paste everything above.")


if __name__ == "__main__":
    main()
