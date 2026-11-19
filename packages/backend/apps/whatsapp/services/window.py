"""
The 24-hour customer service window (plan phase 4, Step 4.3c, decision 6).

A business can send a contact a normal message only within 24 hours of the contact's last message to
it: "When the window closes, you can only send pre-approved template messages."
https://developers.facebook.com/docs/whatsapp/cloud-api/guides/send-messages

Only for messages nobody asked for just now, such as an order update; a reply to a message is always
inside the window. Measured by Meta's timestamp on the contact's last message (`sent_at`), or by when
it was stored if Meta gave none. A message sent at the very edge can still be refused by Meta, which
records it as failed with code 131047 (WindowClosedError in client.py).
"""

from datetime import timedelta

from django.db.models.functions import Coalesce
from django.utils import timezone

from ..constants import MessageDirection
from ..models import WhatsAppContact, WhatsAppMessage

CUSTOMER_SERVICE_WINDOW = timedelta(hours=24)


def is_open(contact: WhatsAppContact) -> bool:
    """Whether `contact` wrote to its number within the last CUSTOMER_SERVICE_WINDOW."""
    since = timezone.now() - CUSTOMER_SERVICE_WINDOW
    return (
        WhatsAppMessage.objects.filter(contact=contact, direction=MessageDirection.INBOUND)
        .annotate(written_at=Coalesce("sent_at", "created_at"))
        .filter(written_at__gt=since)
        .exists()
    )
