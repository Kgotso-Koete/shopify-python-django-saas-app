from django.urls import path

from . import views

urlpatterns = [
    # The one callback URL for every WhatsApp number (plan decision D6): enter
    # https://<api-host>/api/whatsapp/webhook/ in the Meta app's webhook settings.
    path("webhook/", views.webhook_view, name="whatsapp-webhook"),
]
