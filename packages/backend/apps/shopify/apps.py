from django.apps import AppConfig


class ShopifyConfig(AppConfig):
    name = "apps.shopify"

    def ready(self):
        # Register system checks
        from . import checks  # noqa: F401
