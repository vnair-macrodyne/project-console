import io, os, sys
BASE = os.environ.get("BASE", ".")
ET = os.path.join(BASE, "console_web", "etospec.py")
OM = os.path.join(BASE, "make_procurement_omnibus.py")

ET_OLD = '''COLS_EXC = [   # Peter's layout, in his order ("Sextant_po_exceptions_20260912_Column_Corrections_20261008.xlsx")
    ("Buyer",          "Buyer",                    16, "L", False),
    ("ReqNo",          "Purchasing Requisition #", 14, "L", False),   # the draft PO number (ETO keeps one number from draft to issued PO)
    ("RFQDate",        "RFQ Date",                 11, "C", False),
    ("PO",             "PO #",                     10, "L", False),
    ("Cost",           "Cost",                     12, "R", True),    # PO line extended value in CAD (PO currency x PO rate)
    ("Vendor",         "Vendor",                   20, "L", False),
    ("ProjectID",      "Project #",                 8, "C", False),
    ("JobName",        "Project",                  20, "L", False),
    ("Code",           "Code",                      7, "C", False),   # machine / spec
    ("Item",           "Item",                     11, "L", False),
    ("Manufacturer",   "Manufacturer",             18, "L", False),   # tblEngItemMaster.Manufacturer
    ("MfgPartNo",      "Mfg Part #",               16, "L", False),   # tblEngItemMaster.ManufacturerPartNumber
    ("Description",    "Description",              28, "L", False),
    ("Category",       "Category",                 16, "L", False),
    ("DrawingNo",      "Drawing",                  16, "L", False),
    ("EngRelease",     "Release Date",             11, "C", False),
    ("ReleasedBy",     "Released by",              18, "L", False),   # latest releaser (tblBOMReleaseHistory -> tblEmployee)
    ("RelCount",       "# Releases",                9, "R", True),    # times the part was released on the project
    ("PlannedShip",    "Planned Ship",             11, "C", False),   # greyed by Peter: rule to come
    ("PlannedReceipt", "Planned Receipt",          12, "C", False),
    ("RevisedReceipt", "Revised Receipt",          12, "C", False),
    ("ReceiptDate",    "Receipt Date",             11, "C", False),
    ("Status",         "Status",                   12, "L", False),
    ("LastUpdated",    "Last Activity",            11, "C", False),
    ("MfgBegin",       "Mfg Begins",               11, "C", False),   # tblSpec.MfgBegin for the line's machine
    ("PermitDates",    "Permit Dates",             12, "L", False),   # greyed by Peter: rule to come
    ("LeadTime",       "Lead Time",                 8, "R", True),    # number; a historical fallback is italicised via _em
    ("Oversized",      "Oversized",                 8, "C", False),   # greyed by Peter: rule to come
    ("Inspected",      "Inspected",                 8, "C", False),   # greyed by Peter: rule to come
    ("Critical",       "Critical",                  8, "C", False),
    ("LLT",            "LLT",                       9, "C", False),   # PartCustom7 'Long Lead Item'
]'''

ET_NEW = '''COLS_EXC = [   # Peter's re-ordered export layout (Col_Numbering_Sextant_po_listing_20261028.xlsx): cols 1-28, then Released by / # Releases appended
    ("Buyer",          "Buyer",                    16, "L", False),
    ("ReqNo",          "Purchasing Requisition #", 14, "L", False),   # the draft PO number (ETO keeps one number from draft to issued PO)
    ("RFQDate",        "RFQ Date",                 11, "C", False),
    ("PO",             "PO #",                     10, "L", False),
    ("PODate",         "Order Date",               11, "C", False),   # PO header PurchaseDate (Peter col 5; added 2026-10-29)
    ("Cost",           "Cost",                     12, "R", True),    # PO line extended value in CAD (PO currency x PO rate)
    ("Vendor",         "Vendor",                   20, "L", False),
    ("ProjectID",      "Project #",                 8, "C", False),
    ("JobName",        "Project",                  20, "L", False),
    ("Code",           "Code",                      7, "C", False),   # machine / spec
    ("Item",           "Item",                     11, "L", False),
    ("Manufacturer",   "Manufacturer",             18, "L", False),   # tblEngItemMaster.Manufacturer
    ("MfgPartNo",      "Mfg Part #",               16, "L", False),   # tblEngItemMaster.ManufacturerPartNumber
    ("Description",    "Description",              28, "L", False),
    ("Category",       "Category",                 16, "L", False),
    ("DrawingNo",      "Drawing",                  16, "L", False),
    ("EngRelease",     "Release Date",             11, "C", False),
    ("PlannedReceipt", "Planned Receipt",          12, "C", False),
    ("RevisedReceipt", "Revised Receipt",          12, "C", False),
    ("ReceiptDate",    "Receipt Date",             11, "C", False),
    ("LastUpdated",    "Last Activity",            11, "C", False),
    ("MfgBegin",       "Mfg Begins",               11, "C", False),   # tblSpec.MfgBegin for the line's machine
    ("PermitDates",    "Permit Dates",             12, "L", False),   # greyed by Peter: rule to come
    ("LeadTime",       "Lead Time",                 8, "R", True),    # number; a historical fallback is italicised via _em
    ("Oversized",      "Oversized",                 8, "C", False),   # greyed by Peter: rule to come
    ("Inspected",      "Inspected",                 8, "C", False),   # greyed by Peter: rule to come
    ("Critical",       "Critical",                  8, "C", False),
    ("LLT",            "LLT",                       9, "C", False),   # PartCustom7 'Long Lead Item'
    ("ReleasedBy",     "Released by",              18, "L", False),   # latest releaser (tblBOMReleaseHistory -> tblEmployee)
    ("RelCount",       "# Releases",                9, "R", True),    # times the part was released on the project
]'''

OM_OLD = '''    omni_cols = [("Stage", "Stage", "text", "left"), ("OrderDate", "Order Date", "date", "left")] + \\
        [(k, l, t, a) for (k, l, t, a, w) in etospec.web_columns(etospec.COLS_EXC)] + \\
        [("ReleasedBy", "Released by", "text", "left"), ("RelCount", "# Releases", "int", "right")]'''

OM_NEW = '''    omni_cols = [("Stage", "Stage", "text", "left")] + \\
        [(k, l, t, a) for (k, l, t, a, w) in etospec.web_columns(etospec.COLS_EXC)]'''

FILES = {ET: [(ET_OLD, ET_NEW, 1)], OM: [(OM_OLD, OM_NEW, 1)]}

for path, edits in FILES.items():
    txt = io.open(path, "rb").read().decode("utf-8").replace("\r\n", "\n")
    for i, (old, new, n) in enumerate(edits, 1):
        if txt.count(old) != n:
            print("ABORT:", os.path.basename(path), "edit", i, "found", txt.count(old), "expected", n); sys.exit(2)
for path, edits in FILES.items():
    raw = io.open(path, "rb").read().decode("utf-8"); crlf = "\r\n" in raw
    txt = raw.replace("\r\n", "\n")
    for old, new, n in edits:
        txt = txt.replace(old, new)
    if crlf: txt = txt.replace("\n", "\r\n")
    io.open(path, "wb").write(txt.encode("utf-8"))
    print("patched", os.path.basename(path), "CRLF" if crlf else "LF")
print("OK")
