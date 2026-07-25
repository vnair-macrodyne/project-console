"""
console_diag_cols.py — read-only column probe (2026-07-24).

Lists the actual columns of the views/tables the Project Console Labor Data feed depends
on, so the remaining TODO(verify) columns in console_feed.query_labor_data
can be finalized in ONE pass instead of hitting them one 42S22 error at a time.

Run on the domain-joined box:  python console_diag_cols.py
Copy the whole output back and the Labor Data query can be locked to real columns.
Uses the same proven connector as the suite. Reads nothing but metadata + 1 row.
"""
from console_engine import _connect

# object -> the columns we care about resolving (None = dump everything)
TARGETS = {
    "vwTimecards":   ["ProjectID", "SpecID", "EmployeeID", "EmpNumber", "PDescription",
                      "DeptName", "SubDeptName", "HourDescription", "HourType",
                      "TimeDate", "HourTime", "HourRate", "HourFactor"],
    "tblSpec":       ["ProjectID", "SpecID", "SDescription", "SpecName", "Description"],
    "tblEmployee":   ["EmployeeID", "EmpNumber", "EmpFirstName", "EmpLastName"],
}


def columns_of(cur, obj):
    """Return the real column list for a view or table (INFORMATION_SCHEMA)."""
    name = obj.split(".")[-1]
    cur.execute(
        "SELECT COLUMN_NAME, DATA_TYPE FROM INFORMATION_SCHEMA.COLUMNS "
        "WHERE TABLE_NAME = ? ORDER BY ORDINAL_POSITION", name)
    return [(r[0], r[1]) for r in cur.fetchall()]


def main():
    conn = _connect()
    try:
        cur = conn.cursor()
        for obj, wanted in TARGETS.items():
            print("\n" + "=" * 72)
            print(f"OBJECT: {obj}")
            print("=" * 72)
            cols = columns_of(cur, obj)
            if not cols:
                print("  (no columns returned — object name may differ; check schema/prefix)")
                continue
            have = {c.lower() for c, _ in cols}
            print("  ALL COLUMNS:")
            for c, dt in cols:
                print(f"    {c:<32} {dt}")
            print("  WANTED-COLUMN CHECK:")
            for w in wanted:
                mark = "OK " if w.lower() in have else "MISSING"
                print(f"    [{mark}] {w}")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
