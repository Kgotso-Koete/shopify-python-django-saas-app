"""
Deleting store customers' data when Shopify asks (plan Step 2.6, phase 2 decision 4, user story 14):
receivers of apps.shopify's customer_redacted and shop_redacted, connected in apps.py.

Deleting a contact deletes everything it holds: its messages, conversation, assistant history and
store customer. Only store customers are deleted, on the store's own numbers, or with a cart in that
store; the team's contacts and other organizations' customers stay.

Shopify names a customer by its phone; a contact keeps its WhatsApp number as digits, so the phone is
reduced to its digits to match. A known limit: a contact Meta gave no number (some username users,
plan section 6.1) can't be matched.
"""

from django.db.models import Q

from apps.whatsapp.models import WhatsAppContact

from .models import StorefrontChannel


def _store_customers_of(shop):
    """The contacts of `shop`'s store customers: on a number selling from it, or with a cart in it."""
    return WhatsAppContact.objects.filter(store_customer__isnull=False).filter(
        Q(account__storefront_channel__shop=shop) | Q(store_customer__cart_shop=shop)
    )


def delete_redacted_customer(sender, shop, customer, **kwargs):
    digits = "".join(character for character in str(customer.get("phone") or "") if character.isdigit())
    if not digits:
        return
    _store_customers_of(shop).filter(wa_id=digits).delete()


def delete_redacted_shop(sender, shop, **kwargs):
    _store_customers_of(shop).delete()
    StorefrontChannel.objects.filter(shop=shop).delete()
