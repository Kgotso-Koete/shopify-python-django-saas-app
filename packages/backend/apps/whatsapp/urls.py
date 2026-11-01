from django.urls import path

from . import views

urlpatterns = [
    # The callback URL for every number on this service's own Meta app (plan decision D6): enter
    # https://<api-host>/api/whatsapp/webhook/ in that app's webhook settings.
    path("webhook/", views.webhook_view, name="whatsapp-webhook"),
    # Each organization's own Meta app's callback URL (plan Step 2.9), shown on its WhatsApp page.
    path("webhook/<str:public_id>/", views.app_webhook_view, name="whatsapp-app-webhook"),
]
