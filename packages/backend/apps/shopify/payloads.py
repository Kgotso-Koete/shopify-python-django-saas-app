"""
What a webhook delivery keeps of its payload (WhatsApp plan phase 4, Step 4.3b, decision 4).

The webhook view stores each delivery's payload, and hands that stored payload to the handler,
whether the handler runs in the request or in the Celery task. For most topics that is the whole
payload. For a topic listed in KEPT_FIELDS, only the listed fields are kept, under Shopify's own
names, so nothing about a customer that no feature uses is ever stored (POPIA's minimality).

- **Orders keep only what the app uses:** the order's id, its name (#1001), total, currency,
  financial status and note attributes. Never the customer, the addresses or the lines, nor the
  status page link, which opens the order to whoever holds it: orders.py asks Shopify for a fresh one
  when it's needed (Step 4.3d, decision 23). A feature that needs another field adds it here, from
  then on.
- **Note attributes are filtered too:** any app on the store can write them. An app that needs one
  asks for it by key, from its AppConfig.ready, with keep_note_attribute(); the others are dropped.
  apps.whatsapp_shop asks for its checkout code this way, so this app never knows about it.
- **A field the delivery lacks stays out,** rather than being stored as empty.
"""

from apps.shopify.constants import TOPIC_ORDERS_CREATE, TOPIC_ORDERS_PAID

NOTE_ATTRIBUTES = "note_attributes"

ORDER_FIELDS = (
    "id",
    "name",
    "total_price",
    "currency",
    "financial_status",
    NOTE_ATTRIBUTES,
)

# Topic → the payload fields kept. A topic not listed keeps its whole payload.
KEPT_FIELDS = {
    TOPIC_ORDERS_CREATE: ORDER_FIELDS,
    TOPIC_ORDERS_PAID: ORDER_FIELDS,
}

_kept_note_attributes: set[str] = set()


def keep_note_attribute(key: str) -> None:
    """Keep the note attribute named `key` in the deliveries that carry note attributes."""
    _kept_note_attributes.add(key)


def trim(topic: str, payload: dict) -> dict:
    """The part of `payload` kept for `topic`: all of it, unless KEPT_FIELDS lists the topic."""
    fields = KEPT_FIELDS.get(topic)
    if fields is None:
        return payload
    kept = {field: payload[field] for field in fields if field in payload}
    if NOTE_ATTRIBUTES in kept:
        kept[NOTE_ATTRIBUTES] = [
            attribute
            for attribute in kept[NOTE_ATTRIBUTES] or []
            if isinstance(attribute, dict) and attribute.get("name") in _kept_note_attributes
        ]
    return kept
