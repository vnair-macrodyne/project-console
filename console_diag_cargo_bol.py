"""console_diag_cargo_bol.py - READ-ONLY probe.

Find the exact ETO source columns for the two new PO-line fields Peter added - "Cargo Ready Date"
and "BOL / Tracking" - so we can add them to the Purchasing Exception Report BETWEEN Order Date and
Planned Receipt. No writes. Run on vnar (same as the other console_diag_* probes):

    python console_diag_cargo_bol.py
"""
import console_config                      # loads .env / TENANT
from console_store import eto_connection


def run(cur, sql, params=None):
    cur.execute(sql, params or [])
    return [d[0] for d in cur.description], cur.fetchall()


def main():
    conn = eto_connection()
    cur = conn.cursor()

    print("=== 1) tlkpCaption - ANY object, captions matching cargo/BOL/lading/tracking/ready ===")
    _, rows = run(cur, """
        SELECT Object, FieldName, Caption FROM dbo.tlkpCaption
        WHERE Caption LIKE '%Cargo%' OR Caption LIKE '%BOL%' OR Caption LIKE '%Lading%'
           OR Caption LIKE '%Tracking%' OR Caption LIKE '%Ready%'
        ORDER BY Object, FieldName""")
    for r in rows:
        print("   ", tuple(r))

    print("\n=== 2) named PO columns matching cargo/BOL/lading/tracking/ready ===")
    _, rows = run(cur, """
        SELECT TABLE_NAME, COLUMN_NAME, DATA_TYPE FROM INFORMATION_SCHEMA.COLUMNS
        WHERE (COLUMN_NAME LIKE '%Cargo%' OR COLUMN_NAME LIKE '%BOL%' OR COLUMN_NAME LIKE '%Lading%'
            OR COLUMN_NAME LIKE '%Tracking%' OR COLUMN_NAME LIKE '%Ready%')
          AND TABLE_NAME LIKE '%Purchase%'
        ORDER BY TABLE_NAME, COLUMN_NAME""")
    for r in rows:
        print("   ", tuple(r))

    print("\n=== 3) full 'Purchase Order Detail' caption layout (PO-line custom fields) ===")
    _, rows = run(cur, "SELECT FieldName, Caption FROM dbo.tlkpCaption "
                       "WHERE Object = 'Purchase Order Detail' ORDER BY FieldName")
    for r in rows:
        print("   ", tuple(r))

    print("\n=== 4) full 'Purchase Order' caption layout (PO-header custom fields) ===")
    _, rows = run(cur, "SELECT FieldName, Caption FROM dbo.tlkpCaption "
                       "WHERE Object = 'Purchase Order' ORDER BY FieldName")
    for r in rows:
        print("   ", tuple(r))

    conn.close()
    print("\n[done] read-only - no writes.")


if __name__ == "__main__":
    main()
