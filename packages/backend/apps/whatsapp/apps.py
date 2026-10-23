from django.apps import AppConfig


class WhatsAppConfig(AppConfig):
    """
    The WhatsApp channel: Meta accounts, webhooks, messages and conversations.

    See docs/superpowers/plans/2026-10-06-whatsapp-first-channel-plan.md for the design.
    """

    name = "apps.whatsapp"
    verbose_name = "WhatsApp"

    def ready(self):
        from django.core.checks import register

        from .checks import check_whatsapp_settings

        # Report a misconfigured WhatsApp setup on every manage.py command and at server start.
        register(check_whatsapp_settings)
