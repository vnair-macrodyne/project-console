"""
console_diag_eto_grids2.py — read ETO's own purchasing-grid objects.  READ-ONLY.  (2026-10-12)

Take 1 found the objects behind Peter's two ETO grid exports (by name): vwPurchasingItemsToPurchase,
udf/uspPurchasingItemsToPurchase (+ ByInventoryLocation variants), udf/uspPurchasingItemsOnOrder, and
vwPurchasingDemand / Supply / Summary. It also confirmed ETO has NO requisition-number column anywhere,
and that Mfg Begin lives only on tblSpec (63 of 2,581 machines filled).

  H1  Columns of each view / table-valued function, parameters of each procedure and function.
  H2  vwPurchasingItemsToPurchase (and Demand / Supply / Summary if they carry ProjectID): rows for
      250005 matched to Peter's 30 exported rows on machine + part (+ quantities shown side by side).
  H3  uspPurchasingItemsToPurchase / uspPurchasingItemsOnOrder executed with the parameters H1 reveals,
      ONLY when every parameter has a default or is a project / filter we can supply; rows for 250005.
  H4  Definitions, if this account may read them (first 80 lines each).

Run:  python console_diag_eto_grids2.py     → paste the whole output.
"""
import time

GRID_250005 = [(10.0, '250005-10M10.0.0.0-01', 1.0, 0.0, 1.0), (10.0, '250005-10M9.0.0.0-01', 1.0, 0.0, 1.0), (10.0, '250005-10M9.1.0.0-04', 1.0, 0.0, 1.0), (20.0, '250005-20A1.1.0.0-01', 4.0, 0.0, 4.0), (20.0, '250005-20A1.11.0.0-01', 1.0, 0.0, 1.0), (20.0, '250005-20A1.3.0.0-01', 1.0, 0.0, 1.0), (20.0, '250005-20A1.6.0.0-01', 1.0, 0.0, 1.0), (20.0, '250005-20A1.8.0.0-01', 1.0, 0.0, 1.0), (20.0, '250005-20A16.4.0.0-02', 2.0, 0.0, 2.0), (20.0, '250005-20A16.4.0.0-03', 2.0, 0.0, 2.0), (20.0, '250005-20A16.4.1.0-00', 1.0, 0.0, 1.0), (20.0, '250005-20A2.2.5.0-01', 45.0, 0.0, 45.0), (20.0, '250005-20A2.3.0.0-06', 4.0, 0.0, 4.0), (20.0, '250005-20A2.3.0.0-07', 8.0, 0.0, 8.0), (20.0, '250005-20A2.3.0.0-08', 4.0, 0.0, 4.0), (20.0, '250005-20A2.3.0.0-13', 6.0, 0.0, 6.0), (20.0, '250005-20A2.3.0.0-17', 4.0, 0.0, 4.0), (20.0, '250005-20A2.7.1.0-01', 1.0, 0.0, 1.0), (20.0, '250005-20A2.7.1.0-02', 1.0, 0.0, 1.0), (20.0, '250005-20A2.7.1.0-05', 1.0, 0.0, 1.0), (20.0, '250005-20A2.7.1.0-06', 2.0, 0.0, 2.0), (20.0, '250005-20A2.7.1.0-08', 2.0, 0.0, 2.0), (20.0, '250005-20A2.7.1.1-01', 8.0, 0.0, 8.0), (20.0, '250005-20A2.7.1.5-01', 2.0, 0.0, 2.0), (20.0, '6005-002', 4.0, 0.0, 4.0), (20.0, '6401A0.0.0.0-01', 1.0, 0.0, 1.0), (20.0, '6906A0.0.1.1-01 ', 4.0, 0.0, 4.0), (20.0, '8314M0.0.0.0-04', 12.0, 0.0, 12.0), (20.0, '8400M0.0.0.0-10', 8.0, 0.0, 8.0), (20.0, 'E13408', 1.0, 0.0, 1.0)]
VIEWS = ["vwPurchasingItemsToPurchase", "vwPurchasingItemsToPurchaseByInventory", "vwPurchasingDemand",
         "vwPurchasingSupply", "vwPurchasingSummary", "vwPurchasingNonBOM"]
FUNCS = ["udfPurchasingItemsToPurchase", "udfPurchasingItemsToPurchaseByInventoryLocationSlim",
         "udfPurchasingItemsOnOrder"]
PROCS = ["uspPurchasingItemsToPurchase", "urpPurchasingItemsToPurchase", "uspPurchasingItemsOnOrder",
         "uspPurchasingItemsToPurchaseVerify"]


def _f(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def q(cur, sql):
    cur.execute(sql)
    while cur.description is None:
        if not cur.nextset():
            return [], []
    cols = [d[0] for d in cur.description]
    return cols, [tuple(r) for r in cur.fetchall()]


def show(cur, label, sql, n=40):
    try:
        cols, rows = q(cur, sql)
        print(f"\n   {label}  ({len(rows)} row(s))")
        print("     " + " | ".join(cols))
        for r in rows[:n]:
            print("     " + " | ".join("" if v is None else str(v) for v in r))
        return cols, rows
    except Exception as e:
        print(f"   !! {label}: {type(e).__name__}: {e}")
        return [], []


def compare(cols, rows, label):
    lc = [c.lower() for c in cols]
    def pick(*names):
        for n in names:
            if n.lower() in lc:
                return lc.index(n.lower())
        return None
    i_pid = pick("ProjectID", "Project")
    i_spec = pick("SpecID", "Machine")
    i_part = pick("ItemCompanyID", "PaddedPartNumber", "PartNumber", "ItemNumber")
    mine = [r for r in rows if i_pid is None or _f(r[i_pid]) == 250005]
    print(f"\n   {label}: {len(mine)} row(s) for 250005 (project col {i_pid}, machine col {i_spec}, part col {i_part})")
    if i_part is None:
        return
    keyset = {(_f(r[i_spec]) if i_spec is not None else None, str(r[i_part]).strip()) for r in mine}
    hit = [g for g in GRID_250005 if ((g[0] if i_spec is not None else None), g[1]) in keyset]
    print(f"     Peter's 30 rows found: {len(hit)}")
    miss = [g[1] for g in GRID_250005 if g not in hit]
    if miss:
        print("     not found: " + ", ".join(miss[:12]))
    shown = 0
    for g in GRID_250005[:6]:
        for r in mine:
            if str(r[i_part]).strip() == g[1] and (i_spec is None or _f(r[i_spec]) == g[0]):
                print(f"     ETO export {g[1]} m{g[0]:g}: Requested {g[2]:g} Procured {g[3]:g} Required {g[4]:g}")
                print("       this object: " + " | ".join(f"{c}={v}" for c, v in zip(cols, r) if v not in (None, "")))
                shown += 1
                break
    extra = len(mine) - len(hit)
    print(f"     rows here but not in Peter's export: {extra}")


def main():
    from console.infra.connections import eto_connection
    eto = eto_connection(); cur = eto.cursor()
    try:
        eto.timeout = 300
    except Exception:
        pass
    print(f"console_diag_eto_grids2 — {time.strftime('%Y-%m-%d %H:%M')}  (read-only)")

    print("\n== H1. Columns and parameters")
    for o in VIEWS + FUNCS:
        show(cur, f"columns of {o}", f"SELECT c.name, TYPE_NAME(c.user_type_id) AS type FROM sys.columns c "
                                     f"WHERE c.object_id = OBJECT_ID('dbo.{o}') ORDER BY c.column_id", 150)
    params = {}
    for o in FUNCS + PROCS:
        cols, rows = show(cur, f"parameters of {o}", f"SELECT name, TYPE_NAME(user_type_id) AS type, has_default_value "
                                                   f"FROM sys.parameters WHERE object_id = OBJECT_ID('dbo.{o}') AND parameter_id > 0 "
                                                   f"ORDER BY parameter_id")
        params[o] = rows

    print("\n== H2. Views: rows for 250005 vs Peter's export")
    for v in VIEWS:
        try:
            cols, rows = q(cur, f"SELECT TOP 1 * FROM dbo.{v}")
        except Exception as e:
            print(f"   !! {v}: {type(e).__name__}: {e}"); continue
        if "ProjectID" in cols:
            try:
                cols, rows = q(cur, f"SELECT * FROM dbo.{v} WHERE ProjectID = 250005")
                compare(cols, rows, v)
            except Exception as e:
                print(f"   !! {v}: {type(e).__name__}: {e}")
        else:
            print(f"\n   {v}: no ProjectID column — columns: " + ", ".join(cols))

    print("\n== H3. Procedures / functions run with project 250005 where the parameters allow")
    for o in FUNCS + PROCS:
        ps = params.get(o) or []
        args, ok = [], True
        for name, typ, has_def in ps:
            n = name.lower()
            if "project" in n:
                args.append(f"{name}=250005" if o in PROCS else "250005")
            elif has_def:
                if o in PROCS:
                    continue
                args.append("DEFAULT")
            else:
                ok = False
                print(f"   {o}: skipped — parameter {name} ({typ}) has no default and is not a project id")
                break
        if not ok:
            continue
        sql = (f"SET NOCOUNT ON; EXEC dbo.{o} " + ", ".join(args)) if o in PROCS else \
              f"SELECT * FROM dbo.{o}(" + ", ".join(args) + ")"
        print(f"\n   running: {sql}")
        t0 = time.time()
        try:
            cols, rows = q(cur, sql)
            print(f"     {len(rows)} row(s) in {time.time() - t0:.1f}s; columns: " + ", ".join(cols))
            compare(cols, rows, o)
        except Exception as e:
            print(f"   !! {o}: {type(e).__name__}: {e}")

    print("\n== H4. Definitions")
    for o in ["vwPurchasingItemsToPurchase", "udfPurchasingItemsToPurchase", "uspPurchasingItemsToPurchase",
              "udfPurchasingItemsOnOrder", "uspPurchasingItemsOnOrder"]:
        try:
            _, d = q(cur, f"SELECT OBJECT_DEFINITION(OBJECT_ID('dbo.{o}'))")
            text = d[0][0] if d and d[0][0] else None
            if not text:
                print(f"   {o}: definition not readable with this account"); continue
            print(f"\n   --- {o} ---")
            for ln in text.splitlines()[:80]:
                print("     " + ln.rstrip()[:200])
        except Exception as e:
            print(f"   !! {o}: {type(e).__name__}: {e}")
    print("\nDONE — paste everything above.")


if __name__ == "__main__":
    main()
