"""
console_diag_bom_readiness4.py — find the REAL readiness report proc(s) and the arg combo that
EXPLODES the full indented BOM.  READ-ONLY.  Nothing is written.  (2026-09-12)

Probe 3 showed:
  * my guessed proc names don't exist (OBJECT_ID → NULL → OBJECT_DEFINITION NULL; not "encrypted").
  * udfEngStructuredReadiness(250250,10,0,1,0,0,0) returns ONLY the top node (Depth 0, TOP 250250-10),
    i.e. AssemblyStructureID=0 does not explode the assembly.

This probe:
  1. DISCOVERS every readiness-related object by name pattern (proc / function / view), with type +
     IsEncrypted, and whether its definition is readable.
  2. PRINTS the full definition of each NON-encrypted proc/function found — the report proc shows the
     EXACT call into udfEngStructuredReadiness (the AssemblyStructureID it passes + the other 6 args),
     the Bin source, and the column→display mapping.
  3. Finds the TOP assembly StructureID for 250250 / machine 10 in the product-structure tree, then
     RE-CALLS udfEngStructuredReadiness with several arg combos (including that StructureID and
     ExplodeStandardAssemblies / AverageWithBOMQty variations) to find the one that returns the full
     multi-depth BOM.

Run where the other console_diag_*.py scripts run (ETO reachable):
    python console_diag_bom_readiness4.py
Paste the WHOLE output back.
"""
SAMPLE_PROJECT = 250250
SAMPLE_MACHINE = 10
NAME_PATTERNS = ["%Readiness%", "%StructuredBOM%", "%BOMReadiness%", "%EngStructured%",
                 "%crp0470%", "%StructuredReadiness%"]
KEY_COLS = ("Depth", "ParentID", "ChildID", "ItemCompanyID", "UOMType", "CategoryDescription",
            "ItemQty", "TotalRequiredForEntireAssy", "TotalAvailable", "ToBeProcured",
            "PercentageComplete_Absolute_Assy")


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


def run(cur, label, sql, cap=60):
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


def main():
    eto = eto_connect()
    cur = eto.cursor()

    # ── 1. Discover the real readiness objects ───────────────────────────────────
    rule("1. DISCOVER readiness objects (name patterns) — type, encrypted?, definition readable?")
    like = " OR ".join(f"o.name LIKE '{p}'" for p in NAME_PATTERNS)
    found = run(cur, "1. sys.objects matching readiness patterns", f"""
        SELECT o.name, o.type_desc,
               OBJECTPROPERTY(o.object_id,'IsEncrypted') AS IsEncrypted,
               CASE WHEN OBJECT_DEFINITION(o.object_id) IS NULL THEN 'NULL' ELSE 'readable' END AS def_state
        FROM sys.objects o
        WHERE ({like}) AND o.type IN ('P','FN','IF','TF','V')
        ORDER BY o.type_desc, o.name""", cap=200)

    names = [r[0] for r in found]

    # ── 2. Print definitions of the procs/functions found (non-encrypted) ────────
    rule("2. DEFINITIONS of the discovered procs/functions (shows the real call + Bin + columns)")
    for nm in names:
        print("\n" + "-" * 88 + f"\n----- {nm} -----\n" + "-" * 88)
        try:
            cur.execute("SELECT OBJECT_DEFINITION(OBJECT_ID(?))", (nm,))
            row = cur.fetchone()
            print(row[0] if row and row[0] else "(definition NULL — encrypted)")
        except Exception as e:
            print(f"!! {type(e).__name__}: {e}")

    # ── 3. Find the TOP assembly StructureID for 250250/10, then explode ─────────
    rule(f"3. TOP assembly StructureID for {SAMPLE_PROJECT}/{SAMPLE_MACHINE} + explode attempts")
    run(cur, "3a. product-structure root node(s) for this machine",
        f"""SELECT TOP 20 StructureID, ParentID, ChildID, ItemID, ItemQty, UOMType
            FROM dbo.vwEngProductStructure
            WHERE ProjectID = {SAMPLE_PROJECT} AND SpecID = {SAMPLE_MACHINE}
            ORDER BY ParentID, StructureID""")

    # grab a candidate root StructureID (ParentID = 0) to feed the function
    cur.execute(f"""SELECT TOP 1 StructureID FROM dbo.vwEngProductStructure
                    WHERE ProjectID = {SAMPLE_PROJECT} AND SpecID = {SAMPLE_MACHINE}
                    AND (ParentID = 0 OR ParentID IS NULL) ORDER BY StructureID""")
    rootrow = cur.fetchone()
    root_sid = rootrow[0] if rootrow else 0
    print(f"\n   candidate root StructureID = {root_sid}")

    sel = ", ".join(KEY_COLS)
    sigs = [
        f"({SAMPLE_PROJECT}, {SAMPLE_MACHINE}, {root_sid}, 1, 0, 0, 0)",
        f"({SAMPLE_PROJECT}, {SAMPLE_MACHINE}, {root_sid}, 0, 0, 0, 0)",
        f"({SAMPLE_PROJECT}, {SAMPLE_MACHINE}, 0, 1, 0, 3, 1)",
        f"({SAMPLE_PROJECT}, {SAMPLE_MACHINE}, 0, 1, 1, 3, 0)",
        f"({SAMPLE_PROJECT}, {SAMPLE_MACHINE}, 0, 0, 0, 3, 1)",
        f"({SAMPLE_PROJECT}, {SAMPLE_MACHINE}, {root_sid}, 1, 1, 3, 1)",
    ]
    for sig in sigs:
        rows = run(cur, f"3b. udfEngStructuredReadiness{sig} — TOP 40 (looking for multi-depth)",
                   f"SELECT TOP 40 {sel} FROM dbo.udfEngStructuredReadiness{sig}", cap=40)
        if len(rows) > 1:
            print(f"   >>> THIS SIGNATURE EXPLODES: {len(rows)} rows returned.")

    eto.close()
    print("\nDONE — paste everything above.")


if __name__ == "__main__":
    main()
