from celery import shared_task
from django.core.files.base import ContentFile


@shared_task(ignore_result=True)
def issue_invoice(payment_id: int) -> None:
    """
    Issue a completed PayFast payment's invoice and write its PDF to the default storage, which is
    private (WhatsApp plan phase 4, Step 4.4b; D15). Queued by receivers.py when apps.payfast says the
    payment completed. Safe to run again: the payment keeps its one invoice, a PDF is written once, and a
    catch-up renewal's later run only updates the invoice's PayFast id (decision 18).
    """
    from apps.payfast.models import PayFastPayment

    from . import pdf, services

    payment = PayFastPayment.objects.filter(pk=payment_id).first()
    if payment is None:
        return
    invoice = services.issue_invoice(payment)
    if invoice is None or invoice.pdf:
        return
    invoice.pdf.save(f"{invoice.number}.pdf", ContentFile(pdf.render(invoice)), save=True)
