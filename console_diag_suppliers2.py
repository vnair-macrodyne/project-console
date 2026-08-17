"""
console_diag_suppliers2.py — pinpoint the SUPPLIER flag on tblCompany (2026-08-14)

First pass returned all companies (customers included) because no clean supplier flag was detected —
in ETO a company is often BOTH a customer and a supplier, and the role columns aren't always named
obviously. This probe finds the column that actually means "supplier" by:
  A. listing every tblCompany column, tagging bit/role-ish ones;
  B. for each bit column + each role/type-named column, showing how many rows = 1 (or the distinct
     values) — so we SEE the real flags (CCustomer / CSupplier / CProspect / a type code…);
  C. CROSS-CHECK: for each bit column, how many 1s fall on companies we actually BUY from (appear as
     a PO vendor) vs companies we SELL to (a project's customer). The supplier flag is the one that's
     ~all-1 for PO vendors and ~0 for project-only customers.
Then I'll hand back the finalized "active suppliers + addresses" query. READ-ONLY.
Run:  python console_diag_suppliers2.py   → paste the whole output.
"""
ROLE_HINTS = ("customer", "supplier", "vendor", "prospect", "type", "category",
              "class", "kind", "role", "active", "status")


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


def scalar(cur, sql):
    try:
        cur.execute(sql)
        r = cur.fetchone()
        return r[0] if r else None
    except Exception as e:
        return f"[ERROR] {type(e).__name__}: {e}"


def run(cur, label, sql, max_rows=25):
    print("\n" + "-" * 78 + f"\n{label}\n" + "-" * 78)
    try:
        cur.execute(sql)
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


def find_key(cols, hints):
    for n, _ in cols:
        if any(h in n.lower() for h in hints):
            return n
    return None


def main():
    conn = eto_connect()
    cur = conn.cursor()
    try:
        cols = columns_of(cur, "tblCompany")
        bit_cols = [n for n, dt in cols if dt.lower() == "bit"]
        role_named = [n for n, dt in cols
                      if any(h in n.lower() for h in ROLE_HINTS) and dt.lower() != "bit"]

        # ── A. columns ───────────────────────────────────────────────────────────
        rule("A. tblCompany columns (⚑ bit  ◆ role/type-named)")
        for n, dt in cols:
            tag = ""
            if dt.lower() == "bit":
                tag += " ⚑bit"
            if any(h in n.lower() for h in ROLE_HINTS) and dt.lower() != "bit":
                tag += " ◆role"
            print(f"    {n} : {dt}{tag}")

        # ── B. distribution of every flag / role column ──────────────────────────
        rule("B. VALUE COUNTS — every bit flag (=1 count) and role/type column (distinct values)")
        total = scalar(cur, "SELECT COUNT(*) FROM dbo.tblCompany")
        print(f"  tblCompany rows: {total}")
        for b in bit_cols:
            ones = scalar(cur, f"SELECT SUM(CAST([{b}] AS int)) FROM dbo.tblCompany")
            print(f"    [{b}] = 1 on {ones} of {total}")
        for rc in role_named:
            run(cur, f"B/{rc} — distinct values",
                f"SELECT TOP 15 [{rc}] AS value, COUNT(*) AS n FROM dbo.tblCompany "
                f"GROUP BY [{rc}] ORDER BY n DESC", max_rows=15)

        # ── C. cross-check each bit flag vs BUY-from (PO vendor) / SELL-to (customer)
        rule("C. CROSS-CHECK — each bit flag: total 1s | 1s on PO vendors | 1s on project customers")
        poh_cols = columns_of(cur, "vwPurchaseOrderHeader")
        vend_key = find_key(poh_cols, ("companyid", "supplierid", "vendorid", "supplier", "vendor"))
        proj_cols = columns_of(cur, "tblProjects")
        cust_key = find_key(proj_cols, ("companyid",))
        print(f"  PO-vendor company key = vwPurchaseOrderHeader.{vend_key}")
        print(f"  project-customer key  = tblProjects.{cust_key}")
        vend_set = (f"(SELECT DISTINCT [{vend_key}] FROM dbo.vwPurchaseOrderHeader "
                    f"WHERE [{vend_key}] IS NOT NULL)") if vend_key else None
        cust_set = (f"(SELECT DISTINCT [{cust_key}] FROM dbo.tblProjects "
                    f"WHERE [{cust_key}] IS NOT NULL)") if cust_key else None
        print(f"\n  {'flag':32} {'ones':>8} {'on_PO_vendors':>14} {'on_customers':>13}")
        for b in bit_cols:
            ones = scalar(cur, f"SELECT SUM(CAST([{b}] AS int)) FROM dbo.tblCompany")
            onv = scalar(cur, f"SELECT SUM(CAST([{b}] AS int)) FROM dbo.tblCompany "
                              f"WHERE CompanyID IN {vend_set}") if vend_set else "n/a"
            onc = scalar(cur, f"SELECT SUM(CAST([{b}] AS int)) FROM dbo.tblCompany "
                              f"WHERE CompanyID IN {cust_set}") if cust_set else "n/a"
            print(f"  {b:32} {str(ones):>8} {str(onv):>14} {str(onc):>13}")
        if vend_set:
            print("\n  # distinct PO-vendor companies:",
                  scalar(cur, f"SELECT COUNT(*) FROM {vend_set} v"))

        # ── D. dedicated supplier / vendor TABLE (maybe suppliers come from a join)
        rule("D. DEDICATED supplier/vendor table? (columns, row count, join to tblCompany)")
        cur.execute("SELECT TABLE_NAME FROM INFORMATION_SCHEMA.TABLES "
                    "WHERE (TABLE_NAME LIKE '%Supplier%' OR TABLE_NAME LIKE '%Vendor%') "
                    "ORDER BY TABLE_NAME")
        sup_tables = [r[0] for r in cur.fetchall()]
        if not sup_tables:
            print("  (no table named like Supplier/Vendor — supplier-ness is a flag on tblCompany,\n"
                  "   see B/C)")
        for t in sup_tables:
            tcols = columns_of(cur, t)
            names = [n for n, _ in tcols]
            n = scalar(cur, f"SELECT COUNT(*) FROM dbo.[{t}]")
            joinable = find_key(tcols, ("companyid",))
            print(f"\n  ── {t}  ({n} rows){'  [joins tblCompany on ' + joinable + ']' if joinable else ''}")
            print("     cols: " + ", ".join(names))
            # sample a couple of rows to see what the table actually holds
            run(cur, f"D/{t} — sample", f"SELECT TOP 5 * FROM dbo.[{t}]", max_rows=5)
    finally:
        conn.close()
    print("\nDone. Paste the whole output.\n"
          "  • B shows the real flags and their populations (e.g. CCustomer vs CSupplier).\n"
          "  • C is the tell: the SUPPLIER flag is the bit that is ~fully 1 for PO vendors and ~0 for\n"
          "    project-only customers. (A company can be BOTH — that's fine; we just filter on it.)\n"
          "  • D catches the other design: a dedicated supplier/vendor table you JOIN to tblCompany\n"
          "    (supplier = a company that has a row there). If one exists, that's likely the answer.\n"
          "  Send this and I'll give you the final 'active suppliers + addresses' query.")


if __name__ == "__main__":
    main()
