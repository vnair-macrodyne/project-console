"""
console_diag_po_late2.py — read ETO's native late report `urpPurchasingLateVendors`
so we can source "Ord/Del Late" from IT instead of a lead-time estimate (read-only).

The first probe found ETO's own late report is the stored proc `urpPurchasingLateVendors`,
but the reporting account can't see its definition (no VIEW DEFINITION). This probe:
  1. lists the proc's PARAMETERS (so we know how to call it),
  2. tries to read its TEXT three ways (works if the account has permission),
  3. checks how populated the REAL date fields are (detail + header required/revised),
  4. EXECUTES the proc and shows its output columns + a few rows — the surest way to
     see what ETO itself calls "late" and which dates it surfaces.
Nothing is written — SELECT / EXEC of a read-only report proc only.

Run on the box:
    python console_diag_po_late2.py
    python console_diag_po_late2.py --project 230219
Paste the WHOLE output back.
"""
import argparse

PROC = "urpPurchasingLateVendors"


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


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--project", default=None)
    ap.add_argument("--no-exec", action="store_true", help="skip EXEC of the report proc")
    args = ap.parse_args()
    conn = connect(); cur = conn.cursor()

    # 1. parameters of the late-report proc (how to call it)
    rule(f"1. PARAMETERS of dbo.{PROC}")
    try:
        cur.execute("""SELECT PARAMETER_NAME, DATA_TYPE, PARAMETER_MODE
                       FROM INFORMATION_SCHEMA.PARAMETERS
                       WHERE SPECIFIC_NAME = ? ORDER BY ORDINAL_POSITION""", PROC)
        prm = cur.fetchall()
        if not prm:
            print("   (no parameters — callable as: EXEC dbo.%s)" % PROC)
        for name, typ, mode in prm:
            print(f"   {name or '(return)':28} {typ:12} {mode}")
    except Exception as ex:
        print(f"   !! {ex}")

    # 2. try to read the proc TEXT three ways
    rule(f"2. TEXT of dbo.{PROC} (blank if the account lacks VIEW DEFINITION)")
    got = False
    for label, sql, arg in [
        ("OBJECT_DEFINITION", "SELECT OBJECT_DEFINITION(OBJECT_ID(?))", f"dbo.{PROC}"),
        ("sys.sql_modules",
         "SELECT m.definition FROM sys.sql_modules m JOIN sys.objects o "
         "ON o.object_id=m.object_id WHERE o.name=?", PROC),
    ]:
        try:
            cur.execute(sql, arg)
            r = cur.fetchone()
            if r and r[0]:
                got = True
                print(f"   [{label}]")
                for line in r[0].replace("\r", "").splitlines():
                    print("     " + line)
                break
        except Exception as ex:
            print(f"   [{label}] !! {ex}")
    if not got:
        try:
            cur.execute("EXEC sp_helptext ?", f"dbo.{PROC}")
            txt = [row[0] for row in cur.fetchall()]
            if txt:
                got = True
                print("   [sp_helptext]")
                for line in txt:
                    print("     " + str(line).rstrip())
        except Exception as ex:
            print(f"   [sp_helptext] !! {ex}")
    if not got:
        print("   (could not read the proc text with this account — rely on the EXEC output below,\n"
              "    or have someone with VIEW DEFINITION run:  EXEC sp_helptext '%s')" % PROC)

    # 3. populated-ness of the REAL date fields on open lines (detail + header)
    rule("3. OPEN PO lines — how populated are the required/revised dates?")
    scope = ""
    if args.project:
        ids = ",".join(str(int(p)) for p in args.project.split(","))
        scope = f" AND pod.ProjectID IN ({ids})"
    try:
        cur.execute(f"""
            SELECT COUNT(*) AS OpenLines,
                   COUNT(pod.DateRequired)        AS Det_Required,
                   COUNT(pod.DateRevised)         AS Det_Revised,
                   COUNT(poh.PurchaseDateRequired) AS Hdr_Required,
                   COUNT(poh.PurchaseDateRevised)  AS Hdr_Revised
            FROM vwPurchaseOrderDetails pod
            JOIN vwPurchaseOrderHeader poh ON poh.PurchaseOrderID = pod.PurchaseOrderID
            WHERE poh.PurchaseActive = 1
              AND (pod.Received IS NULL OR pod.Received < pod.PurchaseQty){scope}""")
        o, dr, dv, hr, hv = cur.fetchone()
        print(f"   open lines={o}")
        print(f"   detail DateRequired  non-null {dr}/{o}")
        print(f"   detail DateRevised   non-null {dv}/{o}")
        print(f"   header PurchaseDateRequired non-null {hr}/{o}")
        print(f"   header PurchaseDateRevised  non-null {hv}/{o}")
    except Exception as ex:
        print(f"   !! {ex}")

    # 3b. sample lines: detail vs header required/revised + lead time
    if args.project:
        rule(f"3b. SAMPLE open lines for project {args.project}")
        ids = ",".join(str(int(p)) for p in args.project.split(","))
        try:
            cur.execute(f"""
                SELECT TOP 15 poh.PurchaseOrderID AS PO, pod.ItemID AS Item,
                       CAST(pod.DateRequired AS date)          AS DetReq,
                       CAST(pod.DateRevised  AS date)          AS DetRev,
                       CAST(poh.PurchaseDateRequired AS date)  AS HdrReq,
                       CAST(poh.PurchaseDateRevised  AS date)  AS HdrRev,
                       eim.EstimatedLeadTime                   AS Lead,
                       pod.Received AS Rec, pod.PurchaseQty AS Qty
                FROM vwPurchaseOrderDetails pod
                JOIN vwPurchaseOrderHeader poh ON poh.PurchaseOrderID = pod.PurchaseOrderID
                LEFT JOIN tblEngItemMaster eim ON eim.ItemID = pod.ItemID
                WHERE poh.PurchaseActive = 1
                  AND (pod.Received IS NULL OR pod.Received < pod.PurchaseQty)
                  AND pod.ProjectID IN ({ids})
                ORDER BY pod.DateRequired""")
            hdr = [d[0] for d in cur.description]
            print("   " + " | ".join(hdr))
            for row in cur.fetchall():
                print("   " + " | ".join("" if v is None else str(v) for v in row))
        except Exception as ex:
            print(f"   sample failed: {ex}")

    # 4. EXECUTE the native late report and show what it returns
    if not args.no_exec:
        rule(f"4. EXEC dbo.{PROC} — output columns + first rows (what ETO calls 'late')")
        for call in (f"EXEC dbo.{PROC}",
                     f"EXEC dbo.{PROC} @ProjectID = {args.project.split(',')[0]}" if args.project else None):
            if not call:
                continue
            try:
                cur.execute(call)
                cols = [d[0] for d in cur.description] if cur.description else []
                print(f"   CALL OK: {call}")
                print("   columns: " + ", ".join(cols))
                rows = cur.fetchmany(12)
                for row in rows:
                    print("   " + " | ".join("" if v is None else str(v)[:24] for v in row))
                break
            except Exception as ex:
                print(f"   {call}  -> {ex}")

    conn.close()
    print("\nDone. Paste the whole output back.")


if __name__ == "__main__":
    main()
