"""
Tests for the names the Django admin shows for this app's models (found in the WhatsApp plan's Step 4.7 human
checks): Django makes them from the class name, so WhatsAppTemplate read "Whats app templates" and
WhatsAppIdentity "Whats app identitys". Each model names itself, as apps/payfast's models do.
https://docs.djangoproject.com/en/5.2/ref/models/options/#verbose-name

Kind of test: unit (agents.md section 2.5). Why: it reads each model's options; nothing is faked, and the
database isn't touched.
"""

import pytest

from ..models import (
    MetaApp,
    WhatsAppAccount,
    WhatsAppAgentItem,
    WhatsAppContact,
    WhatsAppConversation,
    WhatsAppFlow,
    WhatsAppIdentity,
    WhatsAppMessage,
    WhatsAppPendingAction,
    WhatsAppTemplate,
    WhatsAppWaitingLink,
)

# Only because the root conftest.py's autouse fixtures need the database (agents.md section 2.5).
pytestmark = pytest.mark.django_db


@pytest.mark.parametrize(
    "model, name, plural",
    [
        (MetaApp, "Meta app", "Meta apps"),
        (WhatsAppAccount, "WhatsApp account", "WhatsApp accounts"),
        (WhatsAppContact, "WhatsApp contact", "WhatsApp contacts"),
        (WhatsAppWaitingLink, "WhatsApp waiting link", "WhatsApp waiting links"),
        (WhatsAppIdentity, "WhatsApp identity", "WhatsApp identities"),
        (WhatsAppConversation, "WhatsApp conversation", "WhatsApp conversations"),
        (WhatsAppPendingAction, "WhatsApp pending action", "WhatsApp pending actions"),
        # Meta's own product name: a Flow.
        (WhatsAppFlow, "WhatsApp Flow", "WhatsApp Flows"),
        (WhatsAppTemplate, "WhatsApp template", "WhatsApp templates"),
        (WhatsAppAgentItem, "WhatsApp agent item", "WhatsApp agent items"),
        (WhatsAppMessage, "WhatsApp message", "WhatsApp messages"),
    ],
)
def test_each_model_is_named_as_people_write_it(model, name, plural):
    assert model._meta.verbose_name == name
    assert model._meta.verbose_name_plural == plural
