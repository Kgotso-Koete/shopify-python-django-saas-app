from django.apps import AppConfig


class InvoicingConfig(AppConfig):
    """
    Invoices for this service's PayFast payments (WhatsApp plan phase 4, Steps 4.4 and 4.5). The
    operator issues every invoice, from one numbered sequence, and invoices outlive their organization.
    """

    name = "apps.invoicing"
    verbose_name = "Invoicing"

    def ready(self):
        from django.core.checks import register

        from apps.payfast.signals import payment_completed

        from .checks import check_invoicing_settings
        from .receivers import invoice_completed_payment

        # Warn at startup when an invoice would be printed without its supplier's details.
        register(check_invoicing_settings)
        # Each completed PayFast payment is invoiced (decision 15); apps.payfast never imports this app.
        payment_completed.connect(invoice_completed_payment, dispatch_uid="invoicing_invoice_completed_payment")
