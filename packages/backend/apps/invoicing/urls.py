from django.urls import path

from . import views

urlpatterns = [
    # Download an invoice's PDF (WhatsApp plan phase 4, decision 19); the web app fetches it in the page.
    path("<str:invoice_id>/pdf/", views.InvoicePdfView.as_view(), name="invoice-pdf"),
]
