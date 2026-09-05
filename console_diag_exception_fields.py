"""
console_diag_exception_fields.py — hunt ETO for real sources to POPULATE the Exception report's
currently-blank fields.  (2026-09-05)  READ-ONLY.

The Procurement Exception report (etospec.COLS_EXC) has five fields that today read blank because
the code has no maintained ETO source wired in:
    PlannedShip, DaysToAssembly, RFQDate, PermitDates   (+ LeadTime, sourced but worth a coverage check)

The exception rows are built from:
    vwPurchaseOrderHeader (poh) + vwPurchaseOrderDetails (pod)
    + vwPurchaseOrderDetailsDetailed (pdd) + tblProjects (p) + tblEngItemMaster (eim)

This probe answers, for each blank field:
  A. What date/attribute columns those source objects actually expose (so we can wire a field
     without a new join).
  B. A tenant-wide search for candidate columns anywhere (ship / promise / planned / assembly /
     start / need / rfq / quote / permit / lead), grouped by table+view.
  C. For the strongest candidates, a COVERAGE + SAMPLE readout — is the column actually maintained,
     or is it present-but-empty (which is why we didn't trust it in the first place)?

Run:  python console_diag_exception_fields.py [projectID]
Paste the whole output.
"""
import sys

SRC_OBJECTS = [
    "vwPurchaseOrderHeader", "vwPurchaseOrderDetails", "vwPurchaseOrderDetailsDetailed",
    "tblProjects", "tblEngItemMaster",
]
# name fragments that could feed the blank fields
HINTS = {
    "PlannedShip":    ["ship", "promise", "promised", "planned", "delivery", "deliver"],
    "DaysToAssembly": ["assembly", "assemble", "start", "need", "required", "duedate", "due"],
    "RFQDate":        ["rfq", "quote", "quotation", "bid"],
    "PermitDates":    ["permit", "inspection", "compliance", "cert"],
    "LeadTime":       ["lead"],
}
ALL_HINTS = sorted({h for hs in HINTS.values() for h in hs})


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
    print("\n" + "=" * 78 + f"\n{t}\n" + "=" * 78)


def rows(cur, sql, *a):
    cur.execute(sql, *a)
    cols = [d[0] for d in cur.description]
    return cols, cur.fetchall()


def cols_of(cur, obj):
    _, r = rows(cur, "SELECT COLUMN_NAME, DATA_TYPE FROM INFORMATION_SCHEMA.COLUMNS "
                     "WHERE TABLE_NAME = ? ORDER BY ORDINAL_POSITION", obj)
    return r


def _looks_relevant(name):
    n = name.lower()
    return [h for h in ALL_HINTS if h in n]


def main():
    proj = sys.argv[1] if len(sys.argv) > 1 else None
    eto = eto_connect(); cur = eto.cursor()

    rule("A. Columns of the exception report's source objects (flagging candidate fields)")
    for obj in SRC_OBJECTS:
        cs = cols_of(cur, obj)
        if not cs:
            print(f"  {obj}: (not found)")
            continue
        print(f"  {obj}  ({len(cs)} cols):")
        for c, t in cs:
            hit = _looks_relevant(c)
            mark = ("   <-- " + ",".join(hit)) if hit else ""
            if hit or ("date" in t.lower()):
                print(f"     {c:38} {t}{mark}")

    rule("B. Tenant-wide candidate columns by field need (tables + views)")
    for field, frags in HINTS.items():
        like = " OR ".join([f"LOWER(c.COLUMN_NAME) LIKE '%{f}%'" for f in frags])
        _, hits = rows(cur, f"""
            SELECT c.TABLE_NAME, t.TABLE_TYPE, c.COLUMN_NAME, c.DATA_TYPE
            FROM INFORMATION_SCHEMA.COLUMNS c
            JOIN INFORMATION_SCHEMA.TABLES t ON t.TABLE_NAME = c.TABLE_NAME
            WHERE ({like})
              AND (LOWER(c.TABLE_NAME) LIKE 'tbl%' OR LOWER(c.TABLE_NAME) LIKE 'vw%')
            ORDER BY t.TABLE_TYPE, c.TABLE_NAME, c.COLUMN_NAME""")
        print(f"\n  ── {field}: {len(hits)} candidate column(s)")
        for tn, tt, cn, dt in hits[:40]:
            print(f"     {tt:11} {tn:42} {cn:32} {dt}")
        if len(hits) > 40:
            print(f"     … and {len(hits) - 40} more")

    rule("C. Coverage of the columns we DO wire or could wire (are they maintained?)")
    # LeadTime — already sourced from eim.EstimatedLeadTime
    for obj, col in [("tblEngItemMaster", "EstimatedLeadTime")]:
        try:
            _, r = rows(cur, f"SELECT COUNT(*) AS n, "
                             f"SUM(CASE WHEN [{col}] IS NOT NULL AND [{col}] <> 0 THEN 1 ELSE 0 END) AS filled "
                             f"FROM [{obj}]")
            n, filled = r[0]
            print(f"  {obj}.{col}: {filled}/{n} rows populated")
        except Exception as e:
            print(f"  {obj}.{col}: {e}")

    # tblProjects date columns — the most likely home of a project ship / assembly date
    rule("C2. tblProjects date columns — coverage + sample (PlannedShip / DaysToAssembly candidates)")
    pcols = [c for c, t in cols_of(cur, "tblProjects")
             if "date" in t.lower() or _looks_relevant(c)]
    print(f"  candidate tblProjects columns: {pcols}")
    for c in pcols:
        try:
            _, r = rows(cur, f"SELECT COUNT(*) n, SUM(CASE WHEN [{c}] IS NOT NULL THEN 1 ELSE 0 END) filled, "
                             f"MIN([{c}]) mn, MAX([{c}]) mx FROM tblProjects")
            n, filled, mn, mx = r[0]
            print(f"    {c:34} {filled}/{n} filled   min={str(mn)[:19]}  max={str(mx)[:19]}")
        except Exception as e:
            print(f"    {c:34} err: {e}")

    if proj:
        rule(f"C3. tblProjects row for project {proj} (see which date fields are actually set)")
        pc = [c for c, _ in cols_of(cur, "tblProjects")]
        keep = [c for c in pc if c in ("ProjectID", "DisplayName") or _looks_relevant(c)
                or c.lower().endswith("date")]
        sel = ", ".join(f"[{c}]" for c in keep)
        try:
            hdr, r = rows(cur, f"SELECT {sel} FROM tblProjects WHERE ProjectID = ?", proj)
            for row in r:
                for k, v in zip(hdr, row):
                    print(f"    {k:34} {v}")
        except Exception as e:
            print(f"    err: {e}")

    eto.close()
    print("\nInterpretation: any column that is present but ~0% filled is why the field reads blank; "
          "a well-filled column is a real source we can wire. RFQ / Permit are expected to have no "
          "maintained source — confirm from section B before we decide to drop those columns.")


if __name__ == "__main__":
    main()
