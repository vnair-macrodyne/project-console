"""
console_diag_po_late.py — find ETO's REAL "ordered late / delivered late" source (read-only).

Today the Procurement Exceptions report DERIVES "Ord Late" as
    PurchaseDate + tblEngItemMaster.EstimatedLeadTime  >  need-by
i.e. an estimate off a generic item-master lead time — it does NOT read ETO's own
late/exception data. ETO almost certainly holds a supplier PROMISED / ACKNOWLEDGED /
EXPECTED delivery date on the PO line (and may expose a native late/overdue/exception
view). This probe finds those so we can wire Ord Late (and Del Late) to the real field
instead of guessing. Nothing is written — pure SELECT.

Run on the box (same creds as the other diags):
    python console_diag_po_late.py
    python console_diag_po_late.py --project 230219
Paste the WHOLE output back.
"""
import argparse

# column-name hints that would carry a real delivery commitment / late signal
DATE_HINTS = ("date", "promis", "expect", "eta", "arriv", "deliver", "receipt",
              "acknowledg", "ackn", "confirm", "due", "revis", "expedit", "schedul")
STATUS_HINTS = ("late", "status", "overdue", "expedit", "exception", "flag", "priorit")
# native views/objects that might BE ETO's late/exception report
OBJECT_HINTS = ("late", "exception", "overdue", "pastdue", "past_due", "expedit",
                "promis", "delinquen", "aging", "expedite")


def connect():
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


def cols_of(cur, obj):
    cur.execute("SELECT COLUMN_NAME, DATA_TYPE FROM INFORMATION_SCHEMA.COLUMNS "
                "WHERE TABLE_NAME = ? ORDER BY ORDINAL_POSITION", obj)
    return cur.fetchall()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--project", default=None, help="optional ProjectID to sample real open lines")
    args = ap.parse_args()
    conn = connect(); cur = conn.cursor()

    # 1. Every date/status-ish column on the PO detail + header views
    for view in ("vwPurchaseOrderDetails", "vwPurchaseOrderHeader",
                 "tblPurchaseOrderDetails", "tblPurchaseOrderHeader"):
        rule(f"COLUMNS on {view} (date/commitment/status candidates flagged >>>)")
        rows = cols_of(cur, view)
        if not rows:
            print("   (object not found / no columns)"); continue
        for name, typ in rows:
            n = name.lower()
            hit = any(h in n for h in DATE_HINTS + STATUS_HINTS)
            print(f"   {'>>>' if hit else '   '} {name:34} {typ}")

    # 2. Native late/exception/overdue OBJECTS anywhere, with their SQL definition
    rule("NATIVE late/exception/overdue OBJECTS in the database (name match) + definition")
    like = " OR ".join(f"o.name LIKE '%{h}%'" for h in OBJECT_HINTS)
    cur.execute(f"""SELECT o.name, o.type_desc FROM sys.objects o
                    WHERE ({like}) AND o.type IN ('V','U','P','IF','TF','FN')
                    ORDER BY o.type_desc, o.name""")
    objs = cur.fetchall()
    if not objs:
        print("   (no objects whose NAME matches late/exception/overdue/promise/expedite)")
    for name, kind in objs:
        print(f"\n   ─ {name}  ({kind})")
        try:
            cur.execute("SELECT m.definition FROM sys.sql_modules m "
                        "JOIN sys.objects o ON o.object_id = m.object_id WHERE o.name = ?", name)
            r = cur.fetchone()
            if r and r[0]:
                body = r[0].strip().replace("\r", "")
                print("     " + "\n     ".join(body.splitlines()[:40]))
                if len(body.splitlines()) > 40:
                    print("     … (definition truncated)")
        except Exception as ex:
            print(f"     (could not read definition: {ex})")

    # 3. Populated-ness of each candidate date column on OPEN lines + a comparison sample
    rule("OPEN PO lines: how populated is each candidate delivery-date column?")
    det_cols = [c[0] for c in cols_of(cur, "vwPurchaseOrderDetails")]
    cand = [c for c in det_cols if any(h in c.lower() for h in DATE_HINTS)]
    print(f"   candidate date columns on the detail view: {cand or '(none)'}\n")
    scope = ""
    if args.project:
        scope = f" AND pod.ProjectID IN ({','.join(str(int(p)) for p in [x for x in args.project.split(',')])})"
    for c in cand:
        try:
            cur.execute(f"""SELECT COUNT(*) AS OpenLines,
                                   COUNT([{c}]) AS NonNull,
                                   MIN(CAST([{c}] AS date)) AS MinD, MAX(CAST([{c}] AS date)) AS MaxD
                            FROM vwPurchaseOrderDetails pod
                            JOIN vwPurchaseOrderHeader poh ON poh.PurchaseOrderID = pod.PurchaseOrderID
                            WHERE poh.PurchaseActive = 1
                              AND (pod.Received IS NULL OR pod.Received < pod.PurchaseQty){scope}""")
            openl, nn, mn, mx = cur.fetchone()
            print(f"   {c:28} non-null {nn}/{openl}   range {mn} … {mx}")
        except Exception as ex:
            print(f"   {c:28} !! {ex}")

    # 4. Side-by-side sample: required vs revised vs any promised/expected date vs lead time
    if args.project:
        rule(f"SAMPLE open lines for project {args.project} — required vs revised vs promised/expected")
        promised = [c for c in cand if c.lower() not in ("daterequired", "daterevised")]
        sel = ", ".join(["poh.PurchaseOrderID AS PO", "pod.ItemID AS Item",
                         "CAST(pod.DateRequired AS date) AS Required",
                         "CAST(pod.DateRevised AS date)  AS Revised"]
                        + [f"CAST(pod.[{c}] AS date) AS [{c}]" for c in promised]
                        + ["eim.EstimatedLeadTime AS LeadDays"])
        try:
            cur.execute(f"""SELECT TOP 15 {sel}
                            FROM vwPurchaseOrderDetails pod
                            JOIN vwPurchaseOrderHeader poh ON poh.PurchaseOrderID = pod.PurchaseOrderID
                            LEFT JOIN tblEngItemMaster eim ON eim.ItemID = pod.ItemID
                            WHERE poh.PurchaseActive = 1
                              AND (pod.Received IS NULL OR pod.Received < pod.PurchaseQty)
                              AND pod.ProjectID IN ({','.join(str(int(p)) for p in args.project.split(','))})
                            ORDER BY pod.DateRequired""")
            hdr = [d[0] for d in cur.description]
            print("   " + " | ".join(hdr))
            for row in cur.fetchall():
                print("   " + " | ".join("" if v is None else str(v) for v in row))
        except Exception as ex:
            print(f"   sample failed: {ex}")

    conn.close()
    print("\nDone. Paste the whole output back — then I'll wire Ord Late / Del Late to the real field.")


if __name__ == "__main__":
    main()