"""
console_diag_po_lastupdated.py — does ETO hold a usable "Last Updated" for a PO line? (2026-08-14)

The PO Exception / PO Listing reports carry a "Last Updated" column that we currently leave BLANK,
because the field probe found no per-PO-line modified timestamp — only the header's
`PurchaseDateRevised`, which we suspected is (a) header-level and (b) rarely populated. Vijay asked
to confirm: do we actually have no dates there?

This probe:
  A. lists every candidate timestamp column on the PO header/detail objects (name matches
     modif / updat / changed / revis / lastmod / edit / date), so we don't miss one;
  B. for the promising ones, COUNTS how many active POs actually have them populated, and — for
     PurchaseDateRevised — whether it differs from PurchaseDate (ordered) or is just a static copy;
  C. samples a few real rows so we can eyeball whether the value looks like an audit "last touched"
     timestamp or something else.

READ-ONLY. Run:  python console_diag_po_lastupdated.py   → paste the whole output.
"""
import sys

HINTS = ("modif", "updat", "changed", "change", "revis", "lastmod", "last_mod",
         "edit", "touch", "stamp", "logdate", "entered", "created")
OBJECTS = ["vwPurchaseOrderHeader", "vwPurchaseOrderDetails", "vwPurchaseOrderDetailsDetailed",
           "tblPurchaseOrderHeader", "tblPurchaseOrderDetails"]


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
    cur.execute("SELECT COLUMN_NAME, DATA_TYPE FROM INFORMATION_SCHEMA.COLUMNS "
                "WHERE TABLE_NAME = ? ORDER BY ORDINAL_POSITION", (name,))
    return [(r[0], r[1]) for r in cur.fetchall()]


def main():
    conn = eto_connect()
    cur = conn.cursor()
    try:
        # ── A. every date/timestamp-ish column on the PO objects ─────────────────
        rule("A. CANDIDATE TIMESTAMP COLUMNS on the PO header/detail objects")
        candidates = {}                                   # obj -> [colname, ...] of date-ish hits
        for obj in OBJECTS:
            cols = columns_of(cur, obj)
            if not cols:
                print(f"\n  {obj}: (not found)")
                continue
            hits = [n for n, t in cols
                    if any(h in n.lower() for h in HINTS) or "date" in t.lower()
                    or "time" in t.lower()]
            candidates[obj] = hits
            print(f"\n  {obj}: {len(cols)} cols — date/timestamp-ish: "
                  + (", ".join(hits) if hits else "(none)"))

        # ── B. population of the header revision date (our only real candidate) ──
        rule("B. PurchaseDateRevised — is it populated, and does it move vs PurchaseDate?")
        run(cur, "B1. active-PO header: revised-date population + differs-from-ordered",
            "SELECT COUNT(*) AS active_POs, "
            "       SUM(CASE WHEN PurchaseDateRevised IS NOT NULL THEN 1 ELSE 0 END) AS has_revised, "
            "       SUM(CASE WHEN PurchaseDateRevised IS NOT NULL "
            "                 AND CAST(PurchaseDateRevised AS date) <> CAST(PurchaseDate AS date) "
            "                THEN 1 ELSE 0 END) AS revised_differs_from_ordered "
            "FROM dbo.vwPurchaseOrderHeader WHERE PurchaseActive = 1")

        # ── B2. any OTHER header/detail timestamp that's actually filled ─────────
        rule("B2. population of every other candidate timestamp (active POs / their lines)")
        for obj, hits in candidates.items():
            base = "WHERE PurchaseActive = 1" if obj.endswith("Header") else ""
            for col in hits:
                if col.lower() in ("purchasedate", "purchasedaterevised"):
                    continue
                run(cur, f"B2/{obj}.{col}",
                    f"SELECT COUNT(*) AS rows_, "
                    f"SUM(CASE WHEN [{col}] IS NOT NULL THEN 1 ELSE 0 END) AS has_value, "
                    f"MIN([{col}]) AS min_val, MAX([{col}]) AS max_val "
                    f"FROM dbo.{obj} {base}", max_rows=1)

        # ── C. sample rows so we can eyeball what the values look like ───────────
        rule("C. SAMPLE — a few active POs: ordered vs revised date (recent first)")
        run(cur, "C1. header dates on recent active POs",
            "SELECT TOP 20 PurchaseOrderID, "
            "       CAST(PurchaseDate AS date) AS Ordered, "
            "       CAST(PurchaseDateRevised AS date) AS Revised, "
            "       PurchasePrinted, PurchaseEmailed "
            "FROM dbo.vwPurchaseOrderHeader WHERE PurchaseActive = 1 "
            "ORDER BY PurchaseOrderID DESC")
    finally:
        conn.close()
    print("\nDone. Paste the whole output. How to read it:\n"
          "  • A = the only columns that could feed 'Last Updated'. If nothing beyond\n"
          "    PurchaseDate / PurchaseDateRevised shows up, ETO simply has no per-line audit stamp.\n"
          "  • B1 = of active POs, how many have PurchaseDateRevised at all, and how many where it\n"
          "    actually differs from the ordered date. If has_revised is low, or it rarely differs,\n"
          "    it is NOT a usable 'last updated' — keep the column blank.\n"
          "  • B2 = any other timestamp that's actually filled (would be a better source if so).\n"
          "  • C = eyeball the values. Then we decide: use PurchaseDateRevised as the proxy, or\n"
          "    leave Last Updated blank as we do now.")


if __name__ == "__main__":
    main()
