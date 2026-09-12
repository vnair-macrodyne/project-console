"""
console_diag_bom_readiness2.py — nail the READINESS engine so Sextant can reproduce the
"Structured BOM - Readiness Detailed Report" from the SAME source ETO uses (2026-09-12).
READ-ONLY. Nothing is written.

Take 1 found the pieces: the assembly tree is vwEngProductStructure / vwEngBOM (ParentID→ChildID,
ItemQty, ItemCompanyID, UOMType AS/PC/SA, CategoryDescription), and the readiness columns
(Total/Avail/Proc/To-Be-Proc/%/Bin) come from a readiness FUNCTION/PROC:
    udfEngStructuredReadiness (table-valued function)   ← best: callable even though encrypted
    urpEngStructuredReadinessBySpec / crp0470StructuredBOMReadinessDetailedPS (report procs, encrypted)

This probe gets, for the readiness objects:
  P1. the FUNCTION'S OUTPUT COLUMNS (from the catalog — works even when the source is encrypted),
  P2. the PARAMETERS (so we know how to call it),
  P3. encryption flags,
  P4. a sample call of udfEngStructuredReadiness for the sample job (250250 / machine 10), trying a
      few likely signatures — the one that returns rows shows the exact readiness columns.

Run where the other console_diag_*.py scripts run (ETO reachable):
    python console_diag_bom_readiness2.py
Paste the WHOLE output back.
"""
SAMPLE_PROJECT = 250250
SAMPLE_MACHINE = 10
READINESS_OBJS = ["udfEngStructuredReadiness", "urpEngStructuredReadinessBySpec",
                  "urpEngStructuredReadiness_ForReferenceOnly", "crp0470StructuredBOMReadinessDetailedPS",
                  "crp0470EngStructuredReadiness", "udfEngReportsBaseWithStandardAssemblyExplode"]


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
    print("\n" + "=" * 84 + f"\n{t}\n" + "=" * 84)


def run(cur, label, sql, params=None, cap=30):
    print(f"\n-- {label}\n   {' '.join(sql.split())[:280]}")
    try:
        cur.execute(sql, params) if params else cur.execute(sql)
        if cur.description is None:
            print("   (no result set)"); return [], []
        cols = [d[0] for d in cur.description]
        rows = cur.fetchall()
        print("   " + " | ".join(cols))
        for r in rows[:cap]:
            print("   " + " | ".join("" if v is None else str(v) for v in r))
        print(f"   ({len(rows)} row(s){', showing '+str(cap) if len(rows)>cap else ''})")
        return cols, rows
    except Exception as e:
        print(f"   !! {type(e).__name__}: {e}")
        return [], []


def main():
    eto = eto_connect()
    cur = eto.cursor()
    inlist = ",".join(f"'{n}'" for n in READINESS_OBJS)

    # ── P1. OUTPUT COLUMNS of the readiness functions (works even if the source is encrypted) ──
    rule("P1. OUTPUT COLUMNS of the readiness function(s) — the readiness fields we need")
    run(cur, "P1. sys.columns for the readiness objects", f"""
        SELECT o.name AS object_name, o.type_desc, c.column_id, c.name AS column_name,
               t.name AS data_type, c.max_length
        FROM sys.objects o
        JOIN sys.columns c ON c.object_id = o.object_id
        JOIN sys.types t ON t.user_type_id = c.user_type_id
        WHERE o.name IN ({inlist})
        ORDER BY o.name, c.column_id""", cap=200)

    # ── P2. PARAMETERS (how to call them) ────────────────────────────────────────
    rule("P2. PARAMETERS of the readiness objects")
    run(cur, "P2. sys.parameters", f"""
        SELECT o.name AS object_name, p.parameter_id, p.name AS param_name,
               t.name AS data_type, p.max_length, p.is_output
        FROM sys.objects o
        JOIN sys.parameters p ON p.object_id = o.object_id
        JOIN sys.types t ON t.user_type_id = p.user_type_id
        WHERE o.name IN ({inlist})
        ORDER BY o.name, p.parameter_id""", cap=120)

    # ── P3. encryption + object type ─────────────────────────────────────────────
    rule("P3. type + encryption (encrypted => can't read source, but TVFs still EXECUTE)")
    run(cur, "P3. sys.objects", f"""
        SELECT name, type_desc, OBJECTPROPERTY(object_id,'IsEncrypted') AS IsEncrypted
        FROM sys.objects WHERE name IN ({inlist}) ORDER BY name""", cap=60)

    # ── P4. sample call of the readiness TVF for 250250 / machine 10 ─────────────
    rule("P4. SAMPLE CALL of udfEngStructuredReadiness (250250 / 10) — try likely signatures")
    for sig in [f"({SAMPLE_PROJECT})",
                f"({SAMPLE_PROJECT}, {SAMPLE_MACHINE})",
                f"({SAMPLE_PROJECT}, {SAMPLE_MACHINE}.0)",
                f"({SAMPLE_PROJECT}, NULL)"]:
        cols, rows = run(cur, f"P4. SELECT TOP 20 * FROM dbo.udfEngStructuredReadiness{sig}",
                         f"SELECT TOP 20 * FROM dbo.udfEngStructuredReadiness{sig}", cap=20)
        if cols:
            break   # first signature that works shows the readiness columns + data

    eto.close()
    print("\nDONE — paste everything above.")


if __name__ == "__main__":
    main()
