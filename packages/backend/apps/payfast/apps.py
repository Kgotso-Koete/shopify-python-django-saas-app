from django.apps import AppConfig


class PayfastConfig(AppConfig):
    """PayFast payments, used instead of Stripe when PAYMENT_BACKEND == "payfast"."""

    name = "apps.payfast"
    verbose_name = "PayFast"

    def ready(self):
        from django.core.checks import register
        from django.db.models.signals import pre_delete

        from apps.multitenancy.models import Tenant

        from .checks import check_payfast_settings
        from .receivers import keep_payments_without_the_buyers_details

        # Report a misconfigured PayFast setup on every manage.py command and at server start.
        register(check_payfast_settings)
        # Payments outlive their organization, without the buyer's details (WhatsApp plan phase 4, decision 17).
        pre_delete.connect(
            keep_payments_without_the_buyers_details, sender=Tenant, dispatch_uid="payfast_keep_payments"
        )
