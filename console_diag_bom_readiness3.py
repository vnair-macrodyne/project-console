"""
console_diag_bom_readiness3.py — final BOM probe (2026-09-12).  READ-ONLY. Nothing is written.

We now know udfEngStructuredReadiness takes 7 args and returns the readiness fields, and that the
report proc crp0470StructuredBOMReadinessDetailedPS is NOT encrypted. This probe:
  1. prints the FULL DEFINITIONS of the report/by-spec procs (exact column mapping incl. Bin source
     and the default arguments the report passes), and
  2. does a REAL 7-argument call of udfEngStructuredReadiness for 250250 / machine 10 and shows the
     key readiness columns, so we can validate against the PDF before building.

Run where the other console_diag_*.py scripts run (ETO reachable):
    python console_diag_bom_readiness3.py
Paste the WHOLE output back.
"""
SAMPLE_PROJECT = 250250
SAMPLE_MACHINE = 10
DEF_OBJS = ["urpEngStructuredReadinessBySpec", "crp0470StructuredBOMReadinessDetailedPS",
            "urpEngStructuredReadiness_ForReferenceOnly", "crp0470EngStructuredReadiness"]
# 7-arg signatures to try: (ProjectID, SpecID, AssemblyStructureID, ExplodeStdAssy, WeightMethod,
# IndentSpaces, AverageWithBOMQty). AssemblyStructureID 0/NULL = whole machine.
CALL_SIGS = [
    f"({SAMPLE_PROJECT}, {SAMPLE_MACHINE}, 0, 1, 0, 0, 0)",
    f"({SAMPLE_PROJECT}, {SAMPLE_MACHINE}, NULL, 1, 0, 0, 0)",
    f"({SAMPLE_PROJECT}, {SAMPLE_MACHINE}, 0, 1, 1, 3, 1)",
    f"({SAMPLE_PROJECT}, {SAMPLE_MACHINE}, 0, 0, 0, 0, 0)",
]
KEY_COLS = ("Depth", "ParentID", "ChildID", "ItemCompanyID", "UOMType", "CategoryDescription",
            "ItemQty", "TotalRequiredForEntireAssy", "TotalRequiredForEntireBOM", "TotalAvailable",
            "PurchaseQty", "Received", "OnOrder", "PulledQty", "ToBeProcured", "RequiredQty",
            "PercentageComplete_Absolute_Assy", "PercentageComplete")


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


def main():
    eto = eto_connect()
    cur = eto.cursor()

    # ── 1. FULL definitions (printed raw so the multi-line SQL comes through) ─────
    rule("1. DEFINITIONS of the readiness report procs (exact column mapping + Bin + default args)")
    for nm in DEF_OBJS:
        print("\n" + "-" * 84 + f"\n----- {nm} -----\n" + "-" * 84)
        try:
            cur.execute("SELECT OBJECT_DEFINITION(OBJECT_ID(?))", (nm,))
            row = cur.fetchone()
            print(row[0] if row and row[0] else "(definition NULL — encrypted or not found)")
        except Exception as e:
            print(f"!! {type(e).__name__}: {e}")

    # ── 2. Real 7-arg call of the readiness TVF for the sample machine ───────────
    rule(f"2. udfEngStructuredReadiness — real call for {SAMPLE_PROJECT} / machine {SAMPLE_MACHINE}")
    sel = ", ".join(KEY_COLS)
    for sig in CALL_SIGS:
        print(f"\n-- try udfEngStructuredReadiness{sig}")
        try:
            cur.execute(f"SELECT TOP 40 {sel} FROM dbo.udfEngStructuredReadiness{sig} "
                        f"ORDER BY HierarchySortKey")
            cols = [d[0] for d in cur.description]
            rows = cur.fetchall()
            print("   " + " | ".join(cols))
            for r in rows:
                print("   " + " | ".join("" if v is None else str(v) for v in r))
            print(f"   ({len(rows)} row(s))")
            if rows:
                break     # first working signature is enough
        except Exception as e:
            print(f"   !! {type(e).__name__}: {e}")

    eto.close()
    print("\nDONE — paste everything above.")


if __name__ == "__main__":
    main()
