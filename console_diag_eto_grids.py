"""
console_diag_eto_grids.py — where do ETO's own purchasing grids get their numbers?  READ-ONLY.  (2026-10-12)

Peter sent two ETO grid exports (8 Oct 2026) to define the procurement exception report:
  * "Items to Procure"  — columns Requested / Procured / Required / Available / On Open PO / RFQ / Action
                          (Required = Requested - Procured on all 459 rows) / Mfg. Begin Date / PS # ...
  * "Items on Order"    — open PO lines: Supplier, Qty, received / to be received, Required, Revised,
                          Mfg. Begin, Long Lead Item, PO Date ...
For project 250005 ETO's "Items to Procure" lists 30 lines (mostly machined / fabricated parts with RFQs);
Sextant's Lines to Order lists 354 (every released part not yet on a PO for its machine). ETO's
"Requested" quantity is not the release-log quantity we use. This probe finds the ETO objects behind
both grids, plus where "Mfg. Begin" and any "requisition" number live, so the report can follow ETO
rather than a reconstruction.

  G1  Views / tables / functions / procs whose COLUMNS include Requested + Procured (+ Required).
  G2  Objects whose NAME suggests the grids (Procure, ToOrder, OnOrder, ItemsOn, Purchasing...).
  G3  Every column named like Mfg*Begin, and its fill rate where it is a base-table column.
  G4  Every column named like *Requisition* / *ReqNo* / *Request*.
  G5  For each G1 candidate that has ProjectID: its rows for 250005, matched to the 30 rows of
      Peter's export (embedded below) on machine + part number + Requested/Procured/Required.
  G6  Definition text of the best candidates (if this account may read definitions).

Run from the repo root where ETO is reachable:   python console_diag_eto_grids.py
Paste the whole output back.
"""
import time

GRID_250005 = [(10.0, '250005-10M10.0.0.0-01', 1.0, 0.0, 1.0), (10.0, '250005-10M9.0.0.0-01', 1.0, 0.0, 1.0), (10.0, '250005-10M9.1.0.0-04', 1.0, 0.0, 1.0), (20.0, '250005-20A1.1.0.0-01', 4.0, 0.0, 4.0), (20.0, '250005-20A1.11.0.0-01', 1.0, 0.0, 1.0), (20.0, '250005-20A1.3.0.0-01', 1.0, 0.0, 1.0), (20.0, '250005-20A1.6.0.0-01', 1.0, 0.0, 1.0), (20.0, '250005-20A1.8.0.0-01', 1.0, 0.0, 1.0), (20.0, '250005-20A16.4.0.0-02', 2.0, 0.0, 2.0), (20.0, '250005-20A16.4.0.0-03', 2.0, 0.0, 2.0), (20.0, '250005-20A16.4.1.0-00', 1.0, 0.0, 1.0), (20.0, '250005-20A2.2.5.0-01', 45.0, 0.0, 45.0), (20.0, '250005-20A2.3.0.0-06', 4.0, 0.0, 4.0), (20.0, '250005-20A2.3.0.0-07', 8.0, 0.0, 8.0), (20.0, '250005-20A2.3.0.0-08', 4.0, 0.0, 4.0), (20.0, '250005-20A2.3.0.0-13', 6.0, 0.0, 6.0), (20.0, '250005-20A2.3.0.0-17', 4.0, 0.0, 4.0), (20.0, '250005-20A2.7.1.0-01', 1.0, 0.0, 1.0), (20.0, '250005-20A2.7.1.0-02', 1.0, 0.0, 1.0), (20.0, '250005-20A2.7.1.0-05', 1.0, 0.0, 1.0), (20.0, '250005-20A2.7.1.0-06', 2.0, 0.0, 2.0), (20.0, '250005-20A2.7.1.0-08', 2.0, 0.0, 2.0), (20.0, '250005-20A2.7.1.1-01', 8.0, 0.0, 8.0), (20.0, '250005-20A2.7.1.5-01', 2.0, 0.0, 2.0), (20.0, '6005-002', 4.0, 0.0, 4.0), (20.0, '6401A0.0.0.0-01', 1.0, 0.0, 1.0), (20.0, '6906A0.0.1.1-01 ', 4.0, 0.0, 4.0), (20.0, '8314M0.0.0.0-04', 12.0, 0.0, 12.0), (20.0, '8400M0.0.0.0-10', 8.0, 0.0, 8.0), (20.0, 'E13408', 1.0, 0.0, 1.0)]


def _f(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


def q(cur, sql):
    cur.execute(sql)
    cols = [d[0] for d in cur.description] if cur.description else []
    return cols, [tuple(r) for r in cur.fetchall()] if cols else []


def show(cur, label, sql, n=60):
    try:
        cols, rows = q(cur, sql)
        print(f"\n   {label}  ({len(rows)} row(s))")
        if cols:
            print("     " + " | ".join(cols))
        for r in rows[:n]:
            print("     " + " | ".join("" if v is None else str(v) for v in r))
        return cols, rows
    except Exception as e:
        print(f"   !! {label}: {type(e).__name__}: {e}")
        return [], []


def main():
    from console.infra.connections import eto_connection
    eto = eto_connection(); cur = eto.cursor()
    try:
        eto.timeout = 300
    except Exception:
        pass
    print(f"console_diag_eto_grids — {time.strftime('%Y-%m-%d %H:%M')}  (read-only)")

    print("\n== G1. Objects with columns Requested AND Procured")
    _, g1 = show(cur, "candidates", """
        SELECT o.name, o.type_desc,
               MAX(CASE WHEN c.name = 'Required' THEN 1 ELSE 0 END) AS HasRequired,
               MAX(CASE WHEN c.name = 'ProjectID' THEN 1 ELSE 0 END) AS HasProjectID,
               MAX(CASE WHEN c.name IN ('SpecID','Machine') THEN 1 ELSE 0 END) AS HasMachine,
               COUNT(*) AS Cols
        FROM sys.columns c JOIN sys.objects o ON o.object_id = c.object_id
        WHERE o.type IN ('U','V','IF','TF')
          AND o.object_id IN (SELECT object_id FROM sys.columns WHERE name LIKE 'Requested%')
          AND o.object_id IN (SELECT object_id FROM sys.columns WHERE name LIKE 'Procured%')
        GROUP BY o.name, o.type_desc ORDER BY o.name""")
    for r in g1[:12]:
        show(cur, f"columns of {r[0]}", f"""
            SELECT c.name, TYPE_NAME(c.user_type_id) AS type FROM sys.columns c
            WHERE c.object_id = OBJECT_ID('dbo.{r[0]}') ORDER BY c.column_id""", 120)

    print("\n== G2. Objects named like the grids")
    show(cur, "names", """
        SELECT name, type_desc FROM sys.objects
        WHERE type IN ('U','V','P','IF','TF','FN')
          AND (name LIKE '%Procure%' OR name LIKE '%ToOrder%' OR name LIKE '%OnOrder%' OR name LIKE '%ItemsOn%'
               OR name LIKE '%ItemsTo%' OR name LIKE '%PurchasingItem%' OR name LIKE '%Purchasing%Grid%'
               OR name LIKE 'vwPurchasing%' OR name LIKE '%Requested%')
        ORDER BY type_desc, name""", 120)

    print("\n== G3. Mfg Begin columns")
    _, g3 = show(cur, "columns", """
        SELECT o.name AS obj, o.type_desc, c.name AS col FROM sys.columns c JOIN sys.objects o ON o.object_id = c.object_id
        WHERE (c.name LIKE '%Mfg%Begin%' OR c.name LIKE '%MfgStart%' OR c.name LIKE '%ManufactureBegin%')
          AND o.type IN ('U','V') ORDER BY o.type_desc, o.name""", 80)
    for obj, typ, col in g3:
        if typ == 'USER_TABLE':
            show(cur, f"fill of {obj}.{col}", f"SELECT COUNT(*) AS Rows, SUM(CASE WHEN [{col}] IS NOT NULL THEN 1 ELSE 0 END) AS Filled FROM dbo.[{obj}]")

    print("\n== G4. Requisition / request columns")
    show(cur, "columns", """
        SELECT o.name AS obj, o.type_desc, c.name AS col FROM sys.columns c JOIN sys.objects o ON o.object_id = c.object_id
        WHERE (c.name LIKE '%Requisition%' OR c.name LIKE '%ReqNo%' OR c.name LIKE '%ReqID%' OR c.name LIKE 'Request%')
          AND o.type IN ('U','V') ORDER BY o.type_desc, o.name""", 80)

    print("\n== G5. Candidate rows for 250005 vs Peter's ETO export (30 rows)")
    grid = {(m, p.strip()): (rq, pr, req) for m, p, rq, pr, req in GRID_250005}
    for r in g1:
        name, typ, has_req, has_pid = r[0], r[1], r[2], r[3]
        if not has_pid or typ not in ('VIEW', 'USER_TABLE'):
            continue
        try:
            cols, rows = q(cur, f"SELECT TOP 5000 * FROM dbo.[{name}] WHERE ProjectID = 250005")
        except Exception as e:
            print(f"   !! {name}: {type(e).__name__}: {e}"); continue
        lc = [c.lower() for c in cols]
        def pick(*names):
            for n in names:
                if n.lower() in lc:
                    return lc.index(n.lower())
            return None
        i_spec = pick('SpecID', 'Machine'); i_part = pick('ItemCompanyID', 'PartNumber', 'ItemNumber')
        i_rq = pick('Requested'); i_pr = pick('Procured'); i_req = pick('Required')
        print(f"\n   {name}: {len(rows)} row(s) for 250005; key cols spec={i_spec} part={i_part} req={i_rq}/{i_pr}/{i_req}")
        if i_part is None:
            print("     (no part-number column — columns: " + ", ".join(cols) + ")"); continue
        pos = [x for x in rows if i_req is not None and x[i_req] is not None and _f(x[i_req]) != 0]
        print(f"     rows with Required <> 0: {len(pos)}")
        hit = exact = 0
        for (m, p), (rq, pr, req) in grid.items():
            cand = [x for x in rows if str(x[i_part]).strip() == p and (i_spec is None or _f(x[i_spec]) == m)]
            if cand:
                hit += 1
                x = cand[0]
                if i_rq is not None and i_pr is not None and _f(x[i_rq]) == rq and _f(x[i_pr]) == pr:
                    exact += 1
        print(f"     Peter's 30 rows found: {hit}; with identical Requested and Procured: {exact}")
        if pos:
            print("     first 8 rows with Required <> 0:")
            print("       " + " | ".join(cols[:16]))
            for x in pos[:8]:
                print("       " + " | ".join("" if v is None else str(v) for v in x[:16]))

    print("\n== G6. Definitions (first 60 lines) of the first 3 G1 candidates")
    for r in g1[:3]:
        try:
            _, d = q(cur, f"SELECT OBJECT_DEFINITION(OBJECT_ID('dbo.{r[0]}'))")
            text = d[0][0] if d and d[0][0] else None
            if not text:
                print(f"   {r[0]}: definition not readable with this account"); continue
            print(f"\n   --- {r[0]} ---")
            for ln in text.splitlines()[:60]:
                print("     " + ln.rstrip()[:200])
        except Exception as e:
            print(f"   !! {r[0]}: {type(e).__name__}: {e}")
    print("\nDONE — paste everything above.")


if __name__ == "__main__":
    main()
