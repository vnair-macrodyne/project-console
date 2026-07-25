"""
Exporters — turn any QueryResult into a downloadable Excel workbook or PDF.

Both are generic: they read the QueryResult's typed columns and format each cell
by column type (hours / money / pct / date / int / text), so a new query needs no
exporter changes. Output is tenant-branded (product + company + header colour).
"""
import io
from datetime import datetime

from console_web.queries import branding
from console_web import etospec


# ─────────────────────────────────────────────────────────────────────────────
# value formatting shared by both exporters
# ─────────────────────────────────────────────────────────────────────────────
def _fmt(value, ctype):
    if value is None or value == "":
        return ""
    try:
        if ctype == "hours":
            return "{:,.0f}".format(float(value))
        if ctype == "num":
            f = float(value)
            return "{:,.0f}".format(f) if f == int(f) else "{:,.2f}".format(f)
        if ctype == "money":
            return "${:,.0f}".format(float(value))
        if ctype == "money2":
            return "${:,.2f}".format(float(value))
        if ctype == "pct":
            return "{:.1f}%".format(float(value) * 100)
        if ctype == "int":
            return "{:,d}".format(int(float(value)))
        if ctype == "id":
            return str(int(float(value)))
    except (TypeError, ValueError):
        return str(value)
    return str(value)


def _ts():
    # container clock only; label, not logic
    return datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")


# Executive-dashboard palette (mirrors console_dashboard.py)
C_GROUP = "2E75B6"   # medium-blue block band
C_WARN = "FFEB9C"    # 90–100% amber
C_BAD = "FFC7CE"     # >100% / slipped red
C_ZEBRA = "F2F4F8"


def _tl_hex(ctype, value):
    """Traffic-light fill (amber/red) for a cell — matches the workbook rules."""
    if value is None:
        return None
    try:
        v = float(value)
    except (TypeError, ValueError):
        return None
    if ctype == "pct":
        if v > 1.0:
            return C_BAD
        if v >= 0.9:
            return C_WARN
    elif ctype == "days":
        if v > 0:
            return C_BAD
    return None


def _blocks(columns):
    """Contiguous (block_label, start_index, span) runs across the columns."""
    runs = []
    i = 0
    while i < len(columns):
        blk = columns[i].block
        span = 1
        while i + span < len(columns) and columns[i + span].block == blk:
            span += 1
        runs.append((blk, i, span))
        i += span
    return runs


# ─────────────────────────────────────────────────────────────────────────────
# Excel
# ─────────────────────────────────────────────────────────────────────────────
def _spec_xlsx(exp) -> bytes:
    """Faithful workbook for a deployed eto-reporting report (labour / PO), built by
    the vendored writer so the download matches the on-prem report exactly."""
    kind = exp["kind"]
    if kind == "labour":
        return etospec.labour_book_bytes(exp["report_id"], exp["period_rows"],
                                         exp["life_rows"], exp["p_label"], exp["l_label"])
    if kind == "po_status":
        return etospec.po_status_book_bytes(exp["df"], exp["label"])
    if kind == "exceptions":
        return etospec.exceptions_book_bytes(exp["items"], exp["label"])
    if kind == "late":
        return etospec.late_vendors_book_bytes(exp["df"], exp["label"])
    if kind == "delivered":
        return etospec.delivered_book_bytes(exp["df"], exp["label"])
    raise ValueError(f"unknown spec export kind '{kind}'")


def to_xlsx(result) -> bytes:
    exp = getattr(result, "export", None)
    if exp:
        return _spec_xlsx(exp)
    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
    from openpyxl.utils import get_column_letter

    b = branding()
    hexcolor = (b["color"] or "1F3864").lstrip("#")
    wb = Workbook()
    ws = wb.active
    ws.title = result.query_id[:31] or "Result"

    head_fill = PatternFill("solid", fgColor=hexcolor)
    head_font = Font(name="Helvetica", bold=True, color="FFFFFF", size=9)
    group_fill = PatternFill("solid", fgColor=C_GROUP)
    group_font = Font(name="Helvetica", bold=True, color="FFFFFF", size=9)
    title_font = Font(name="Helvetica", bold=True, size=14, color=hexcolor)
    sub_font = Font(name="Helvetica", size=9, color="808080")
    zebra_fill = PatternFill("solid", fgColor=C_ZEBRA)
    thin = Side(style="thin", color="D9D9D9")
    border = Border(bottom=thin)

    cols = result.columns
    grouped = any(c.block for c in cols)
    ncols = max(len(cols), 1)
    ws.cell(1, 1, f"{b['product']} — {result.title}").font = title_font
    ws.cell(2, 1, f"{b['company']}   ·   generated {_ts()}").font = sub_font
    line3 = result.note or ("   ".join(f"{c.label}: {c.value}" for c in result.cards))
    if line3:
        ws.cell(3, 1, line3).font = sub_font

    # ── group band (Executive Dashboard only) ──────────────────────────────
    group_row = 5 if grouped else None
    header_row = 6 if grouped else 5
    if grouped:
        for blk, start, span in _blocks(cols):
            c = ws.cell(group_row, start + 1, blk or "")
            c.font = group_font
            c.alignment = Alignment(horizontal="center", vertical="center")
            if blk:
                c.fill = group_fill
                if span > 1:
                    ws.merge_cells(start_row=group_row, start_column=start + 1,
                                   end_row=group_row, end_column=start + span)
                    for k in range(1, span):
                        ws.cell(group_row, start + 1 + k).fill = group_fill

    for j, col in enumerate(cols, start=1):
        c = ws.cell(header_row, j, col.label)
        c.fill = head_fill
        c.font = head_font
        c.alignment = Alignment(horizontal=col.align, vertical="center", wrap_text=grouped)
        c.border = border

    for i, row in enumerate(result.rows, start=header_row + 1):
        zebra = grouped and (i - header_row) % 2 == 0
        for j, col in enumerate(cols, start=1):
            raw = row.get(col.key)
            cell = ws.cell(i, j)
            if col.type in ("hours", "int", "days") and isinstance(raw, (int, float)):
                cell.value = raw
                cell.number_format = "#,##0"
            elif col.type == "num" and isinstance(raw, (int, float)):
                cell.value = raw
                cell.number_format = "#,##0.##"
            elif col.type == "id" and isinstance(raw, (int, float)):
                cell.value = int(raw)
                cell.number_format = "0"
            elif col.type == "money" and isinstance(raw, (int, float)):
                cell.value = raw
                cell.number_format = '"$"#,##0'
            elif col.type == "pct" and isinstance(raw, (int, float)):
                cell.value = raw
                cell.number_format = "0.0%"
            else:
                cell.value = _fmt(raw, col.type) if col.type not in ("text", "date") else (raw or "")
            cell.alignment = Alignment(horizontal=col.align)
            if grouped:
                cell.font = Font(name="Helvetica", size=9)
            tl = _tl_hex(col.type, raw)
            if tl:
                cell.fill = PatternFill("solid", fgColor=tl)
            elif zebra:
                cell.fill = zebra_fill

    for j, col in enumerate(cols, start=1):
        if grouped:
            w = {"text": 22, "date": 12, "pct": 11, "money": 12, "int": 9, "days": 10}.get(col.type, 11)
        else:
            w = min(max(len(col.label) + 2, 12), 34)
        ws.column_dimensions[get_column_letter(j)].width = w
    # freeze header (+ the 3 leading id columns for the exec board)
    ws.freeze_panes = ws.cell(header_row + 1, 4 if grouped else 1)
    if grouped:
        ws.page_setup.orientation = "landscape"
        ws.page_setup.fitToWidth = 1
        ws.sheet_properties.pageSetUpPr.fitToPage = True

    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


# ─────────────────────────────────────────────────────────────────────────────
# PDF
# ─────────────────────────────────────────────────────────────────────────────
def to_pdf(result) -> bytes:
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import letter, landscape
    from reportlab.lib.units import inch
    from reportlab.platypus import (SimpleDocTemplate, Table, TableStyle,
                                     Paragraph, Spacer)
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle

    b = branding()
    hexcolor = "#" + (b["color"] or "1F3864").lstrip("#")
    brand = colors.HexColor(hexcolor)

    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=landscape(letter),
                            leftMargin=0.5 * inch, rightMargin=0.5 * inch,
                            topMargin=0.55 * inch, bottomMargin=0.5 * inch,
                            title=f"{b['product']} — {result.title}")
    styles = getSampleStyleSheet()
    h = ParagraphStyle("h", parent=styles["Title"], textColor=brand,
                       fontSize=16, spaceAfter=2, alignment=0)
    sub = ParagraphStyle("sub", parent=styles["Normal"], fontSize=8,
                         textColor=colors.grey, spaceAfter=2)
    cellst = ParagraphStyle("cell", parent=styles["Normal"], fontSize=7.5, leading=9)

    story = [Paragraph(f"{b['product']} — {result.title}", h),
             Paragraph(f"{b['company']} &nbsp;·&nbsp; generated {_ts()}", sub)]
    if result.cards:
        story.append(Paragraph(
            " &nbsp;&nbsp;|&nbsp;&nbsp; ".join(f"<b>{c.label}:</b> {c.value}"
                                               for c in result.cards), sub))
    story.append(Spacer(1, 8))

    cols = result.columns
    grouped = any(c.block for c in cols)
    if grouped:
        cellst = ParagraphStyle("cellg", parent=styles["Normal"], fontSize=6, leading=7.5)
    hcell = ParagraphStyle("hcell", parent=cellst, textColor=colors.white, fontSize=cellst.fontSize)

    data = []
    header_idx = 0
    if grouped:
        band = [""] * len(cols)
        for blk, start, span in _blocks(cols):
            if blk:
                band[start] = Paragraph(f"<b>{blk.upper()}</b>", hcell)
        data.append(band)
        header_idx = 1
    data.append([Paragraph(f"<b>{c.label}</b>", hcell) for c in cols])
    for row in result.rows:
        data.append([Paragraph(_fmt(row.get(col.key), col.type), cellst) for col in cols])
    data_start = header_idx + 1

    # column widths
    avail = landscape(letter)[0] - inch
    if grouped:
        wmap = {"text": 3.2, "date": 1.5, "pct": 1.3, "money": 1.5, "int": 1.0, "days": 1.1}
        weights = [wmap.get(c.type, 1.2) for c in cols]
    else:
        weights = [max(len(c.label), 6) for c in cols]
    tot = sum(weights) or 1
    widths = [avail * w / tot for w in weights]

    table = Table(data, colWidths=widths, repeatRows=data_start)
    style = [
        ("BACKGROUND", (0, header_idx), (-1, header_idx), brand),
        ("TEXTCOLOR", (0, header_idx), (-1, header_idx), colors.white),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("GRID", (0, header_idx), (-1, -1), 0.25, colors.HexColor("#E0E0E0")),
        ("TOPPADDING", (0, 0), (-1, -1), 2 if grouped else 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 2 if grouped else 3),
        ("LEFTPADDING", (0, 0), (-1, -1), 3),
        ("RIGHTPADDING", (0, 0), (-1, -1), 3),
    ]
    if grouped:
        for blk, start, span in _blocks(cols):
            if blk:
                style.append(("SPAN", (start, 0), (start + span - 1, 0)))
                style.append(("BACKGROUND", (start, 0), (start + span - 1, 0),
                              colors.HexColor("#" + C_GROUP)))
        # zebra + per-cell traffic lights on the data region
        style.append(("ROWBACKGROUNDS", (0, data_start), (-1, -1),
                      [colors.white, colors.HexColor("#" + C_ZEBRA)]))
        for ri, row in enumerate(result.rows):
            for j, col in enumerate(cols):
                tl = _tl_hex(col.type, row.get(col.key))
                if tl:
                    style.append(("BACKGROUND", (j, data_start + ri),
                                  (j, data_start + ri), colors.HexColor("#" + tl)))
    else:
        style.append(("ROWBACKGROUNDS", (0, data_start), (-1, -1),
                      [colors.white, colors.HexColor("#F4F6FB")]))
    for j, col in enumerate(cols):
        if col.align == "right":
            style.append(("ALIGN", (j, data_start), (j, -1), "RIGHT"))
    table.setStyle(TableStyle(style))
    story.append(table)
    doc.build(story)
    return buf.getvalue()


def filename(result, ext):
    b = branding()
    stub = b["product"].replace(" ", "")
    stamp = datetime.utcnow().strftime("%Y%m%d")
    return f"{stub}_{result.query_id}_{stamp}.{ext}"
