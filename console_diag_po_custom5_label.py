"""
console_diag_po_custom5_label.py — what does ETO CALL PurchaseOrderHeaderCustom5? (2026-08-14)

The PO Last-Updated probe found that `PurchaseOrderHeaderCustom5` is the only PO custom DATE field
with any real population (~11% of headers, values 2023-2026). Before deciding whether to surface it
(e.g. as "Last Updated" or under its real name), we need to know what Macrodyne configured it to
MEAN — i.e. the caption/label ETO shows for that field on the PO screen. Total ETO stores custom
field captions in a lookup/config table; this probe finds that table and reads the caption, and — as
a fallback — infers the field's meaning empirically from its values.

This probe:
  A. finds candidate caption/label/custom-field-definition tables by name;
  B. dumps their columns and any ROWS that reference a PurchaseOrder custom field / the text
     'Custom5' / a caption — so we can read the configured label directly;
  C. samples populated PurchaseOrderHeaderCustom5 values next to the PO's ordered / required dates,
     so if the caption can't be found we can still infer what the date represents.

READ-ONLY. Run:  python console_diag_po_custom5_label.py   → paste the whole output.
"""
NAME_LIKE = ("%custom%", "%caption%", "%label%", "%fieldname%", "%userfield%",
             "%terminology%", "%fielddef%", "%screenfield%")
CAPTION_COL_HINTS = ("caption", "label", "displayname", "prompt", "title", "description", "name",
                     "terminology", "fieldname")
KEY_COL_HINTS = ("field", "column", "custom", "name", "key", "tag", "id")


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


def run(cur, label, sql, params=(), max_rows=60):
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


def main():
    conn = eto_connect()
    cur = conn.cursor()
    try:
        # ── A. candidate caption/custom-field tables by name ─────────────────────
        rule("A. CANDIDATE caption / custom-field-definition tables (by name)")
        like = " OR ".join(["TABLE_NAME LIKE ?"] * len(NAME_LIKE))
        cur.execute("SELECT TABLE_NAME FROM INFORMATION_SCHEMA.TABLES "
                    f"WHERE ({like}) ORDER BY TABLE_NAME", NAME_LIKE)
        cand = [r[0] for r in cur.fetchall()]
        print("  " + ("\n  ".join(cand) if cand else "(none found)"))

        # ── B. for each candidate, columns + rows mentioning a PO custom field ───
        rule("B. columns of each candidate, + any row referencing a PurchaseOrder custom5 caption")
        for t in cand:
            cur.execute("SELECT COLUMN_NAME, DATA_TYPE FROM INFORMATION_SCHEMA.COLUMNS "
                        "WHERE TABLE_NAME = ? ORDER BY ORDINAL_POSITION", (t,))
            cols = [(r[0], r[1]) for r in cur.fetchall()]
            colnames = [c for c, _ in cols]
            print(f"\n  ── {t} ({len(cols)} cols): " + ", ".join(colnames))
            # text columns we can search for 'Custom5' / 'PurchaseOrder'
            text_cols = [c for c, dt in cols if dt.lower() in
                         ("varchar", "nvarchar", "char", "nchar", "text", "ntext")]
            if not text_cols:
                continue
            where = " OR ".join([f"[{c}] LIKE '%Custom5%' OR [{c}] LIKE '%PurchaseOrder%' "
                                 f"OR [{c}] LIKE '%PO %'" for c in text_cols])
            run(cur, f"B/{t} — rows mentioning Custom5 / PurchaseOrder",
                f"SELECT TOP 40 * FROM dbo.[{t}] WHERE {where}", max_rows=40)

        # ── C. empirical: sample populated Custom5 next to the PO's own dates ────
        rule("C. EMPIRICAL — populated PurchaseOrderHeaderCustom5 vs ordered / required dates")
        run(cur, "C1. 30 most-recent active POs that HAVE Custom5 set",
            "SELECT TOP 30 PurchaseOrderID, "
            "       CAST(PurchaseDate AS date)          AS Ordered, "
            "       CAST(PurchaseDateRequired AS date)  AS Required, "
            "       CAST(PurchaseDateRevised AS date)   AS Revised, "
            "       CAST(PurchaseOrderHeaderCustom5 AS date) AS Custom5, "
            "       DATEDIFF(day, PurchaseDate, PurchaseOrderHeaderCustom5) AS days_after_ordered "
            "FROM dbo.vwPurchaseOrderHeader "
            "WHERE PurchaseActive = 1 AND PurchaseOrderHeaderCustom5 IS NOT NULL "
            "ORDER BY PurchaseOrderID DESC", max_rows=30)
        run(cur, "C2. how Custom5 sits relative to the ordered date (distribution)",
            "SELECT CASE "
            "         WHEN c5 < ordered THEN 'before ordered' "
            "         WHEN c5 = ordered THEN 'same as ordered' "
            "         WHEN c5 <= DATEADD(day,60,ordered) THEN 'within 60d after' "
            "         ELSE 'more than 60d after' END AS bucket, "
            "       COUNT(*) AS pos "
            "FROM (SELECT CAST(PurchaseDate AS date) AS ordered, "
            "             CAST(PurchaseOrderHeaderCustom5 AS date) AS c5 "
            "      FROM dbo.vwPurchaseOrderHeader "
            "      WHERE PurchaseActive = 1 AND PurchaseOrderHeaderCustom5 IS NOT NULL) x "
            "GROUP BY CASE "
            "         WHEN c5 < ordered THEN 'before ordered' "
            "         WHEN c5 = ordered THEN 'same as ordered' "
            "         WHEN c5 <= DATEADD(day,60,ordered) THEN 'within 60d after' "
            "         ELSE 'more than 60d after' END "
            "ORDER BY pos DESC")
    finally:
        conn.close()
    print("\nDone. Paste the whole output. How to read it:\n"
          "  • A/B = if ETO stores the caption, one of these tables holds a row tying a PurchaseOrder\n"
          "    custom-5 field to a human label (e.g. 'Confirmed Date', 'Expedite Date'). That label\n"
          "    is the field's real meaning.\n"
          "  • C = if no caption table exists, the values themselves hint at meaning: mostly AFTER\n"
          "    the ordered date suggests a confirmation/expedite/promise date; equal-to-ordered\n"
          "    suggests a copy; scattered suggests it's not a reliable single concept.\n"
          "  Then we decide whether to surface Custom5 (under its real name) or leave it alone.")


if __name__ == "__main__":
    main()
