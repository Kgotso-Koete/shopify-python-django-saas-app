from django.apps import AppConfig


class WhatsAppSaasConfig(AppConfig):
    """
    What an organization's team can do on its internal communications WhatsApp number (plan decision
    D1, Step 1.17): CRUD items, Shopify products and renaming the organization, through menus, Flows
    and the assistant, which all call the same operations in use_cases.py (D10). The channel itself
    is apps.whatsapp, which never imports this app; this app registers its handler there.

    See docs/superpowers/plans/2026-10-06-whatsapp-first-channel-plan.md.
    """

    name = "apps.whatsapp_saas"
    verbose_name = "WhatsApp for an organization's team"

    def ready(self):
        from apps.whatsapp import registry
        from apps.whatsapp.constants import AccountPurpose
        from apps.whatsapp.services import confirmations

        from .menus import InternalNumberHandler
        from .writes import ACTIONS

        # This app answers internal communications numbers (D1), and owns the writes it asks users to
        # confirm (D11).
        registry.register_handler(AccountPurpose.INTERNAL_COMMUNICATIONS, InternalNumberHandler())
        for name, action in ACTIONS.items():
            confirmations.register_action(name, action)
