from django.urls import path

from . import views

urlpatterns = [
    # Point PAYFAST_NOTIFY_URL_DEVELOPMENT / _PRODUCTION at https://<api-host>/api/payfast/notify/
    path("notify/", views.itn_view, name="payfast-itn"),
]
