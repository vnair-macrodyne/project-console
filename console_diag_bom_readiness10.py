"""
console_diag_bom_readiness10.py — map each PDF column to the exact proc column, and see what feeds
"Avail Qty".  READ-ONLY.  (2026-09-13)

Explodes the ELECTRICAL scope of 250250/10 and dumps ALL quantity columns for the specific items on
page 1 of the sample PDF, so we can line each PDF column up with a proc column:

  PDF page 1 (for reference):
    E04011  Assy 3  Total 3  Avail 3  Proc 3  ToBeProc 0   %100
    E06718  Assy 2  Total 2  Avail 3  Proc 3  ToBeProc (1) %100
    E06745  Assy 2  Total 2  Avail 0  Proc 2  ToBeProc 0   %0
    E09452  Assy 1  Total 1  Avail 0  Proc 1  ToBeProc 1   %0
    E00567  Assy 1  Total 1  Avail 1  Proc 1  ToBeProc (1) %100

We print, per item: ItemQty, TotalRequiredForEntireAssy, TotalAvailable, PurchaseQty, Received,
OnOrder, PulledQty, Reserved, RequiredQty, ToBeProcured, OutstandingQty, TotalQtyReleased,
PercentageComplete_Absolute_Assy — so "Proc Qty" and "Avail Qty" are pinned to real columns.

Run:  python console_diag_bom_readiness10.py   — paste the WHOLE output.
"""
P, S, SCOPE = 250250, 10, 224093        # 224093 = the ELECTRICAL scope StructureID for 250250/10
PROC = "urpEngStructuredReadinessBySpec"
ITEMS = {"E04011", "E06718", "E06745", "E09452", "E00567"}
SHOW = ["ItemCompanyID", "Depth", "ItemQty", "TotalRequiredForEntireAssy", "TotalAvailable",
        "PurchaseQty", "Received", "OnOrder", "PulledQty", "Reserved", "RequiredQty",
        "ToBeProcured", "OutstandingQty", "TotalQtyReleased", "PercentageComplete_Absolute_Assy"]


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


def main():
    eto = eto_connect()
    cur = eto.cursor()
    args = [P, S, SCOPE, 1, 0, 0, 0, 99, 3, 0]
    cur.execute(f"{{CALL dbo.{PROC}(?,?,?,?,?,?,?,?,?,?)}}", args)
    cols, rows = [], []
    while True:
        if cur.description is not None:
            cols = [d[0] for d in cur.description]
            rows = cur.fetchall()
            if rows:
                break
        if not cur.nextset():
            break
    idx = {c: cols.index(c) for c in SHOW if c in cols}
    print("Columns present:", [c for c in SHOW if c in cols])
    print("\nItem      | " + " | ".join(c for c in SHOW[1:] if c in idx))
    for r in rows:
        ic = str(r[cols.index("ItemCompanyID")] or "").strip()
        if ic in ITEMS:
            vals = [("" if r[idx[c]] is None else str(r[idx[c]])) for c in SHOW[1:] if c in idx]
            print(f"{ic:9} | " + " | ".join(vals))
    eto.close()
    print("\nDONE — paste everything above.")


if __name__ == "__main__":
    main()
