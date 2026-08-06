"""
console_diag_project_made_parts.py — how do PROJECT-MADE parts tie to a project & to on-hand?
(2026-08-06)

WHY: the inventory report is scoped to *purchased* items on a project's PO lines with on-hand > 0.
A part MADE for the project (e.g. numbered like  220154-10M0 ) is never on a PO, so it's invisible
even though it's stocked / being shipped. We want to broaden inventory scope to include
project-made parts that are available to the project. To do that correctly we must first learn the
LINK ETO uses. Three candidates this maps and ranks:

  (A) NAMING CONVENTION — the item number is prefixed with the project number
      (ItemCompanyID LIKE '<project>%').  Cheapest, but must be confirmed real & complete.
  (B) A MANUFACTURING / WORK-ORDER / JOB / SPEC object carrying ProjectID + ItemID.
      Authoritative if it exists.
  (C) The ITEM MASTER carries a make/buy flag (+ a Project/Spec tie) distinguishing made vs bought.

READ-ONLY. Run:
    python console_diag_project_made_parts.py                 # project 220154, auto item-prefix
    python console_diag_project_made_parts.py 220154 220154-10M0   # explicit project + item pattern
Paste the WHOLE output back.
"""

import sys

MFG_CANDIDATES = [
    "tblManufacturing", "vwManufacturing", "tblManufacturedItem", "vwManufacturedItems",
    "tblWorkOrder", "tblWorkOrders", "vwWorkOrder", "vwWorkOrders",
    "tblShopOrder", "vwShopOrder", "tblJob", "tblJobs", "vwJob", "vwJobs",
    "tblProduction", "vwProduction", "tblAssembly", "vwAssembly",
    "tblMakeItem", "tblBuildItem", "tblManufacturingOrder", "vwManufacturingOrder",
    "tblSpec", "vwSpec", "tblSpecItem", "vwSpecItem", "tblSpecDetail",
    "tblBOM", "tblBillOfMaterial", "vwBOM", "tblProjectItem", "vwProjectItem",
    "tblProjectPart", "vwProjectPart",
]
ITEM_OBJECTS = ["tblItem", "tblItems", "vwItem", "vwItems", "vwItemMaster",
                "tblInventoryItem", "vwInventoryItem", "tblPart", "vwPart", "tblParts"]

PROJ_HINTS = ("projectid", "specid")
ITEM_HINTS = ("itemid", "itemcompanyid", "itemno", "partid", "partno", "partnumber")
QTY_HINTS = ("qty", "quantity", "onhand", "made", "built", "completed")
MAKEBUY_HINTS = ("makebuy", "make_buy", "manufactured", "purchased", "sourcetype", "itemtype",
                 "makeorbuy", "procurement", "buymake")
DATE_HINTS = ("date", "completed", "created", "due")


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


def run(cur, label, sql, params=(), max_rows=25):
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
    try:
        cur.execute("SELECT COLUMN_NAME, DATA_TYPE FROM INFORMATION_SCHEMA.COLUMNS "
                    "WHERE TABLE_NAME = ? ORDER BY ORDINAL_POSITION", (name,))
        return [(r[0], r[1]) for r in cur.fetchall()]
    except Exception:
        return []


def has_col(cols, name):
    return any(c[0].lower() == name.lower() for c in cols)


def flag(nl):
    m = ""
    if nl in PROJ_HINTS:
        m += " *"        # project link
    if any(h in nl for h in ITEM_HINTS):
        m += " #"        # item
    if any(h in nl for h in QTY_HINTS):
        m += " >"        # qty
    if any(h in nl for h in MAKEBUY_HINTS):
        m += " M/B"      # make-or-buy flag
    if any(h in nl for h in DATE_HINTS):
        m += " ~"        # date
    return m


def main():
    args = [a for a in sys.argv[1:]]
    proj = next((a for a in args if a.isdigit()), "220154")
    # item pattern: explicit 2nd arg, else derive from the project number
    pat = next((a for a in args if not a.isdigit()), None) or f"{proj}%"
    if "%" not in pat:
        pat = pat + "%"
    conn = eto_connect()
    cur = conn.cursor()
    print(f"Project = {proj}   item-number pattern = '{pat}'")
    existing = {}
    try:
        # ── A. does the item number carry the project number? (naming test) ───
        rule("A. NAMING-CONVENTION TEST — vwInventory items whose number starts with the project")
        run(cur, f"A1. vwInventory rows LIKE '{pat}' (ALL on-hand, incl. 0 — catches shipped-out)",
            "SELECT ItemCompanyID, ItemDescription, LocationName, BinLabel, QtyOnHand, "
            "QtyMinRequired "
            "FROM dbo.vwInventory WHERE ItemCompanyID LIKE ? ORDER BY ItemCompanyID", (pat,))
        run(cur, f"A2. how many match, and how many are on-hand > 0 (available)",
            "SELECT COUNT(*) AS matching_rows, "
            "SUM(CASE WHEN QtyOnHand > 0 THEN 1 ELSE 0 END) AS available_rows, "
            "COUNT(DISTINCT ItemID) AS distinct_items "
            "FROM dbo.vwInventory WHERE ItemCompanyID LIKE ?", (pat,))
        run(cur, "A3. are these ALSO on the project's PO lines? (overlap vs current PO scope)",
            "SELECT COUNT(DISTINCT v.ItemID) AS name_matched_items, "
            "COUNT(DISTINCT p.ItemID) AS also_on_project_POs "
            "FROM dbo.vwInventory v "
            "LEFT JOIN (SELECT DISTINCT ItemID FROM dbo.vwPurchaseOrderDetails WHERE ProjectID = ?) p "
            "  ON p.ItemID = v.ItemID "
            "WHERE v.ItemCompanyID LIKE ?", (proj, pat))

        # ── B. manufacturing / work-order / job / spec objects ────────────────
        rule("B. MFG / WORK-ORDER / JOB / SPEC OBJECTS  (* project  # item  > qty  M/B flag  ~ date)")
        found_mfg = {}
        for name in MFG_CANDIDATES:
            cols = columns_of(cur, name)
            if not cols:
                continue
            found_mfg[name] = cols
            existing[name] = cols
            proj_col = "★ProjectID" if any(c[0].lower() in PROJ_HINTS for c in cols) else \
                       "(no direct project col)"
            print(f"\n  {name} ({len(cols)} cols) — {proj_col}")
            for n, t in cols:
                print(f"    {n} : {t}{flag(n.lower())}")
        if not found_mfg:
            print("  (none of the curated mfg/job/spec candidates exist — check names another way)")

        # sample the ones that link project + item
        rule(f"C. MFG/JOB/SPEC SAMPLE for project {proj} (objects carrying both ProjectID & an item)")
        for name, cols in found_mfg.items():
            pc = next((c[0] for c in cols if c[0].lower() in PROJ_HINTS), None)
            ic = next((c[0] for c in cols if c[0].lower() in ITEM_HINTS), None)
            if not (pc and ic):
                continue
            run(cur, f"C/{name} — rows for project {proj}",
                f"SELECT TOP 20 * FROM dbo.{name} WHERE [{pc}] = ?", (proj,))

        # ── D. item master: make/buy flag + project/spec tie ──────────────────
        rule("D. ITEM MASTER — make/buy flag & any project/spec tie (for the matched items)")
        for name in ITEM_OBJECTS:
            cols = columns_of(cur, name)
            if not cols:
                continue
            existing[name] = cols
            mb = [c[0] for c in cols if any(h in c[0].lower() for h in MAKEBUY_HINTS)]
            pj = [c[0] for c in cols if c[0].lower() in PROJ_HINTS]
            idc = next((c for c in ("ItemCompanyID", "ItemNo", "PartNo", "PartNumber")
                        if has_col(cols, c)), None)
            print(f"\n  {name}: make/buy cols = {mb or '(none)'} ; project cols = {pj or '(none)'}")
            if idc and (mb or pj):
                sel = ", ".join(f"[{c}]" for c in
                                ([idc] + (["ItemDescription"] if has_col(cols, "ItemDescription")
                                          else []) + mb + pj))
                run(cur, f"D/{name} — matched items with make/buy & project cols",
                    f"SELECT TOP 20 {sel} FROM dbo.{name} WHERE [{idc}] LIKE ?", (pat,))

        # ── E. THE COVERAGE GAP — made parts missing from today's PO scope ────
        rule(f"E. COVERAGE GAP — on-hand items for project {proj} NOT reachable via PO scope")
        run(cur, "E1. name-matched, on-hand > 0, but NOT on any project PO (the missing made parts)",
            "SELECT v.ItemCompanyID, v.ItemDescription, v.LocationName, v.QtyOnHand "
            "FROM dbo.vwInventory v "
            "WHERE v.ItemCompanyID LIKE ? AND v.QtyOnHand > 0 "
            "AND v.ItemID NOT IN (SELECT DISTINCT ItemID FROM dbo.vwPurchaseOrderDetails "
            "                     WHERE ProjectID = ?) "
            "ORDER BY v.QtyOnHand DESC", (pat, proj))

        # ── F. project-link summary ───────────────────────────────────────────
        rule("F. PROJECT-LINK SUMMARY")
        direct = [n for n, cols in existing.items()
                  if any(c[0].lower() in PROJ_HINTS for c in cols)]
        print("  Objects that carry a direct ProjectID/SpecID (authoritative made-part→project link):")
        print("    " + (", ".join(direct) or "(none — fall back to the item-number naming convention)"))

    finally:
        conn.close()

    print("\nDone. Paste the whole output. Decision it drives:")
    print("  • If A shows the project-prefixed items with on-hand (A1/E1 non-empty) and A3 confirms")
    print("    they're mostly NOT on POs → naming convention is a valid scope-broadening key.")
    print("  • If B/C surface a mfg/job/spec object with ProjectID+ItemID → use that as the")
    print("    authoritative link instead of (or alongside) the name prefix.")
    print("  • D tells us whether the item master can label Made vs Purchased for a 'Source' column.")
    print("  • E is the concrete list of parts today's report is missing for this project.")


if __name__ == "__main__":
    main()
