"""
console_diag_bom_readiness9.py — find the machine's ROOT assembly id and explode the BOM by it.
READ-ONLY.  (2026-09-13)

Every readiness call returns only the top node because AssemblyStructureID=0 = "just this node".
The on-prem report explodes a specific assembly. This probe finds the machine's ROOT (the ItemID
that is a parent but never a child) and every plausible id for it, then feeds each as
@intAssemblyStructureID at NumberOfLevels=99 to find the one that explodes the tree.

  1. ROOT ItemID = ParentID that never appears as a ChildID for 250250/10.
  2. Candidate assembly ids: the root ItemID; any StructureID whose ChildID = root; the StructureIDs
     of the root's direct children (the scope assemblies).
  3. For urpEngStructuredReadinessBySpec AND crp0470StructuredBOMReadinessDetailedPS, call with each
     candidate as @intAssemblyStructureID (NumberOfLevels=99) and print row counts.
  4. Dump columns + first 15 rows of the first combo that explodes.

Run:  python console_diag_bom_readiness9.py   — paste the WHOLE output.
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


def q(cur, sql):
    cur.execute(sql)
    return cur.fetchall()


def call(cur, proc, asm, levels=99):
    args = [P, S, asm, 1, 0, 0, 0, levels, 3, 0]
    cur.execute(f"{{CALL dbo.{proc}(?,?,?,?,?,?,?,?,?,?)}}", args)
    cols, rows = [], []
    while True:
        if cur.description is not None:
            cols = [d[0] for d in cur.description]
            rows = cur.fetchall()
            if rows:
                break
        if not cur.nextset():
            break
    return cols, rows


def main():
    eto = eto_connect()
    cur = eto.cursor()

    rule(f"1. Structure roots & candidate assembly ids for {P}/{S}")
    cands = []
    try:
        roots = q(cur, f"SELECT DISTINCT ParentID FROM dbo.vwEngProductStructure "
                       f"WHERE ProjectID={P} AND SpecID={S} AND ParentID NOT IN "
                       f"(SELECT ChildID FROM dbo.vwEngProductStructure WHERE ProjectID={P} AND SpecID={S})")
        root_ids = [int(r[0]) for r in roots if r[0] is not None]
        print(f"   ROOT ItemID(s) (parent never a child): {root_ids}")
        cands += root_ids
        for rid in root_ids:
            # structure rows where the root is the CHILD (its own edge, if any)
            sr = q(cur, f"SELECT StructureID, ParentID, ChildID, ItemCompanyID, ItemDescription "
                        f"FROM dbo.vwEngProductStructure WHERE ProjectID={P} AND SpecID={S} AND ChildID={rid}")
            for r in sr:
                print("   root-as-child row: " + " | ".join("" if v is None else str(v) for v in r))
                cands.append(int(r[0]))
            # the root's direct children (scope assemblies) — their StructureIDs
            kids = q(cur, f"SELECT StructureID, ChildID, ItemCompanyID, ItemDescription "
                          f"FROM dbo.vwEngProductStructure WHERE ProjectID={P} AND SpecID={S} AND ParentID={rid} "
                          f"ORDER BY StructureID")
            print(f"   root {rid} direct children:")
            for r in kids[:12]:
                print("     " + " | ".join("" if v is None else str(v) for v in r))
            cands += [int(r[0]) for r in kids]
            cands += [int(r[1]) for r in kids]   # also try the child ItemIDs
    except Exception as e:
        print(f"   !! {type(e).__name__}: {e}")
    cands = list(dict.fromkeys(cands))          # de-dup, keep order
    print(f"\n   candidate @intAssemblyStructureID values to try: {cands}")

    rule("2. Explode attempts — @intAssemblyStructureID = each candidate, NumberOfLevels=99")
    winner = None
    for proc in PROCS:
        for asm in cands:
            try:
                cols, rows = call(cur, proc, asm)
                flag = "  <<< EXPLODES" if len(rows) > 1 else ""
                print(f"   {proc[:34]:34} @asm={asm:>8} -> {len(rows)} row(s){flag}")
                if len(rows) > 1 and winner is None:
                    winner = (proc, asm, cols, rows)
            except Exception as e:
                print(f"   {proc[:34]:34} @asm={asm:>8} -> !! {type(e).__name__}: {e}")

    rule("3. FIRST exploding combo — columns + first 15 rows")
    if winner:
        proc, asm, cols, rows = winner
        print(f"   WINNER: {proc}  @intAssemblyStructureID={asm}  ({len(rows)} rows)")
        idx = {c: cols.index(c) for c in KEY if c in cols}
        print("   " + " | ".join(idx.keys()))
        for r in rows[:15]:
            print("   " + " | ".join(str(r[i]) for i in idx.values()))
        print("\n   ALL COLUMNS:", ", ".join(cols))
    else:
        print("   (still nothing exploded — the proc likely needs a POPULATE step or a different\n"
              "    parameterization; next step is to read its definition in SSMS under your login:\n"
              "    SELECT OBJECT_DEFINITION(OBJECT_ID('dbo.crp0470StructuredBOMReadinessDetailedPS'));)")

    eto.close()
    print("\nDONE — paste everything above.")


if __name__ == "__main__":
    main()
