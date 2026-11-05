"""patch_exc_cargo_bol.py — add Cargo Ready Date + BOL / Tracking to the Purchasing Exception Report.

Peter asked for two PO-line fields inserted BETWEEN Order Date and Planned Receipt:
  * Cargo Ready Date  <- pod.PurchaseOrderDetailCustom6  (date)
  * BOL / Tracking    <- pod.PurchaseOrderDetailCustom2  (text)
sourced via the live tlkpCaption registry (console_diag_cargo_bol.py).

Touches console_web/etospec.py only: the shared SELECT (query_po_exceptions, feeds BOTH the
po_exceptions and po_listing reports), COLS_EXC, and the three row builders that emit COLS_EXC
rows (exc_detail, po_listing_detail, to_procure_detail). The renderer does r[c[0]] for every
COLS_EXC key, so every builder must set the two new keys or it KeyErrors. The demo path routes
through the same builders (r.get -> '' when absent), so no demo edits are needed.

Run from the repo root:  python patch_exc_cargo_bol.py        (apply)
                         DRY=1 python patch_exc_cargo_bol.py  (validate anchors only, no write)
"""
import io, os, sys
BASE = os.environ.get("BASE", ".")
ES = os.path.join(BASE, "console_web", "etospec.py")
DRY = os.environ.get("DRY") == "1"

EDITS = [
    # 1) shared SELECT: pull the two customs (feeds both reports via query_po_exceptions)
    ('''        CAST(pod.DateRequired AS date)  AS DateRequired,
        CAST(pod.DateRevised  AS date)  AS DateRevised,''',
     '''        CAST(pod.DateRequired AS date)  AS DateRequired,
        CAST(pod.DateRevised  AS date)  AS DateRevised,
        CAST(pod.PurchaseOrderDetailCustom6 AS date) AS CargoReady,   -- Cargo Ready Date (PO-line custom; Peter, 2026-11-05)
        pod.PurchaseOrderDetailCustom2               AS BOLTracking,   -- BOL / Tracking (PO-line custom; Peter, 2026-11-05)''', 1),
    # 2) COLS_EXC: insert the two columns between Order Date and Planned Receipt
    ('''    ("PODate",         "Order Date",               11, "C", False),   # PO header PurchaseDate (Peter col 5; added 2026-10-29)
    ("PlannedReceipt", "Planned Receipt",          12, "C", False),''',
     '''    ("PODate",         "Order Date",               11, "C", False),   # PO header PurchaseDate (Peter col 5; added 2026-10-29)
    ("CargoReady",     "Cargo Ready Date",         12, "C", False),   # PurchaseOrderDetailCustom6 (Peter, 2026-11-05)
    ("BOLTracking",    "BOL / Tracking",           18, "L", False),   # PurchaseOrderDetailCustom2 (Peter, 2026-11-05)
    ("PlannedReceipt", "Planned Receipt",          12, "C", False),''', 1),
    # 3) exc_detail builder: set the two keys (unique PO-issued anchor distinguishes it from po_listing_detail)
    ('''            "PO": ("" if _blank(r.get("PO")) or (not _flag(r.get("PurchasePrinted")) and not _flag(r.get("PurchaseEmailed")))
                   else str(r.get("PO"))),                # PO # only once issued (printed or emailed); a draft is a requisition
            "PODate": _iso(r.get("Ordered")),             # PO header date (entered date; ETO keeps no issue date)''',
     '''            "PO": ("" if _blank(r.get("PO")) or (not _flag(r.get("PurchasePrinted")) and not _flag(r.get("PurchaseEmailed")))
                   else str(r.get("PO"))),                # PO # only once issued (printed or emailed); a draft is a requisition
            "PODate": _iso(r.get("Ordered")),             # PO header date (entered date; ETO keeps no issue date)
            "CargoReady": _iso(r.get("CargoReady")),      # Cargo Ready Date (PurchaseOrderDetailCustom6)
            "BOLTracking": ("" if _blank(r.get("BOLTracking")) else str(r.get("BOLTracking")).strip()),''', 1),
    # 4) po_listing_detail builder: same keys (its PO line is the plain form -> unique)
    ('''            "PO": ("" if _blank(r.get("PO")) else str(r.get("PO"))),
            "PODate": _iso(r.get("Ordered")),             # PO header date (entered date; ETO keeps no issue date)''',
     '''            "PO": ("" if _blank(r.get("PO")) else str(r.get("PO"))),
            "PODate": _iso(r.get("Ordered")),             # PO header date (entered date; ETO keeps no issue date)
            "CargoReady": _iso(r.get("CargoReady")),      # Cargo Ready Date (PurchaseOrderDetailCustom6)
            "BOLTracking": ("" if _blank(r.get("BOLTracking")) else str(r.get("BOLTracking")).strip()),''', 1),
    # 5) to_procure_detail builder: no PO yet -> blanks
    ('''            "ToOrder": _num_or_none(r.get("ToOrder")), "OverOrder": None,
        })''',
     '''            "ToOrder": _num_or_none(r.get("ToOrder")), "OverOrder": None,
            "CargoReady": "", "BOLTracking": "",          # no PO line yet -> no cargo-ready / BOL
        })''', 1),
]


def apply(path, edits):
    raw = io.open(path, "rb").read().decode("utf-8")
    crlf = "\r\n" in raw
    txt = raw.replace("\r\n", "\n")
    ok = True
    for i, (old, new, n) in enumerate(edits, 1):
        c = txt.count(old)
        if c != n:
            print("ANCHOR MISMATCH:", os.path.basename(path), "edit", i, "found", c, "expected", n)
            ok = False
    if not ok:
        sys.exit(2)
    if DRY:
        print("DRY RUN ok:", os.path.basename(path), "- all", len(edits), "anchors matched (no write)")
        return
    for old, new, n in edits:
        txt = txt.replace(old, new)
    if crlf:
        txt = txt.replace("\n", "\r\n")
    io.open(path, "wb").write(txt.encode("utf-8"))
    print("patched", os.path.basename(path), "CRLF" if crlf else "LF")


apply(ES, EDITS)
print("DRY-OK" if DRY else "OK")
