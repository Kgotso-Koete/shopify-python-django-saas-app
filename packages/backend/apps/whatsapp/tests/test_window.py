"""
Tests for the 24-hour customer service window (WhatsApp plan phase 4, Step 4.3c, decision 6): whether
a contact wrote to the number within the last 24 hours, so a normal message can still reach them.
"When the window closes, you can only send pre-approved template messages."
https://developers.facebook.com/docs/whatsapp/cloud-api/guides/send-messages

- the window is open for 24 hours after the contact's last message to us, by Meta's timestamp
  (`sent_at`), or by when we stored it if Meta gave none
- our own messages don't open it, nor do another contact's

Kind of test: integration (agents.md section 2.5). Why: the contacts and messages are rows in the
test database; nothing is faked.
"""

from datetime import timedelta

import pytest
from django.utils import timezone

from apps.whatsapp.constants import MessageDirection, MessageStatus

from .factories import ContactFactory, MessageFactory

pytestmark = pytest.mark.django_db


def is_open(contact):
    # Imported here, not at the top, so a missing module fails each test instead of the whole file.
    from apps.whatsapp.services import window

    return window.is_open(contact)


def ago(**delta):
    return timezone.now() - timedelta(**delta)


class TestTheWindow:
    def test_a_contact_who_never_wrote_has_it_closed(self):
        assert not is_open(ContactFactory())

    def test_it_is_open_just_inside_24_hours_of_their_last_message(self):
        contact = ContactFactory()
        MessageFactory(contact=contact, sent_at=ago(hours=23, minutes=59))

        assert is_open(contact)

    def test_it_closes_24_hours_after_their_last_message_by_metas_timestamp(self):
        # Stored just now, but Meta says it was sent 24 hours and a minute ago: Meta's clock counts.
        contact = ContactFactory()
        MessageFactory(contact=contact, sent_at=ago(hours=24, minutes=1))

        assert not is_open(contact)

    def test_the_latest_message_counts(self):
        contact = ContactFactory()
        MessageFactory(contact=contact, sent_at=ago(days=3))
        MessageFactory(contact=contact, sent_at=ago(hours=2))

        assert is_open(contact)

    def test_a_message_without_metas_timestamp_counts_from_when_it_was_stored(self):
        contact = ContactFactory()
        MessageFactory(contact=contact, sent_at=None)

        assert is_open(contact)

    def test_our_own_messages_dont_open_it(self):
        contact = ContactFactory()
        MessageFactory(
            contact=contact, direction=MessageDirection.OUTBOUND, status=MessageStatus.SENT, sent_at=ago(minutes=5)
        )

        assert not is_open(contact)

    def test_another_contacts_message_doesnt_open_it(self):
        contact = ContactFactory()
        MessageFactory(contact=ContactFactory(account=contact.account), sent_at=ago(minutes=5))

        assert not is_open(contact)
