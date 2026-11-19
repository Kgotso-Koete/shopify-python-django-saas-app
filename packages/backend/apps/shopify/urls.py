from django.urls import path
from apps.shopify.views import install_view, callback_view
from apps.shopify.webhooks import webhook_view

urlpatterns = [
    path("install/", install_view, name="shopify-install"),
    path("auth/callback/", callback_view, name="shopify-callback"),
    path("webhooks/", webhook_view, name="shopify-webhooks"),
    # Shopify drops the trailing slash from a subscription's address, and Django can't redirect a POST to add it
    # (500 with DEBUG, 301 without, and the webhook is lost either way): the same view, without the slash
    # (WhatsApp plan Step 4.7 human checks, 2026-11-10).
    path("webhooks", webhook_view),
]
