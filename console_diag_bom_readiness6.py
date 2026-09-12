"""
console_diag_bom_readiness6.py — FINAL: explode the readiness report and lock the column mapping to
the PDF.  READ-ONLY (EXECs the vendor report procs, which only SELECT).  (2026-09-12)

Probe 5 proved the procs are callable and that the SINGLE wrong arg was @intNumberOfLevels=0 (explode
0 levels → top node only). The target PDF ("Structured BOM - Readiness Detailed Report") shows:
  Part Number - UOM - Description | Assembly Qty | Total Qty | Avail. Qty | Proc. Qty | To Be Proc.
  | % Avail.(Absolute) | Bin
and BinLabel exists ONLY in crp0470EngStructuredReadiness.

This probe EXECs the two best procs with @intNumberOfLevels = 99 (full explode) and prints, for the
first ~35 exploded rows, exactly the columns that map to the PDF — so we can (a) confirm the row set
matches the PDF's opening rows (ELECTRICAL SCOPE → MCP → CABINET → E04011 …) and (b) nail which raw
column is "Proc. Qty".

Full explode args: (ProjectID, SpecID, AssemblyStructureID=0, ExplodeStandardAssemblies=1,
WeightMethod=0, AssembliesOnly=0, HideFullyAvailable=0, NumberOfLevels=99, IndentSpaces=3,
AverageWithBOMQty=0).

Run from the repo root:
    python console_diag_bom_readiness6.py
Paste the WHOLE output back.
"""
SAMPLE_PROJECT = 250250
SAMPLE_MACHINE = 10
ARGS = [SAMPLE_PROJECT, SAMPLE_MACHINE, 0, 1, 0, 0, 0, 99, 3, 0]  # NumberOfLevels=99 is the fix
# columns we want to see, if present (mapped to the PDF)
WANT = ["Depth", "PaddedPartNumber", "ItemCompanyID", "UOMType", "ItemDescription",
        "ItemQty",                       # -> Assembly Qty
        "TotalRequiredForEntireAssy",    # -> Total Qty
        "TotalAvailable",                # -> Avail. Qty
        "PurchaseQty", "OnOrder", "Received",  # candidates for Proc. Qty
        "ToBeProcured",                  # -> To Be Proc.
        "PercentageComplete_Absolute_Assy",  # -> % Avail.
        "BinLabel"]                      # -> Bin (only in crp0470EngStructuredReadiness)


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
    print("\n" + "=" * 100 + f"\n{t}\n" + "=" * 100)


def trunc(v, n=34):
    s = "" if v is None else str(v)
    return s if len(s) <= n else s[:n - 1] + "…"


def exec_explode(cur, name):
    ph = ", ".join("?" for _ in ARGS)
    print(f"\n-- EXEC {name} with NumberOfLevels=99  args={ARGS}")
    try:
        cur.execute(f"{{CALL dbo.{name}({ph})}}", ARGS)
        setno = 0
        while True:
            setno += 1
            if cur.description is not None:
                cols = [d[0] for d in cur.description]
                rows = cur.fetchall()
                if rows:
                    idx = {c: cols.index(c) for c in WANT if c in cols}
                    print(f"   result set {setno}: {len(rows)} rows — key columns:")
                    print("     " + " | ".join(idx.keys()))
                    for r in rows[:35]:
                        print("     " + " | ".join(trunc(r[i]) for i in idx.values()))
                    print(f"   ... ({len(rows)} rows total; PDF is 31 pages)")
                    hasbin = "BinLabel" in idx and any(r[idx['BinLabel']] for r in rows)
                    print(f"   >>> BinLabel present: {'BinLabel' in idx}; any populated: {hasbin}")
                else:
                    print(f"   result set {setno}: 0 rows")
            else:
                print(f"   result set {setno}: (no columns)")
            if not cur.nextset():
                break
    except Exception as e:
        print(f"   !! {type(e).__name__}: {e}")


def main():
    eto = eto_connect()
    cur = eto.cursor()

    rule("A. crp0470EngStructuredReadiness (has BinLabel) — the likely PDF data proc")
    exec_explode(cur, "crp0470EngStructuredReadiness")

    rule("B. urpEngStructuredReadinessBySpec (clean, no Bin) — fallback / cross-check of the numbers")
    exec_explode(cur, "urpEngStructuredReadinessBySpec")

    eto.close()
    print("\nDONE — paste everything above.")


if __name__ == "__main__":
    main()
