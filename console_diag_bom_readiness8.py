"""
console_diag_bom_readiness8.py — pick the WORKING readiness proc and find the arg that EXPLODES it.
READ-ONLY.  (2026-09-13)

Probe 7 proved crp0470EngStructuredReadiness returns 0 rows (a Crystal wrapper — wrong choice). The
procs that DO return data (probe 5) are urpEngStructuredReadinessBySpec and
crp0470StructuredBOMReadinessDetailedPS, but each returned only the TOP node at NumberOfLevels=0.
This probe finds the arg that explodes them for 250250 / machine 10:

  1. Finds the machine's TOP node (StructureID + ChildID/ItemID) in vwEngProductStructure.
  2. For BOTH working procs, sweeps @intNumberOfLevels (0,1,2,3,5,10,50,99) at AssemblyStructureID=0,
     printing the row count for each.
  3. For BOTH, tries @intAssemblyStructureID = the top StructureID AND = the top ChildID (ItemID),
     at NumberOfLevels=99, printing row counts — in case explosion is driven by the assembly id, not
     the level count.
  4. For the first combo that returns many rows, dumps the columns + first 12 rows so we can map them.

Run where the other console_diag_*.py scripts run:
    python console_diag_bom_readiness8.py
Paste the WHOLE output back.
"""
P, S = 250250, 10
PROCS = ["urpEngStructuredReadinessBySpec", "crp0470StructuredBOMReadinessDetailedPS"]
KEY = ("Depth", "PaddedPartNumber", "ItemCompanyID", "UOMType", "ItemDescription", "ItemQty",
       "TotalRequiredForEntireAssy", "TotalAvailable", "PurchaseQty", "ToBeProcured",
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
    print("\n" + "=" * 92 + f"\n{t}\n" + "=" * 92)


def call(cur, proc, asm, levels, explode=1, assy_only=0, hide=0, weight=0):
    """Positional {CALL}: (ProjectID, SpecID, AssemblyStructureID, ExplodeStdAssy, WeightMethod,
    AssembliesOnly, HideFullyAvailable, NumberOfLevels, IndentSpaces, AverageWithBOMQty)."""
    args = [P, S, asm, explode, weight, assy_only, hide, levels, 3, 0]
    cur.execute(f"{{CALL dbo.{proc}(?,?,?,?,?,?,?,?,?,?)}}", args)
    cols, rows = None, []
    while True:
        if cur.description is not None:
            cols = [d[0] for d in cur.description]
            rows = cur.fetchall()
            if rows:
                break
        if not cur.nextset():
            break
    return cols or [], rows


def main():
    eto = eto_connect()
    cur = eto.cursor()

    # ── 1. the machine's top node ───────────────────────────────────────────────
    rule(f"1. TOP node for {P}/{S} (vwEngProductStructure)")
    top_sid = top_child = 0
    try:
        cur.execute(f"SELECT StructureID, ParentID, ChildID, ItemCompanyID, ItemDescription "
                    f"FROM dbo.vwEngProductStructure WHERE ProjectID={P} AND SpecID={S} "
                    f"AND (ParentID=0 OR ParentID IS NULL) ORDER BY StructureID")
        rows = cur.fetchall()
        for r in rows:
            print("   " + " | ".join("" if v is None else str(v) for v in r))
        if rows:
            top_sid, top_child = int(rows[0][0]), int(rows[0][2])
        print(f"   -> top StructureID={top_sid}, top ChildID(ItemID)={top_child}")
    except Exception as e:
        print(f"   !! {type(e).__name__}: {e}")

    winner = None
    # ── 2. NumberOfLevels sweep, AssemblyStructureID=0 ──────────────────────────
    rule("2. NumberOfLevels sweep at AssemblyStructureID=0 — row counts")
    for proc in PROCS:
        print(f"\n   {proc}:")
        for lv in (0, 1, 2, 3, 5, 10, 50, 99):
            try:
                cols, rows = call(cur, proc, 0, lv)
                print(f"      NumberOfLevels={lv:>3} -> {len(rows)} row(s)")
                if len(rows) > 1 and winner is None:
                    winner = (proc, 0, lv, cols, rows)
            except Exception as e:
                print(f"      NumberOfLevels={lv:>3} -> !! {type(e).__name__}: {e}")

    # ── 3. drive by AssemblyStructureID (top StructureID and top ItemID) ─────────
    rule("3. AssemblyStructureID variations at NumberOfLevels=99 — row counts")
    for proc in PROCS:
        for label, asm in (("StructureID", top_sid), ("ChildID/ItemID", top_child)):
            try:
                cols, rows = call(cur, proc, asm, 99)
                print(f"   {proc} @asm={asm} ({label}) -> {len(rows)} row(s)")
                if len(rows) > 1 and winner is None:
                    winner = (proc, asm, 99, cols, rows)
            except Exception as e:
                print(f"   {proc} @asm={asm} ({label}) -> !! {type(e).__name__}: {e}")

    # ── 4. dump the winning combo ───────────────────────────────────────────────
    rule("4. FIRST exploding combo — columns + first 12 rows")
    if winner:
        proc, asm, lv, cols, rows = winner
        print(f"   WINNER: {proc}  AssemblyStructureID={asm}  NumberOfLevels={lv}  ({len(rows)} rows)")
        idx = {c: cols.index(c) for c in KEY if c in cols}
        print("   " + " | ".join(idx.keys()))
        for r in rows[:12]:
            print("   " + " | ".join(str(r[i]) for i in idx.values()))
        print("\n   ALL COLUMNS:", ", ".join(cols))
    else:
        print("   (nothing exploded — none of the combos returned more than the top node)")

    eto.close()
    print("\nDONE — paste everything above.")


if __name__ == "__main__":
    main()
