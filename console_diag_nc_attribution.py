"""
console_diag_nc_attribution.py — confirm NC attribution granularity (2026-07-26, read-only).

The NC reports attribute cost three ways beyond supplier: by Source (detected), by ETO's
maintained responsible Department (tlkpNonConformanceOrigin.DepartmentName), and by a
DERIVED discipline (keyword on the origin text). This probe shows exactly how granular the
DepartmentName capture is, and how the derived-discipline mapping lands on the real origin
list — so we can tune the crosswalk if needed. Pure SELECT; nothing written.

Run on the box:  python console_diag_nc_attribution.py
Paste the WHOLE output back.
"""

# Same keyword rules as console_web/ncspec.derive_discipline (kept in sync by hand).
_RULES = (("hydraulic", "Hydraulic Engineering"),
          ("electrical", "Electrical Engineering"),
          ("mechanical", "Mechanical Engineering"))


def derive_discipline(origin):
    s = (origin or "").lower()
    for kw, disc in _RULES:
        if kw in s:
            return disc
    return "Other / Unattributed"


def connect():
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


def show(cur, label, sql):
    print("\n" + "-" * 78 + f"\n{label}\n" + "-" * 78)
    try:
        cur.execute(sql)
        cols = [d[0] for d in cur.description]
        rows = cur.fetchall()
        print("  " + " | ".join(cols))
        for r in rows:
            print("  " + " | ".join("" if v is None else str(v) for v in r))
        return [dict(zip(cols, r)) for r in rows]
    except Exception as e:
        print(f"  [ERROR] {type(e).__name__}: {e}")
        return []


def main():
    conn = connect()
    cur = conn.cursor()
    try:
        # 1. The origin lookup — Description + ETO responsible department + disabled flag.
        origins = show(cur, "1. tlkpNonConformanceOrigin — origin → ETO DepartmentName",
                       "SELECT NonConformanceOriginID AS ID, NonConformanceOriginDescription "
                       "AS Origin, DepartmentName, Disabled FROM dbo.tlkpNonConformanceOrigin "
                       "ORDER BY NonConformanceOriginDescription")

        # 2. How complete is the DepartmentName capture?
        with_dept = sum(1 for o in origins if (o.get("DepartmentName") or "").strip())
        print(f"\n  DepartmentName populated on {with_dept} / {len(origins)} origins.")

        # 3. NCR volume + cost by ETO department (join through the cost rollup).
        show(cur, "3. NCR count + cost by ETO responsible department",
             "SELECT ISNULL(O.DepartmentName,'(unassigned)') AS Department, COUNT(*) AS NCRs, "
             "CAST(SUM(ISNULL(C.TotalNCCostingValue,0)) AS decimal(20,2)) AS TotalCost "
             "FROM dbo.vwNonConformances NC "
             "LEFT JOIN dbo.vwCostingSummed_ByNC C ON NC.NonConformanceID = C.NonConformanceID "
             "LEFT JOIN dbo.tlkpNonConformanceOrigin O "
             "       ON NC.NonConformanceOriginID = O.NonConformanceOriginID "
             "WHERE NC.SActive = 1 GROUP BY O.DepartmentName ORDER BY NCRs DESC")

        # 4. Derived-discipline distribution over the REAL origin list (portfolio-wide),
        #    computed here so we can see how much lands in 'Other'.
        rows = show(cur, "4. NCR count by origin (for the derived-discipline mapping check)",
                    "SELECT NonConformanceOriginDescription AS Origin, COUNT(*) AS NCRs "
                    "FROM dbo.vwNonConformances WHERE SActive = 1 "
                    "GROUP BY NonConformanceOriginDescription ORDER BY COUNT(*) DESC")
        buckets = {}
        for r in rows:
            disc = derive_discipline(r.get("Origin"))
            buckets[disc] = buckets.get(disc, 0) + int(r.get("NCRs") or 0)
        print("\n  Derived-discipline rollup (keyword on origin text):")
        for disc, n in sorted(buckets.items(), key=lambda kv: -kv[1]):
            print(f"    {disc:26} {n}")
        print("\n  → If too much lands in 'Other / Unattributed', we extend the keyword rules "
              "or prefer the ETO DepartmentName as the primary attribution axis.")
    finally:
        conn.close()
    print("\nDone. Paste the whole output back.")


if __name__ == "__main__":
    main()
