"""
console_diag_suppliers.py — active suppliers + addresses (discover schema, then run it) (2026-08-14)

Suppliers/vendors and customers all live in ETO's `tblCompany` (CompanyID, CName). We need the
ACTIVE flag, the SUPPLIER/VENDOR flag, and the ADDRESS columns — none of which the console currently
references. This probe:
  A. dumps tblCompany's columns, flagging the active / supplier / address-ish ones;
  B. auto-detects those columns and PRINTS the SELECT it will use;
  C. RUNS that query (active suppliers + address) and shows a sample + the row count;
  D. as a fallback, checks for a separate company-address table / a vwCompany|vwSupplier view.

If C returns rows, that IS your query (printed in B — copy it). If a guess is wrong, A's column
list shows the real name to drop in. READ-ONLY.  Run:  python console_diag_suppliers.py  → paste.
"""
ACTIVE_HINTS = ("cactive", "active", "isactive", "companyactive", "inactive")
SUPPLIER_HINTS = ("supplier", "vendor")
NAME_HINTS = ("cname", "companyname", "name")
ADDR_HINTS = ("address", "addr", "street", "city", "prov", "state", "region",
              "zip", "postal", "country", "phone", "fax", "email", "website")


def eto_connect():
    try:
        from console_store import eto_connection
        return eto_connection()
    except Exception:
        import os
        import pyodbc
        from console_config import TENANT
        cs = (f"Driver={{ODBC Driver 17 for SQL Server}};Server={TENANT.eto_server};"
              f"Database={TENANT.eto_database};")
        cs += ("Trusted_Connection=yes;" if TENANT.use_windows_auth
               else f"UID={os.environ.get('ETO_USER')};PWD={os.environ.get('ETO_PWD')};")
        return pyodbc.connect(cs)


def rule(t):
    print("\n" + "=" * 78 + f"\n{t}\n" + "=" * 78)


def run(cur, label, sql, params=(), max_rows=25):
    print("\n" + "-" * 78 + f"\n{label}\n" + "-" * 78)
    try:
        cur.execute(sql, params)
        while cur.description is None and cur.nextset():
            pass
        if cur.description is None:
            print("  (no result set)")
            return
        cols = [d[0] for d in cur.description]
        rows = cur.fetchall()
        print("  " + " | ".join(cols))
        for r in rows[:max_rows]:
            print("  " + " | ".join("" if v is None else str(v) for v in r))
        if len(rows) > max_rows:
            print(f"  ... (+{len(rows) - max_rows} more)")
        if not rows:
            print("  (0 rows)")
    except Exception as e:
        print(f"  [ERROR] {type(e).__name__}: {e}")


def columns_of(cur, name):
    cur.execute("SELECT COLUMN_NAME, DATA_TYPE FROM INFORMATION_SCHEMA.COLUMNS "
                "WHERE TABLE_NAME = ? ORDER BY ORDINAL_POSITION", (name,))
    return [(r[0], r[1]) for r in cur.fetchall()]


def pick(cols, hints, prefer=None, want_bit=False):
    names = [n for n, _ in cols]
    if prefer:
        for p in prefer:
            for n in names:
                if n.lower() == p.lower():
                    return n
    for n, dt in cols:
        nl = n.lower()
        if any(h in nl for h in hints) and (not want_bit or dt.lower() == "bit"):
            return n
    return None


def main():
    conn = eto_connect()
    cur = conn.cursor()
    try:
        cols = columns_of(cur, "tblCompany")

        # ── A. tblCompany columns, flagged ───────────────────────────────────────
        rule("A. tblCompany columns (★ active  ◆ supplier/vendor  ◇ address-ish)")
        for n, dt in cols:
            nl = n.lower()
            tag = ""
            if any(h in nl for h in SUPPLIER_HINTS):
                tag += " ◆supplier"
            if any(h in nl for h in ACTIVE_HINTS):
                tag += " ★active"
            if any(h in nl for h in ADDR_HINTS):
                tag += " ◇addr"
            print(f"    {n} : {dt}{tag}")

        # ── B. auto-detect the columns and BUILD the query ───────────────────────
        rule("B. AUTO-DETECTED columns + the SELECT that will run")
        name_col = pick(cols, NAME_HINTS, prefer=["CName", "CompanyName", "Name"])
        active_col = pick(cols, ACTIVE_HINTS, prefer=["CActive", "CompanyActive", "IsActive", "Active"],
                          want_bit=True)
        supplier_col = pick(cols, SUPPLIER_HINTS, prefer=["CSupplier", "CVendor", "IsSupplier"],
                            want_bit=True)
        addr_cols = [n for n, _ in cols if any(h in n.lower() for h in ADDR_HINTS)]
        print(f"  name     = {name_col}")
        print(f"  active   = {active_col}")
        print(f"  supplier = {supplier_col}")
        print(f"  address  = {', '.join(addr_cols) if addr_cols else '(none found on tblCompany — see D)'}")

        sel_cols = ["CompanyID"] + [c for c in [name_col] if c] + addr_cols
        where = []
        if active_col:
            where.append(f"[{active_col}] = 1")
        if supplier_col:
            where.append(f"[{supplier_col}] = 1")
        where_sql = (" WHERE " + " AND ".join(where)) if where else ""
        order = f" ORDER BY [{name_col}]" if name_col else ""
        query = (f"SELECT {', '.join('[' + c + ']' for c in sel_cols)}\n"
                 f"FROM dbo.tblCompany{where_sql}{order}")
        print("\n  --- query ---\n  " + query.replace("\n", "\n  "))

        # ── C. RUN it ────────────────────────────────────────────────────────────
        rule("C. RESULT — active suppliers + addresses (sample; full count below)")
        if supplier_col or active_col:
            run(cur, "C1. active suppliers", query, max_rows=25)
            run(cur, "C2. total count", f"SELECT COUNT(*) AS active_suppliers FROM dbo.tblCompany{where_sql}")
        else:
            print("  Could not auto-detect an active/supplier flag on tblCompany — see A and D, then\n"
                  "  tell me which columns to use and I'll finalize the query.")

        # ── D. fallback: separate address table / company views ──────────────────
        rule("D. FALLBACK objects (only needed if no address columns on tblCompany)")
        cur.execute("SELECT TABLE_NAME FROM INFORMATION_SCHEMA.TABLES "
                    "WHERE TABLE_NAME LIKE '%Company%' OR TABLE_NAME LIKE '%Supplier%' "
                    "   OR TABLE_NAME LIKE '%Vendor%' OR TABLE_NAME LIKE '%Address%' "
                    "ORDER BY TABLE_NAME")
        for r in cur.fetchall():
            print("   ", r[0])
    finally:
        conn.close()
    print("\nDone. Paste the whole output.\n"
          "  • If C1/C2 returned rows, the SELECT printed in B is your query — copy it.\n"
          "  • If a flag/address guess was wrong, A lists the real column names; tell me which to use\n"
          "    (or if addresses live in a table from D) and I'll hand back the finalized query.")


if __name__ == "__main__":
    main()
