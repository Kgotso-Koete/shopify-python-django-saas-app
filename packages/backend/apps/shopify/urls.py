from django.urls import path
from apps.shopify.views import install_view, callback_view
from apps.shopify.webhooks import webhook_view

urlpatterns = [
    path("install/", install_view, name="shopify-install"),
    path("auth/callback/", callback_view, name="shopify-callback"),
    path("webhooks/", webhook_view, name="shopify-webhooks"),
]
