"""
Tests for apps/whatsapp/tasks.py.

process_inbound_message is queued by the webhook for every stored inbound message (plan D7). Since
Step 1.8a it hands the message to the router; what the router does is tested in test_router.py.

Kind of test: integration (agents.md section 2.5). Why: the task runs directly against messages in
the test database; nothing is faked.
"""

import pytest

from ..constants import MessageStatus
from ..models import WhatsAppMessage
from ..tasks import process_inbound_message
from .factories import MessageFactory

pytestmark = pytest.mark.django_db


def test_processing_a_stored_message_routes_it(mocker):
    route = mocker.patch("apps.whatsapp.services.router.route")
    message = MessageFactory(status=MessageStatus.RECEIVED)

    # Called directly, as the Celery worker would call it.
    process_inbound_message(message.pk)

    route.assert_called_once_with(message.pk)


def test_a_message_that_no_longer_exists_is_skipped_without_an_error():
    # E.g. the contact was deleted between the webhook and the worker picking the task up.
    missing_id = (WhatsAppMessage.objects.order_by("-pk").values_list("pk", flat=True).first() or 0) + 1

    process_inbound_message(missing_id)
