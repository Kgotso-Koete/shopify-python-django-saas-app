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
    # No SMS since 2026-11-09 (maintainer's decision, user story WA.D1.OM.J1.A3): a member proves their number
    # on WhatsApp, which they use to talk to the app anyway.
    assert [channel.value for channel in Channel] == ["WHATSAPP_INBOUND", "WHATSAPP_TEMPLATE"]
