"""console_diag_released_by.py - READ-ONLY probe: WHO released, per active project.

Source: tblBOMReleaseHistory.ReleasedByEmployeeID -> tblEmployee (NOT NULL, 100% populated).
Name format matches the Buyer column: 'LastName, FirstName'.

  A. Per project: first-release (date + who) and last-release (date + who).
  B. Per project: every releaser with their event count and date span
     ("whoever released at whatever point").
  C. Portfolio: top releasers overall (event count) across the active set.

No writes. Run from the repo root with the same Python as the other console_diag_* scripts:
    python console_diag_released_by.py
"""
import console_config                      # loads .env / TENANT
from console_store import eto_connection, console_connection


def run(cur, sql, params=None):
    cur.execute(sql, params or [])
    return [d[0] for d in cur.description], cur.fetchall()


def dd(v):
    try:
        return v.date().isoformat()
    except Exception:
        return "" if v is None else str(v)[:10]


def main():
    active = []
    try:
        ccur = console_connection().cursor()
        ccur.execute("SELECT ProjectID FROM Reporting.tblActiveProject ORDER BY ProjectID")
        active = [int(r[0]) for r in ccur.fetchall()]
    except Exception as e:
        print("(could not read Reporting.tblActiveProject:", e, ")")
    if not active:
        print("no active projects - aborting"); return
    ids = ",".join(str(p) for p in active)
    print("active projects:", len(active), active)

    cur = eto_connection().cursor()
    NAME = "e.EmpLastName + ', ' + e.EmpFirstName"

    print("\n" + "=" * 78)
    print("A. First and last release - date + who (per project)")
    print("=" * 78)
    _, rows = run(cur, f"""
        WITH r AS (
          SELECT h.ProjectID, h.ReleasedDateTime, {NAME} AS rel,
                 ROW_NUMBER() OVER (PARTITION BY h.ProjectID
                     ORDER BY h.ReleasedDateTime ASC, h.BOMReleaseHistoryID ASC)  AS rn_first,
                 ROW_NUMBER() OVER (PARTITION BY h.ProjectID
                     ORDER BY h.ReleasedDateTime DESC, h.BOMReleaseHistoryID DESC) AS rn_last
          FROM tblBOMReleaseHistory h
          JOIN tblEmployee e ON e.EmployeeID = h.ReleasedByEmployeeID
          WHERE h.ProjectID IN ({ids})
        )
        SELECT ProjectID,
          MAX(CASE WHEN rn_first=1 THEN CAST(ReleasedDateTime AS date) END) AS first_date,
          MAX(CASE WHEN rn_first=1 THEN rel END)                           AS first_by,
          MAX(CASE WHEN rn_last=1  THEN CAST(ReleasedDateTime AS date) END) AS last_date,
          MAX(CASE WHEN rn_last=1  THEN rel END)                           AS last_by
        FROM r GROUP BY ProjectID ORDER BY ProjectID""")
    print(f"   {'Proj':>7}  {'first_rel':>10}  {'first_by':<22}  {'last_rel':>10}  {'last_by':<22}")
    for r in rows:
        print(f"   {r[0]:>7}  {dd(r[1]):>10}  {str(r[2] or ''):<22}  {dd(r[3]):>10}  {str(r[4] or ''):<22}")

    print("\n" + "=" * 78)
    print("B. Releasers per project (who released, how many, over what span)")
    print("=" * 78)
    _, rows = run(cur, f"""
        SELECT h.ProjectID, {NAME} AS rel, COUNT(*) AS n,
               CAST(MIN(h.ReleasedDateTime) AS date) AS first,
               CAST(MAX(h.ReleasedDateTime) AS date) AS last
        FROM tblBOMReleaseHistory h
        JOIN tblEmployee e ON e.EmployeeID = h.ReleasedByEmployeeID
        WHERE h.ProjectID IN ({ids})
        GROUP BY h.ProjectID, {NAME}
        ORDER BY h.ProjectID, COUNT(*) DESC""")
    cur_proj = None
    for r in rows:
        if r[0] != cur_proj:
            cur_proj = r[0]
            print(f"\n   {r[0]}:")
        print(f"       {str(r[1] or ''):<24} {r[2]:>6} releases   {dd(r[3])} .. {dd(r[4])}")

    print("\n" + "=" * 78)
    print("C. Top releasers overall (active set)")
    print("=" * 78)
    _, rows = run(cur, f"""
        SELECT {NAME} AS rel, COUNT(*) AS n, COUNT(DISTINCT h.ProjectID) AS projs
        FROM tblBOMReleaseHistory h
        JOIN tblEmployee e ON e.EmployeeID = h.ReleasedByEmployeeID
        WHERE h.ProjectID IN ({ids})
        GROUP BY {NAME} ORDER BY COUNT(*) DESC""")
    for r in rows:
        print(f"   {str(r[0] or ''):<24} {r[1]:>7} releases   on {r[2]} project(s)")

    print("\nDONE (read-only).")


if __name__ == "__main__":
    main()
