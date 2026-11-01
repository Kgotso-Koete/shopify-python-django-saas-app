"""
Helpers for the store customers' chat tests (test-support code, agents.md section 2.1): an
organization's external number selling from a store, a store customer texting it, a message sent as
them through the real router, and the screens that came back.

Written here rather than imported from apps.whatsapp_saas's tests, so this app's tests don't depend
on that app (plan decision D1).
"""

from apps.shopify.models import ShopifyShop
from apps.whatsapp.constants import MessageDirection, MessageKind
from apps.whatsapp.models import WhatsAppMessage
from apps.whatsapp.services import router
from apps.whatsapp.tests.factories import ContactFactory, ExternalAccountFactory, MessageFactory

from ..models import StorefrontChannel

# What a store needs to sell on WhatsApp (Step 2.1b): the Storefront API's product listings and cart.
STOREFRONT_SCOPES = "read_products,unauthenticated_read_product_listings,unauthenticated_write_checkouts"


class Screen:
    """
    One reply as the customer sees it: its body text, its buttons or list rows as (id, title), the
    list rows' descriptions, its header image if any, and a link button's text and address.
    """

    def __init__(self, message):
        self.link = None
        if message["type"] == "image":
            # A picture on its own, such as the store's logo: its caption reads as the body.
            image = message["image"]
            self.body, self.image_url, self.options, self.descriptions = image.get("caption", ""), image["link"], [], []
            return
        if message["type"] == "text":
            self.body, self.image_url, self.options, self.descriptions = message["text"]["body"], None, [], []
            return
        interactive = message["interactive"]
        self.body = interactive["body"]["text"]
        self.image_url = interactive.get("header", {}).get("image", {}).get("link")
        action = interactive["action"]
        self.descriptions = []
        if "buttons" in action:
            self.options = [(button["reply"]["id"], button["reply"]["title"]) for button in action["buttons"]]
        elif "sections" in action:
            rows = [row for section in action["sections"] for row in section["rows"]]
            self.options = [(row["id"], row["title"]) for row in rows]
            self.descriptions = [row.get("description", "") for row in rows]
        else:
            self.options = []
        if interactive["type"] == "cta_url":
            self.link = action["parameters"]

    @property
    def titles(self):
        return [title for _, title in self.options]

    def press(self, title):
        [choice_id] = [choice_id for choice_id, shown in self.options if shown == title]
        return choice_id


def store(tenant, domain="acme.myshopify.com", *, scopes=STOREFRONT_SCOPES, **fields):
    shop = ShopifyShop(shop_domain=domain, tenant=tenant, scopes=scopes, **fields)
    shop.access_token = "admin-token"
    shop.save()
    return shop


def selling_number(tenant, shop, **channel):
    """The organization's external number, selling from `shop`."""
    account = ExternalAccountFactory(tenant=tenant, verified_name="Acme Outdoor")
    StorefrontChannel.objects.create(account=account, shop=shop, **channel)
    return account


def customer_of(account):
    """Someone texting the number: no account, no membership, just a WhatsApp number."""
    return ContactFactory(account=account, wa_id="27000001001")


def send(contact, text=None, *, press=None) -> list[Screen]:
    """Route one message from `contact` (typed text, or a press on a choice id) and return the screens it got."""
    if press is not None:
        payload = {"text": "", "action_id": press, "flow_response": {}}
        message = MessageFactory(contact=contact, kind=MessageKind.LIST_REPLY, payload=payload)
    else:
        payload = {"text": text, "action_id": "", "flow_response": {}}
        message = MessageFactory(contact=contact, payload=payload)
    router.route(message.pk)
    rows = WhatsAppMessage.objects.filter(contact=contact, direction=MessageDirection.OUTBOUND).order_by("pk")
    screens = [Screen(row.payload) for row in rows]
    rows.delete()
    return screens
