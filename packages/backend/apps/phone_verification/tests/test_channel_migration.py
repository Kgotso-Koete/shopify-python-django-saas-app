"""
Tests for the data migration that rewrites the stored verification channel to its member names
(WhatsApp plan Step 1.16, agents.md section 5.3b): "whatsapp_inbound" becomes "WHATSAPP_INBOUND", with
a reverse that restores the old value.

A code binds its channel into its HMAC, so a code issued before the migration no longer matches after
it. Codes last minutes, so that's accepted (plan Step 1.16), not repaired.

Kind of test: integration (agents.md section 2.5). Why: rows in the test database are rewritten by
the migration's own functions, called directly; nothing is faked.
"""

import importlib
from datetime import timedelta

import pytest
from django.apps import apps as django_apps
from django.utils import timezone

from apps.users.tests.factories import UserFactory

from ..models import PhoneVerificationCode

pytestmark = pytest.mark.django_db

migration = importlib.import_module("apps.phone_verification.migrations.0002_channel_values_are_member_names")


@pytest.fixture
def old_code():
    code = PhoneVerificationCode.objects.create(
        user=UserFactory(),
        phone_number="27000001001",
        channel="whatsapp_inbound",
        code_hash="0" * 64,
        expires_at=timezone.now() + timedelta(minutes=10),
    )
    return code


def test_old_values_become_member_names(old_code):
    migration.store_member_names(django_apps, None)

    old_code.refresh_from_db()
    assert old_code.channel == "WHATSAPP_INBOUND"


def test_the_reverse_restores_the_old_values(old_code):
    migration.store_member_names(django_apps, None)

    migration.store_old_values(django_apps, None)

    old_code.refresh_from_db()
    assert old_code.channel == "whatsapp_inbound"
