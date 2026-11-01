from django.apps import AppConfig


class EntitlementsConfig(AppConfig):
    """
    What each plan includes, and so what an organization may use (WhatsApp plan phase 3). Its own
    app, beside apps.finances rather than inside it, so upstream's billing code is left as it is
    (agents.md section 3.1).
    """

    name = "apps.entitlements"
    verbose_name = "Entitlements"
