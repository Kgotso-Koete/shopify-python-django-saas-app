"""
Tests that every enum in apps/whatsapp/constants.py is stored with exactly its member names (plan
Step 1.16, agents.md section 5.3b): `SENT = "SENT"`, never "sent". A human reading the database, or a
setting, sees the same word the code uses.

Every enum class in the module is checked, so a new one can't slip in with another spelling.

Kind of test: unit (agents.md section 2.5). Why: the enum classes on their own, with no database or
network; nothing is faked.
"""

import pytest
from django.db import models

from .. import constants

# The root conftest.py registers fixtures whose autouse parts need the database.
pytestmark = pytest.mark.django_db


def enums_in(module) -> list[type[models.Choices]]:
    """Every Django choices class defined in `module` itself."""
    return [
        value
        for value in vars(module).values()
        if isinstance(value, type) and issubclass(value, models.Choices) and value.__module__ == module.__name__
    ]


@pytest.mark.parametrize("enum", enums_in(constants), ids=lambda enum: enum.__name__)
def test_every_member_is_stored_as_its_name(enum):
    assert {member.name: member.value for member in enum} == {member.name: member.name for member in enum}


def test_every_enum_is_checked():
    # A guard on the test itself: the module's seven enums, so none is missed.
    assert sorted(enum.__name__ for enum in enums_in(constants)) == [
        "AccountPurpose",
        "ConnectionMethod",
        "ConversationMode",
        "MessageDirection",
        "MessageKind",
        "MessageStatus",
        "SendBackend",
    ]


def test_a_numbers_purpose_says_who_it_is_for():
    # Its organization's own team texts an internal number; its customers text an external one; one
    # number can serve both (plan Step 2.7).
    assert [purpose.name for purpose in constants.AccountPurpose] == [
        "INTERNAL_COMMUNICATIONS",
        "EXTERNAL_COMMUNICATIONS",
        "INTERNAL_AND_EXTERNAL_COMMUNICATIONS",
    ]


def test_a_messages_direction_is_inbound_or_outbound():
    assert [direction.value for direction in constants.MessageDirection] == ["INBOUND", "OUTBOUND"]
