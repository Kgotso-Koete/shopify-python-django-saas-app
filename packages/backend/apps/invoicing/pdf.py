"""
An invoice's PDF, written with ReportLab (WhatsApp plan phase 4, Step 4.4b; D15, decisions 13 and 18).
https://docs.reportlab.com/reportlab/userguide/ch2_graphics/

It says exactly what the invoice row says, and only that: the PDF is written once, so a later change
anywhere else never alters an issued invoice. It's an "Invoice", not a "Tax Invoice", with no VAT: the
operator isn't VAT-registered (decision 13). PayFast's id isn't printed: the invoice's own number is its
reference, and a catch-up renewal's PayFast id is filled in after the PDF exists (decision 18).

Written without page compression, so its text can be read back from the bytes in tests; an invoice is
small either way.
"""

from io import BytesIO

from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.pdfgen.canvas import Canvas

from .models import Invoice

MARGIN = 20 * mm
LINE = 6 * mm


def render(invoice: Invoice) -> bytes:
    """The invoice as a one-page A4 PDF."""
    buffer = BytesIO()
    canvas = Canvas(buffer, pagesize=A4, pageCompression=0)
    canvas.setTitle(invoice.number)
    width, height = A4
    y = height - MARGIN

    canvas.setFont("Helvetica-Bold", 20)
    canvas.drawString(MARGIN, y, "Invoice")
    canvas.setFont("Helvetica", 10)
    canvas.drawRightString(width - MARGIN, y, invoice.number)
    canvas.drawRightString(width - MARGIN, y - LINE, f"Date: {invoice.issued_at.date().isoformat()}")

    # Who issues it: the operator, as the settings said when it was issued.
    y -= 3 * LINE
    canvas.setFont("Helvetica-Bold", 11)
    canvas.drawString(MARGIN, y, invoice.supplier_name)
    canvas.setFont("Helvetica", 10)
    for line in invoice.supplier_address.splitlines():
        y -= LINE
        canvas.drawString(MARGIN, y, line)

    # Whom it's for.
    y -= 2 * LINE
    canvas.setFont("Helvetica-Bold", 10)
    canvas.drawString(MARGIN, y, "Bill to")
    canvas.setFont("Helvetica", 10)
    y -= LINE
    canvas.drawString(MARGIN, y, invoice.tenant_name)

    # What was paid for, and the total.
    amount = f"{invoice.currency} {invoice.amount:.2f}"
    y -= 3 * LINE
    canvas.setFont("Helvetica-Bold", 10)
    canvas.drawString(MARGIN, y, "Description")
    canvas.drawRightString(width - MARGIN, y, "Amount")
    canvas.line(MARGIN, y - 2 * mm, width - MARGIN, y - 2 * mm)
    canvas.setFont("Helvetica", 10)
    y -= LINE + 2 * mm
    canvas.drawString(MARGIN, y, invoice.description)
    canvas.drawRightString(width - MARGIN, y, amount)
    y -= 2 * LINE
    canvas.setFont("Helvetica-Bold", 11)
    canvas.drawString(MARGIN, y, "Total")
    canvas.drawRightString(width - MARGIN, y, amount)

    canvas.showPage()
    canvas.save()
    return buffer.getvalue()
