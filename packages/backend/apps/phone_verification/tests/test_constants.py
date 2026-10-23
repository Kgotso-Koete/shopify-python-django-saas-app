"""
Tests that the phone verification channel is stored with exactly its member names (WhatsApp plan
Step 1.16, agents.md section 5.3b).

Kind of test: unit (agents.md section 2.5). Why: the enum class on its own, with no database or
network; nothing is faked.
"""

import pytest

from ..constants import Channel

# The root conftest.py registers fixtures whose autouse parts need the database.
pytestmark = pytest.mark.django_db


def test_every_channel_is_stored_as_its_name():
    assert [channel.value for channel in Channel] == ["WHATSAPP_INBOUND", "WHATSAPP_TEMPLATE", "SMS"]
