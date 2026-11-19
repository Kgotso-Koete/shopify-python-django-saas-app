"""
The organization's plan and invoices, from its team's WhatsApp number (plan phase 4, Steps 4.1 and 4.5b,
decisions 9, 12 and 14).

The menu and the assistant send these same screens:
- plans_link: a **Choose a plan** link to the organization's Subscriptions page on the website, where
  choosing and paying happen as they always do. Nothing about plans or prices is said here, so the chat
  can never disagree with the page.
- invoices_screen and send_invoice: the organization's newest invoices to tap, and a tapped one's PDF,
  uploaded to Meta and sent as a document, never as a link (D15).
"""

from apps.whatsapp.builders import Row, document_message, link_button, list_message, text_reply
from apps.whatsapp.client import SendError, send_backend

from . import use_cases
from .use_cases import UseCaseError

# A tapped invoice; the menus map it to send_invoice.
INVOICE = "invoice"

PDF = "application/pdf"


def plans_link(user, tenant) -> list[dict]:
    """The link, for billing.manage; anyone else gets the use case's refusal (UseCaseError)."""
    url = use_cases.subscriptions_link(user, tenant)
    body = f"Choose or change {tenant.name}'s plan, and pay, on the website's Subscriptions page."
    return [link_button(body, display_text="Choose a plan", url=url)]


def invoices_screen(turn) -> list[dict]:
    """The organization's newest invoices, each by its number with what it was for, for billing.view."""
    tenant = turn.conversation.tenant
    invoices = use_cases.recent_invoices(turn.user, tenant)
    if not invoices:
        first = use_cases.first_invoice_date(turn.user, tenant)
        if first is not None:
            # User story WA.D6.OM.J2.A1: during a trial, say when the first invoice comes.
            return text_reply(f"No invoices yet. Your first comes with your first payment on {first:%Y-%m-%d}.")
        return text_reply(f"No invoices yet: {tenant.name} gets one for each payment made on the website.")
    rows = [
        Row(
            turn.choice(INVOICE, invoice_id=str(invoice.id)),
            invoice.number,
            f"{invoice.description} · {invoice.currency} {invoice.amount:.2f}",
        )
        for invoice in invoices
    ]
    body = f"{tenant.name}'s invoices, newest first. Tap one to get its PDF."
    return [list_message(body, button_label="Invoices", section_title="Invoices", rows=rows)]


def send_invoice(turn, invoice_id) -> list[dict]:
    """A tapped invoice's PDF, as a document; it has no buttons, so the caller adds the way back (D17)."""
    invoice, content = use_cases.invoice_pdf(turn.user, turn.conversation.tenant, invoice_id)
    filename = f"{invoice.number}.pdf"
    try:
        media_id = send_backend().upload_media(turn.contact.account, content, filename=filename, mime_type=PDF)
    except SendError as error:
        raise UseCaseError(
            "The invoice couldn't be sent right now. Please try again in a few minutes.", "try_again_later"
        ) from error
    caption = (
        f"Invoice {invoice.number} for {invoice.tenant_name}: {invoice.description}, "
        f"{invoice.currency} {invoice.amount:.2f}."
    )
    return [document_message(media_id, filename=filename, caption=caption)]
