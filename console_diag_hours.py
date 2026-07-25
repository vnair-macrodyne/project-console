"""
console_diag_hours.py — find the budget/actual HOURS-by-hour-type source (read-only).

The Executive Dashboard's per-discipline Labour block should be HOURS-based
(hours consumed vs budget hours per discipline), matching the manual dashboard and
the lead-on-hours principle. Layer 1 currently has labour $ by hour type; this probe
locates the parallel HOURS columns so the discipline block can be put on hours.

Run:  python console_diag_hours.py   → paste the whole output back.
"""
from console_engine import _connect


def cols(cur, name):
    cur.execute("SELECT COLUMN_NAME, DATA_TYPE FROM INFORMATION_SCHEMA.COLUMNS "
                "WHERE TABLE_NAME = ? ORDER BY ORDINAL_POSITION", name)
    return cur.fetchall()


def main():
    conn = _connect()
    try:
        cur = conn.cursor()

        # 1. The two estimate/actual views we already use — full column dump so we can
        #    see whether they carry hours alongside the labour $.
        for obj in ("vwProjectLaborActualsVSEstimatesByHourType",
                    "vwProjectActualsVSEstimates"):
            print("=" * 72)
            print(f"OBJECT: {obj}")
            print("=" * 72)
            c = cols(cur, obj)
            if not c:
                print("  (no columns — name may differ)")
            for name, dt in c:
                print(f"    {name:<42} {dt}")

        # 2. Anywhere in the DB, columns that look like budget/estimate/actual HOURS —
        #    this surfaces the right source table/view even if it's not one above.
        print("\n" + "=" * 72)
        print("ANY COLUMN LIKE '%Hour%' + (Budget|Est|Actual) ACROSS THE DB")
        print("=" * 72)
        cur.execute("""
            SELECT TABLE_NAME, COLUMN_NAME, DATA_TYPE
            FROM INFORMATION_SCHEMA.COLUMNS
            WHERE COLUMN_NAME LIKE '%Hour%'
              AND (COLUMN_NAME LIKE '%Budget%' OR COLUMN_NAME LIKE '%Est%'
                   OR COLUMN_NAME LIKE '%Actual%')
            ORDER BY TABLE_NAME, COLUMN_NAME
        """)
        rows = cur.fetchall()
        for t, c, dt in rows:
            print(f"    {t:<46} {c:<34} {dt}")
        if not rows:
            print("    (none found)")

        # 3. One sample row of the hour-type view for project 230219, so we see real
        #    values and confirm which columns are hours vs dollars.
        print("\n" + "=" * 72)
        print("SAMPLE: vwProjectLaborActualsVSEstimatesByHourType WHERE ProjectID=230219")
        print("=" * 72)
        try:
            cur.execute("SELECT TOP 5 * FROM dbo.vwProjectLaborActualsVSEstimatesByHourType "
                        "WHERE ProjectID = 230219")
            hdr = [d[0] for d in cur.description]
            print("    " + " | ".join(hdr))
            for r in cur.fetchall():
                print("    " + " | ".join("" if v is None else str(v) for v in r))
        except Exception as e:
            print("   sample failed:", e)
    finally:
        conn.close()


if __name__ == "__main__":
    main()
