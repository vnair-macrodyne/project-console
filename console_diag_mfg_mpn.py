"""console_diag_mfg_mpn.py — READ-ONLY probe.

Answers, with no guesses, before we wire Manufacturer / Manufacturer Part Number into the
purchasing reports:
  A. Everywhere those columns live (which tables/views, and their data types).
  B. The exact columns on tblEngItemMaster (the `eim` join the PO reports already make),
     and whether they are free-text (native) or an int FK to a lookup.
  C. That they actually resolve through the report's own PO -> item-master join.
  D. How populated they are — across ALL PO lines and across the ACTIVE-project PO lines.

No writes. Run from the repo root with the same Python you use for the other
console_diag_* scripts:   python console_diag_mfg_mpn.py
"""
import console_config                      # loads .env / TENANT
from console_store import eto_connection, console_connection


def run(cur, sql, params=None):
    cur.execute(sql, params or [])
    cols = [d[0] for d in cur.description]
    return cols, cur.fetchall()


def main():
    conn = eto_connection()
    cur = conn.cursor()

    print("=" * 80)
    print("A. Every column named like 'Manufactur...' across ALL tables & views")
    print("=" * 80)
    _, rows = run(cur, """
        SELECT TABLE_NAME, COLUMN_NAME, DATA_TYPE, CHARACTER_MAXIMUM_LENGTH, IS_NULLABLE
        FROM INFORMATION_SCHEMA.COLUMNS
        WHERE COLUMN_NAME LIKE '%Manufactur%'
        ORDER BY TABLE_NAME, COLUMN_NAME
    """)
    for r in rows:
        print("   ", r[0], "|", r[1], "|", r[2], "| len", r[3], "| null", r[4])
    if not rows:
        print("    (none found)")

    print("\n   supplier-part columns, for contrast:")
    _, rows = run(cur, """
        SELECT TABLE_NAME, COLUMN_NAME, DATA_TYPE, CHARACTER_MAXIMUM_LENGTH
        FROM INFORMATION_SCHEMA.COLUMNS
        WHERE COLUMN_NAME LIKE '%SupplierPart%' OR COLUMN_NAME LIKE '%SupplierItem%'
        ORDER BY TABLE_NAME, COLUMN_NAME
    """)
    for r in rows:
        print("   ", r[0], "|", r[1], "|", r[2], "| len", r[3])

    print("\n" + "=" * 80)
    print("B. Manufacturer / Supplier-part columns ON tblEngItemMaster (the eim join hub)")
    print("=" * 80)
    _, rows = run(cur, """
        SELECT COLUMN_NAME, DATA_TYPE, CHARACTER_MAXIMUM_LENGTH, IS_NULLABLE
        FROM INFORMATION_SCHEMA.COLUMNS
        WHERE TABLE_NAME = 'tblEngItemMaster'
          AND (COLUMN_NAME LIKE '%Manufactur%' OR COLUMN_NAME LIKE '%SupplierPart%')
        ORDER BY COLUMN_NAME
    """)
    eim = {r[0].lower(): (r[0], r[1]) for r in rows}
    for r in rows:
        print("   ", r[0], "|", r[1], "| len", r[2], "| null", r[3])

    name_col = eim.get("manufacturer", (None, None))[0]
    mpn_col = eim.get("manufacturerpartnumber", (None, None))[0]
    name_typ = eim.get("manufacturer", (None, None))[1]
    print("\n   -> Manufacturer column on eim :", name_col, "(", name_typ, ")")
    print("   -> Manuf. Part No column on eim:", mpn_col)
    if name_col and name_typ in ("int", "bigint", "smallint"):
        print("   !! Manufacturer is an INT — it's an FK/lookup, not free text.")
        print("      Looking for a manufacturer lookup table:")
        _, lk = run(cur, """
            SELECT TABLE_NAME FROM INFORMATION_SCHEMA.TABLES
            WHERE TABLE_NAME LIKE '%Manufactur%' ORDER BY TABLE_NAME
        """)
        for r in lk:
            print("        ", r[0])

    if not (name_col and mpn_col):
        print("\n   !! Did not find BOTH columns on tblEngItemMaster by the expected names.")
        print("      Use section A above to see where they really live, then re-run.")
        print("\nDONE (read-only).")
        return

    print("\n" + "=" * 80)
    print("C. Sample via the report's own join: vwPurchaseOrderDetails pod -> tblEngItemMaster eim")
    print("=" * 80)
    sql = f"""
        SELECT TOP 15 pod.ProjectID, pod.ItemCompanyID AS PartNo,
               eim.{name_col} AS Manufacturer, eim.{mpn_col} AS MfgPartNo,
               pod.PurchaseSupplierItem AS SupplierItem
        FROM dbo.vwPurchaseOrderDetails pod
        LEFT JOIN dbo.tblEngItemMaster eim ON eim.ItemID = pod.ItemID
        WHERE NULLIF(LTRIM(RTRIM(CAST(eim.{mpn_col} AS nvarchar(400)))), '') IS NOT NULL
    """
    cols, rows = run(cur, sql)
    print("   ", " | ".join(cols))
    for r in rows:
        print("   ", " | ".join("" if v is None else str(v) for v in r))
    if not rows:
        print("    (no PO lines with a non-blank MPN in the sample)")

    # active-project ids from the console store (the open-projects list)
    active = []
    try:
        cc = console_connection()
        ccur = cc.cursor()
        ccur.execute("SELECT ProjectID FROM Reporting.tblActiveProject")
        active = [int(x[0]) for x in ccur.fetchall()]
    except Exception as e:
        print("\n   (could not read Reporting.tblActiveProject:", e, ")")
    print("\n   active projects from tblActiveProject:", len(active), active[:25])

    def pop(where_sql, params):
        sql = f"""
            SELECT
              COUNT(*) AS Lines,
              SUM(CASE WHEN NULLIF(LTRIM(RTRIM(CAST(eim.{name_col} AS nvarchar(400)))),'') IS NOT NULL
                       THEN 1 ELSE 0 END) AS HasMfr,
              SUM(CASE WHEN NULLIF(LTRIM(RTRIM(CAST(eim.{mpn_col}  AS nvarchar(400)))),'') IS NOT NULL
                       THEN 1 ELSE 0 END) AS HasMPN,
              COUNT(DISTINCT pod.ItemID) AS DistinctItems
            FROM dbo.vwPurchaseOrderDetails pod
            LEFT JOIN dbo.tblEngItemMaster eim ON eim.ItemID = pod.ItemID
            {where_sql}
        """
        cols, rows = run(cur, sql, params)
        return dict(zip(cols, rows[0]))

    print("\n" + "=" * 80)
    print("D. Population on PO lines (Manufacturer / MPN filled)")
    print("=" * 80)
    print("   ALL PO lines:          ", pop("", []))
    if active:
        ph = ",".join("?" * len(active))
        print("   ACTIVE-project lines:  ", pop(f"WHERE pod.ProjectID IN ({ph})", active))
        sql = f"""
            SELECT pod.ProjectID, COUNT(*) AS Lines,
              SUM(CASE WHEN NULLIF(LTRIM(RTRIM(CAST(eim.{mpn_col} AS nvarchar(400)))),'') IS NOT NULL
                       THEN 1 ELSE 0 END) AS HasMPN,
              SUM(CASE WHEN NULLIF(LTRIM(RTRIM(CAST(eim.{name_col} AS nvarchar(400)))),'') IS NOT NULL
                       THEN 1 ELSE 0 END) AS HasMfr
            FROM dbo.vwPurchaseOrderDetails pod
            LEFT JOIN dbo.tblEngItemMaster eim ON eim.ItemID = pod.ItemID
            WHERE pod.ProjectID IN ({ph})
            GROUP BY pod.ProjectID ORDER BY pod.ProjectID
        """
        _, rows = run(cur, sql, active)
        print("\n   per active project (ProjectID | Lines | HasMPN | HasMfr):")
        for r in rows:
            print("     ", r[0], "|", r[1], "|", r[2], "|", r[3])

    print("\nDONE (read-only).")


if __name__ == "__main__":
    main()
