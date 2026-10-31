"""
Signals for apps that keep a store's customer data (WhatsApp plan Step 2.6, phase 2 decision 4).

Shopify's privacy webhooks must be acted on within 30 days
(https://shopify.dev/docs/apps/build/compliance/privacy-law-compliance). This app keeps no customer
data itself; an app that does, such as apps.whatsapp_shop with its store customers, connects a
receiver here and deletes its own, so apps.shopify never imports it. The handlers in services.py send
them, wherever they run: in the webhook request, or in the Celery task, which retries on failure.

- customer_redacted(shop, customer): customers/redact; `customer` is Shopify's, with its id, email and
  phone (each may be missing).
- shop_redacted(shop): shop/redact, sent before the store's row is anonymized, so a receiver still
  finds what belonged to it.
"""

from django.dispatch import Signal

customer_redacted = Signal()
shop_redacted = Signal()
