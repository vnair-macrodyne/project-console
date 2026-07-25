"""
console_diag_eto_views.py — read-only DISCOVERY of the ETO views the web reporting
suite reads, so we replace every inferred column with a verified one.

Scope (deliberate): the **Labour** and **Purchase** families only. Non-Conformance
is intentionally NOT probed here — we deal with it later.

What it does (nothing is written — pure SELECT):
  1. Lists the real column set of each view (INFORMATION_SCHEMA).
  2. Prints one sample row per view so we see actual values/shapes.
  3. Checks, column-by-column, whether the names the web suite depends on exist,
     and prints PRESENT / **MISSING** for each.
  4. With --project, runs the suite's ACTUAL scoped aggregates so we confirm the
     queries execute and the numbers are sane (esp. that the PO *detail* view can
     be scoped by ProjectID — the main open question for Purchase).

Run on a machine that can reach the ETO SQL Server (same creds as console_sync):
    python console_diag_eto_views.py
    python console_diag_eto_views.py --project 230219
    python console_diag_eto_views.py --project 230219,230312

Then paste the WHOLE output back.
"""
import argparse
import sys


# The columns the web suite (console_web/queries.py) currently reads, per view.
# Anything that comes back MISSING is a guess we must fix.
EXPECTED = {
    "vwTimecards": [
        "ProjectID", "PDescription", "DeptName", "EmployeeID", "EmpNumber",
        "HourDescription", "HourFactor", "HourRate", "HourTime", "TimeDate",
    ],
    "vwPurchaseOrderHeader": [
        "PurchaseOrderID", "CName", "PurchaseActive", "PurchaseDate", "BuyerID",
    ],
    "vwPurchaseOrderDetails": [
        "PurchaseOrderID", "ProjectID", "SpecID", "ItemDescription",
        "ExtendedPrice", "Received",
    ],
}

# Candidate date columns worth spotting on the PO header (the suite assumes PurchaseDate).
PO_DATE_CANDIDATES = ["PurchaseDate", "PODate", "OrderDate", "DateOrdered", "PurchaseOrderDate"]


def connect():
    """Reuse the proven read-only ETO connection (same creds as console_sync)."""
    try:
        from console_store import eto_connection
        return eto_connection()
    except Exception as e1:
        try:
            import pyodbc
            from console_config import TENANT
            import os
            cs = (f"Driver={{ODBC Driver 17 for SQL Server}};Server={TENANT.eto_server};"
                  f"Database={TENANT.eto_database};")
            if TENANT.use_windows_auth:
                cs += "Trusted_Connection=yes;"
            else:
                cs += f"UID={os.environ.get('ETO_USER')};PWD={os.environ.get('ETO_PWD')};"
            return pyodbc.connect(cs)
        except Exception as e2:
            print(f"COULD NOT CONNECT.\n  via console_store: {e1}\n  via direct pyodbc: {e2}")
            sys.exit(1)


def rule(title):
    print("\n" + "=" * 78)
    print(title)
    print("=" * 78)


def list_columns(cur, view):
    """Real columns of a view, from INFORMATION_SCHEMA (works even if empty)."""
    cur.execute(
        "SELECT COLUMN_NAME, DATA_TYPE, IS_NULLABLE "
        "FROM INFORMATION_SCHEMA.COLUMNS WHERE TABLE_NAME = ? "
        "ORDER BY ORDINAL_POSITION", view)
    return [(r[0], r[1], r[2]) for r in cur.fetchall()]


def sample_row(cur, view):
    cur.execute(f"SELECT TOP 1 * FROM dbo.{view}")
    cols = [d[0] for d in cur.description]
    row = cur.fetchone()
    return cols, row


def probe_view(cur, view):
    rule(f"VIEW: dbo.{view}")
    # 1. real columns
    try:
        cols = list_columns(cur, view)
    except Exception as e:
        print(f"  !! could not read columns: {e}")
        return
    if not cols:
        print("  !! view not found (no columns returned by INFORMATION_SCHEMA).")
        return
    print(f"  {len(cols)} columns:")
    for name, typ, nullable in cols:
        print(f"    - {name:32} {typ:14} {'NULL' if nullable == 'YES' else 'NOT NULL'}")
    real = {c[0].lower() for c in cols}

    # 2. expected-column presence check
    print("\n  Columns the web suite depends on:")
    for want in EXPECTED.get(view, []):
        present = want.lower() in real
        print(f"    [{'PRESENT' if present else 'MISSING ':7}] {want}")

    # 2b. PO header date-column hint
    if view == "vwPurchaseOrderHeader":
        hits = [c for c in PO_DATE_CANDIDATES if c.lower() in real]
        print(f"\n  PO date column candidates present: {hits or 'NONE of ' + str(PO_DATE_CANDIDATES)}")

    # 3. one sample row
    try:
        scols, srow = sample_row(cur, view)
        print("\n  Sample row (TOP 1):")
        if srow is None:
            print("    (view returned 0 rows)")
        else:
            for name, val in zip(scols, srow):
                sval = "" if val is None else str(val)
                if len(sval) > 60:
                    sval = sval[:57] + "..."
                print(f"    {name:32} = {sval}")
    except Exception as e:
        print(f"  !! could not fetch sample row: {e}")


def scoped_checks(cur, pids):
    ids = ",".join(str(int(p)) for p in pids)
    rule(f"SCOPED SANITY CHECKS — project(s) {ids}")

    # Labour: the suite's exact aggregate (applied-rate cost).
    print("\n  Labour (vwTimecards, applied-rate cost):")
    try:
        cur.execute(f"""
            SELECT COUNT(*) AS Entries, COUNT(DISTINCT EmployeeID) AS Emps,
                   SUM(HourTime) AS Hours,
                   SUM(HourTime*HourRate*HourFactor) AS Cost
            FROM dbo.vwTimecards WHERE ProjectID IN ({ids})""")
        e, emps, hrs, cost = cur.fetchone()
        print(f"    entries={e}  employees={emps}  hours={hrs}  cost={cost}")
    except Exception as ex:
        print(f"    !! labour aggregate failed: {ex}")

    # Purchase: THE open question — can the DETAIL view be scoped by ProjectID?
    print("\n  Purchase — can vwPurchaseOrderDetails be scoped by ProjectID?")
    try:
        cur.execute(f"""
            SELECT COUNT(DISTINCT poh.PurchaseOrderID) AS POs, COUNT(*) AS Lines,
                   SUM(pod.ExtendedPrice) AS ExtValue
            FROM dbo.vwPurchaseOrderDetails pod
            JOIN dbo.vwPurchaseOrderHeader poh ON poh.PurchaseOrderID = pod.PurchaseOrderID
            WHERE pod.ProjectID IN ({ids}) AND poh.PurchaseActive = 1""")
        pos, lines, val = cur.fetchone()
        print(f"    OK — pod.ProjectID works.  POs={pos}  lines={lines}  ext_value={val}")
    except Exception as ex:
        print(f"    !! scoped PO query failed (this is what we need to learn): {ex}")
        print("       -> if 'Invalid column name ProjectID', the detail view does NOT")
        print("          expose ProjectID and we must scope POs another way.")


def main():
    ap = argparse.ArgumentParser(description="Read-only discovery of ETO Labour/Purchase views.")
    ap.add_argument("--project", help="comma-separated ProjectID(s) for scoped sanity checks")
    args = ap.parse_args()

    conn = connect()
    print("Connected read-only to ETO. Discovering Labour + Purchase views "
          "(Non-Conformance intentionally skipped).")
    try:
        cur = conn.cursor()
        for view in ["vwTimecards", "vwPurchaseOrderHeader", "vwPurchaseOrderDetails"]:
            probe_view(cur, view)
        if args.project:
            pids = [int(p) for p in args.project.split(",") if p.strip()]
            scoped_checks(cur, pids)
        else:
            print("\n(no --project given — run again with --project <id> to exercise the "
                  "actual scoped Labour + Purchase aggregates.)")
    finally:
        conn.close()
    print("\nDone. Paste the whole output back.")


if __name__ == "__main__":
    main()