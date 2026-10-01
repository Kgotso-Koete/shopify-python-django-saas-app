from django.apps import AppConfig


class PayfastConfig(AppConfig):
    """PayFast payments, used instead of Stripe when PAYMENT_BACKEND == "payfast"."""

    name = "apps.payfast"
    verbose_name = "PayFast"

    def ready(self):
        from django.core.checks import register

        from .checks import check_payfast_settings

        # Report a misconfigured PayFast setup on every manage.py command and at server start.
        register(check_payfast_settings)
