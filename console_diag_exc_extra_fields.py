"""
console_diag_exc_extra_fields.py — find the source columns for two more Exception-report fields:
a CRITICAL flag (on the PO line or the item) and DRAWING NUMBER.  READ-ONLY.  Nothing written.
(2026-09-12)

The user wants, on the Exception report: a Critical flag ("might be on the regular PO or attached to
the item"), and Drawing Number. This probe:
  1. Searches EVERY table/view for a column named like '%Critical%' (distinctive word) + samples it.
  2. Finds '%Drawing%' columns on the item master / PO / product-structure objects + samples them, so
     we see whether it's a clean drawing NUMBER or a file path (vwEngProductStructure.Drawing looked
     like a path).
  3. Dumps the PO-line and PO-header CUSTOM fields (PurchaseOrderDetailCustom* / PurchaseOrderCustom*)
     with sample values — Critical / Drawing may be a PO custom flag/field.

Run from the repo root:
    python console_diag_exc_extra_fields.py [projectID]
Paste the WHOLE output back.
"""
import sys
SAMPLE_PROJECT = int(sys.argv[1]) if len(sys.argv) > 1 else 250250

# objects we care about for Drawing / PO custom fields
PO_OBJS = ["vwPurchaseOrderDetails", "vwPurchaseOrderDetailsDetailed", "vwPurchaseOrderHeader",
           "tblPurchaseOrderDetails", "tblPurchaseOrderHeader"]
ITEM_OBJS = ["tblEngItemMaster", "vwEngItemMaster", "vwEngBOM", "vwEngProductStructure"]


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


def run(cur, label, sql, cap=25):
    print(f"\n-- {label}")
    try:
        cur.execute(sql)
        if cur.description is None:
            print("   (no result set)"); return []
        cols = [d[0] for d in cur.description]
        rows = cur.fetchall()
        print("   " + " | ".join(cols))
        for r in rows[:cap]:
            print("   " + " | ".join("" if v is None else str(v)[:60] for v in r))
        print(f"   ({len(rows)} row(s))")
        return rows
    except Exception as e:
        print(f"   !! {type(e).__name__}: {e}")
        return []


def cols_of(cur, obj, like):
    cur.execute("SELECT COLUMN_NAME, DATA_TYPE FROM INFORMATION_SCHEMA.COLUMNS "
                "WHERE TABLE_NAME=? AND COLUMN_NAME LIKE ? ORDER BY ORDINAL_POSITION", (obj, like))
    return [(r[0], r[1]) for r in cur.fetchall()]


def sample_col(cur, obj, col):
    run(cur, f"   {obj}.{col} — top distinct non-null",
        f"SELECT TOP 8 [{col}] AS val, COUNT(*) AS n FROM dbo.{obj} "
        f"WHERE [{col}] IS NOT NULL GROUP BY [{col}] ORDER BY n DESC", cap=8)


def main():
    eto = eto_connect()
    cur = eto.cursor()

    # ── 1. CRITICAL flag anywhere ────────────────────────────────────────────────
    rule("1. Any column named like '%Critical%' (table/view) + sample")
    crit = run(cur, "1a. all Critical-named columns", """
        SELECT TABLE_NAME, COLUMN_NAME, DATA_TYPE FROM INFORMATION_SCHEMA.COLUMNS
        WHERE COLUMN_NAME LIKE '%Critical%' ORDER BY TABLE_NAME, COLUMN_NAME""", cap=100)
    for tbl, col, _dt in [(r[0], r[1], r[2]) for r in crit]:
        if tbl in PO_OBJS + ITEM_OBJS or tbl.startswith(("tblPurchase", "tblEngItem", "vwPurchase", "vwEngItem")):
            sample_col(cur, tbl, col)

    # ── 2. DRAWING columns on item / PO / structure ──────────────────────────────
    rule("2. '%Drawing%' columns on item / PO / structure (+ sample to see NUMBER vs file path)")
    for obj in ITEM_OBJS + PO_OBJS:
        for col, dt in cols_of(cur, obj, "%Drawing%"):
            print(f"\n   [{obj}] {col} : {dt}")
            sample_col(cur, obj, col)
    # also the plain item number / rev on the item master for reference
    run(cur, "2b. item master identity columns (for 'drawing number' candidates)",
        "SELECT COLUMN_NAME, DATA_TYPE FROM INFORMATION_SCHEMA.COLUMNS "
        "WHERE TABLE_NAME='tblEngItemMaster' AND (COLUMN_NAME LIKE '%Drawing%' "
        "OR COLUMN_NAME LIKE '%Rev%' OR COLUMN_NAME LIKE '%Print%' OR COLUMN_NAME LIKE '%Doc%') "
        "ORDER BY COLUMN_NAME", cap=40)

    # ── 3. PO custom fields (Critical / Drawing may live here) ───────────────────
    rule("3. PO custom fields + sample (Critical/Drawing may be a PO custom)")
    for obj in ("vwPurchaseOrderDetails", "tblPurchaseOrderDetails", "vwPurchaseOrderHeader",
                "tblPurchaseOrderHeader"):
        customs = cols_of(cur, obj, "%Custom%")
        if not customs:
            continue
        print(f"\n   {obj} custom columns: " + ", ".join(f"{c}({t})" for c, t in customs))
    # sample the DETAIL customs (most likely to carry a per-line Critical flag / drawing)
    for col, dt in cols_of(cur, "vwPurchaseOrderDetails", "%Custom%"):
        sample_col(cur, "vwPurchaseOrderDetails", col)

    eto.close()
    print("\nDONE — paste everything above.")


if __name__ == "__main__":
    main()
