"""
console_diag_task999_labour.py — locate & quantify labour charged to task/spec 999 (2026-08-07).

CONTEXT (Vijay): rework labour is often charged to task code 999. It isn't aimed at a specific
task, but it's part of a project's — and a discipline's — labour. SpecID 999 = the project's
"Nonconformances (NCR)" bucket (confirmed on 220154, alongside 850 Field Services / 899 Mgmt
Contingency). The NC module reports labour ≈ $0 because it attributes labour PER NCR
(NonConformanceID); the real rework labour lives on spec 999 at the project/discipline grain.

This maps it:
  (A) column shapes of the per-spec costed labour views + the budget table;
  (B) confirm what 999 (and 850/899) are called across projects;
  (C) labour ON spec 999 per project (hours + applied-rate cost) and its share of project labour;
  (D) 999 labour by HOUR TYPE / department → the discipline split;
  (E) is spec 999 BUDGETED (tblSpecHours)? — does it have a labour budget of its own;
  (F) how much 999 labour carries a NonConformanceID vs not — explains the NC module's $0.

READ-ONLY. Run:  python console_diag_task999_labour.py
Paste the WHOLE output.
"""


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


def run(cur, label, sql, params=(), max_rows=30):
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
    try:
        cur.execute("SELECT COLUMN_NAME, DATA_TYPE FROM INFORMATION_SCHEMA.COLUMNS "
                    "WHERE TABLE_NAME = ? ORDER BY ORDINAL_POSITION", (name,))
        return [(r[0], r[1]) for r in cur.fetchall()]
    except Exception:
        return []


def has(cols, name):
    return any(c[0].lower() == name.lower() for c in cols)


def main():
    conn = eto_connect()
    cur = conn.cursor()
    try:
        # ── A. column shapes ──────────────────────────────────────────────────
        rule("A. COLUMN SHAPES — per-spec costed labour views + budget table")
        for name in ("vwCostingTimecardsSummed_BySpecID",
                     "vwCostingTimecardsSummed_BySpecIDAndHourType",
                     "vwCostingTimecardsDetailed", "tblSpecHours"):
            cols = columns_of(cur, name)
            if not cols:
                print(f"\n  {name}: (not found)")
                continue
            print(f"\n  {name} ({len(cols)} cols): " + ", ".join(f"{n}:{t}" for n, t in cols))

        # ── B. what is 999 (and 850/899)? ─────────────────────────────────────
        rule("B. SPEC-CODE MEANING — how 999 / 850 / 899 are named across projects")
        run(cur, "B1. distinct descriptions for these special spec codes",
            "SELECT SpecID, COUNT(*) AS specs, MIN(SDescription) AS example_desc "
            "FROM dbo.tblSpec WHERE SpecID IN (850, 899, 999) GROUP BY SpecID ORDER BY SpecID")
        run(cur, "B2. sample 999 specs (project → description)",
            "SELECT TOP 15 ProjectID, SpecID, SDescription, DisplayName "
            "FROM dbo.tblSpec WHERE SpecID = 999 ORDER BY ProjectID DESC")

        # ── C. labour ON spec 999 per project + share of project labour ───────
        rule("C. LABOUR ON SPEC 999 — hours + applied-rate cost per project")
        run(cur, "C1. top projects by 999 labour cost",
            "SELECT TOP 25 ProjectID, TotalHours, LaborCostingValue "
            "FROM dbo.vwCostingTimecardsSummed_BySpecID WHERE SpecID = 999 "
            "ORDER BY LaborCostingValue DESC")
        run(cur, "C2. portfolio total: 999 labour vs ALL project labour (share)",
            "SELECT s.projects_with_999, s.hrs_999, s.cost_999, t.total_cost, "
            "CAST(s.cost_999 AS float) / NULLIF(t.total_cost, 0) AS share "
            "FROM (SELECT COUNT(DISTINCT ProjectID) AS projects_with_999, "
            "             SUM(TotalHours) AS hrs_999, SUM(LaborCostingValue) AS cost_999 "
            "      FROM dbo.vwCostingTimecardsSummed_BySpecID WHERE SpecID = 999) s "
            "CROSS JOIN (SELECT SUM(LaborCostingValue) AS total_cost "
            "            FROM dbo.vwCostingTimecardsSummed_ByProjectID) t")

        # ── D. 999 labour by HOUR TYPE / department (the discipline split) ────
        rule("D. 999 LABOUR BY HOUR TYPE / DEPARTMENT (discipline split)")
        run(cur, "D1. by hour type on the by-spec+hourtype view",
            "SELECT TOP 40 * FROM dbo.vwCostingTimecardsSummed_BySpecIDAndHourType "
            "WHERE SpecID = 999 ORDER BY 1", max_rows=5)
        run(cur, "D2. 999 labour grouped by hour type + dept (detailed view)",
            "SELECT TOP 40 HourType, HourDescription, DeptName, "
            "SUM(HourTime) AS hrs, SUM(LaborCostingValue) AS cost "
            "FROM dbo.vwCostingTimecardsDetailed WHERE SpecID = 999 "
            "GROUP BY HourType, HourDescription, DeptName ORDER BY cost DESC")

        # ── E. is spec 999 budgeted? ──────────────────────────────────────────
        rule("E. BUDGET — does spec 999 carry a labour budget of its own?")
        run(cur, "E1. tblSpecHours coverage for 999 vs normal specs",
            "SELECT CASE WHEN SpecID = 999 THEN '999 (NCR)' ELSE 'other specs' END AS bucket, "
            "COUNT(*) AS rows, COUNT(DISTINCT ProjectID) AS projects "
            "FROM dbo.tblSpecHours GROUP BY CASE WHEN SpecID = 999 THEN '999 (NCR)' ELSE 'other specs' END")
        run(cur, "E2. sample budget rows for spec 999 (if any)",
            "SELECT TOP 15 * FROM dbo.tblSpecHours WHERE SpecID = 999", max_rows=15)

        # ── F. NC linkage — 999 labour with vs without a NonConformanceID ─────
        rule("F. NC LINKAGE — 999 labour that carries a NonConformanceID vs not")
        run(cur, "F1. split (explains why per-NCR labour looks like $0)",
            "SELECT SUM(CASE WHEN NonConformanceID > 0 THEN LaborCostingValue ELSE 0 END) AS nc_linked_cost, "
            "SUM(CASE WHEN NonConformanceID IS NULL OR NonConformanceID = 0 THEN LaborCostingValue ELSE 0 END) AS not_linked_cost, "
            "COUNT(*) AS lines "
            "FROM dbo.vwCostingTimecardsDetailed WHERE SpecID = 999")

    finally:
        conn.close()
    print("\nDone. What it tells us:")
    print("  • B: confirm 999 = NCR (and 850/899 siblings) — the special non-task buckets.")
    print("  • C: how much labour is on 999 and what share of project labour it is (is it material?).")
    print("  • D: the discipline split of 999 labour (via hour type/description) — so it can be")
    print("    attributed to disciplines, not left as an unallocated lump.")
    print("  • E: whether 999 has a budget (likely not) — so today it's actual-with-no-budget,")
    print("    inflating consumed %; decides how we treat it (own line vs spread vs excluded).")
    print("  • F: 999 labour is real but NOT NCR-linked → that's why the NC module shows ~$0.")


if __name__ == "__main__":
    main()
