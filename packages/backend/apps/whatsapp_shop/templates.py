"""
The order update template (plan phase 4, Step 4.3d-2, decisions 6 and 24; Step 4.7, decision 30): what a store
customer gets about their order once the 24-hour window has closed, since only an approved template may then be
sent. The last resort (agents.md section 5.3d): within the window an update is a normal message with the order's
details, built in orders.py.

- **One utility template for any stage** (decision 30, replacing decision 24's one per stage): fixed wording
  around two blanks, the store and the order number, never starting or ending with one, since Meta's review
  refuses templates that "start or end with a parameter".
  https://developers.facebook.com/documentation/business-messaging/whatsapp/templates/template-review
- **An Order details quick-reply button,** not a link: the tap is a message from the customer, which opens a new
  24-hour window, so the app answers with the order's details, live from Shopify, as a normal message
  (menus.py). Its payload names the checkout, `order:<code>`, set when the template is sent.
- **Each business's own:** templates belong to a WhatsApp Business account, so each number serving customers
  gets its own copy and its own review, submitted when it connects (tasks.py), or by the
  `whatsapp_publish_order_templates` command. The name starts with `shop_`, so it can't take a name the business
  uses for its own templates.
- **The two it replaced are retired** when it's published: deleted from the business's account and from the
  service's records.
"""

from apps.whatsapp.builders import template_message
from apps.whatsapp.constants import AccountPurpose
from apps.whatsapp.services import templates

ORDER_UPDATE = "shop_order_update"
# Decision 24's templates, with their View order link, replaced by ORDER_UPDATE in Step 4.7 (decision 30).
RETIRED = ("shop_order_received", "shop_order_paid")
LANGUAGE = "en"
CATEGORY = "UTILITY"
ORDER_DETAILS = "Order details"
# The start of the quick reply's payload; the checkout's code follows it.
ORDER_DETAILS_PAYLOAD_PREFIX = "order:"

# The numbers whose customers get order updates: those serving customers (plan Step 2.7).
CUSTOMER_PURPOSES = (
    AccountPurpose.EXTERNAL_COMMUNICATIONS,
    AccountPurpose.INTERNAL_AND_EXTERNAL_COMMUNICATIONS,
)

# {{1}} is the store, {{2}} the order number.
BODY = "Hello, this is {{1}}. There's an update on your order {{2}}. Tap Order details to see it."
EXAMPLE_BODY = ["Acme Outdoor", "#1001"]


def order_templates() -> dict[str, dict]:
    """The order templates by name, as Meta's Message Templates API takes them."""
    return {
        ORDER_UPDATE: {
            "category": CATEGORY,
            "language": LANGUAGE,
            "components": [
                {"type": "BODY", "text": BODY, "example": {"body_text": [EXAMPLE_BODY]}},
                {"type": "BUTTONS", "buttons": [{"type": "QUICK_REPLY", "text": ORDER_DETAILS}]},
            ],
        }
    }


def publish_order_templates(account) -> list[tuple[str, object, bool]]:
    """
    Submit the order templates to the account's WhatsApp Business account, each only if it changed, and retire
    the ones they replaced. Returns (name, stored template, whether Meta was asked now) for each; raises a
    SendError when Meta refuses one.
    """
    published = []
    for name, template in sorted(order_templates().items()):
        stored, changed = templates.submit(account, name, **template)
        published.append((name, stored, changed))
    for name in RETIRED:
        templates.retire(account, name)
    return published


def order_template(*, store: str, number: str, code: str) -> dict:
    """The update template, with its blanks filled in and the checkout's code in its Order details payload."""
    return template_message(
        ORDER_UPDATE,
        language=LANGUAGE,
        body=[store, number],
        quick_reply_payload=f"{ORDER_DETAILS_PAYLOAD_PREFIX}{code}",
    )
