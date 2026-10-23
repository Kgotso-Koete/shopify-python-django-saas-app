"""
Tests proving the WhatsApp settings in config/settings.py are read from environment variables,
and that each one has a safe default when the variable is unset (agents.md section 2.3).

The settings themselves are described in section 8.7 of
docs/superpowers/plans/2026-10-06-whatsapp-first-channel-plan.md.

Kind of test: sanity (agents.md section 2.5). Why: they prove each setting reads its environment
variable, in a fresh subprocess; nothing is faked.
"""

import subprocess

import pytest
from django.conf import settings

from .utils import read_settings

# The root conftest.py registers fixtures (apps.finances.tests.fixtures) for every test, and their
# autouse fixtures need the database, so these tests are marked to allow it.
pytestmark = pytest.mark.django_db

WHATSAPP_SETTINGS = [
    # Switches the whole WhatsApp channel on; off by default so a fresh clone needs nothing.
    "WHATSAPP_ENABLED",
    # The Meta Graph API version every request to Meta goes through.
    "WHATSAPP_GRAPH_API_VERSION",
    # Our Meta app (plan Step 1.18): its App secret signs every number's webhooks, and Meta sends
    # its verify token back when it checks the webhook URL.
    "WHATSAPP_APP_SECRET",
    "WHATSAPP_VERIFY_TOKEN",
    # Fernet key that encrypts stored WhatsApp credentials (access tokens, app secrets).
    "WHATSAPP_TOKEN_ENCRYPTION_KEY",
    # "LOG" stores replies without calling Meta; "META" really sends them. Values are SendBackend's
    # member names (agents.md section 5.3b).
    "WHATSAPP_SEND_BACKEND",
    # Strict ordering (plan D21): each reply also waits for Meta's `sent` status on the one before.
    "WHATSAPP_SEND_WAIT_FOR_SENT_STATUS",
    # The conversation mode for a user who hasn't chosen one: "WHATSAPP_FORM" or "AGENTIC".
    "WHATSAPP_DEFAULT_CONVERSATION_MODE",
    # The country code a local number (one leading 0) gets when it's stored (plan D19).
    "WHATSAPP_DEFAULT_COUNTRY_CODE",
    # How long a linking code works, and how long an idle conversation keeps its menu state.
    "WHATSAPP_LINK_CODE_TTL_SECONDS",
    "WHATSAPP_CONVERSATION_TTL_SECONDS",
    # The AI assistant's model (empty means the agent falls back to OPENAI_MODEL) and its
    # cap on tool calls per inbound message.
    "WHATSAPP_AI_MODEL",
    "WHATSAPP_AI_MAX_TOOL_CALLS",
]

# Gone with the platform number (plan Step 1.17): every number is connected on its organization's
# WhatsApp tab, never named in the environment.
REMOVED_SETTINGS = [
    "WHATSAPP_PLATFORM_PHONE_NUMBER_ID",
    "WHATSAPP_PLATFORM_WABA_ID",
    "WHATSAPP_PLATFORM_ACCESS_TOKEN",
    "WHATSAPP_PLATFORM_DISPLAY_NUMBER",
]


class TestWhatsAppSettings:
    def test_whatsapp_settings_read_env_vars(self):
        # Every value differs from its default, so a setting that ignores its variable fails.
        values = read_settings(
            WHATSAPP_SETTINGS,
            WHATSAPP_ENABLED="true",
            WHATSAPP_GRAPH_API_VERSION="v27.0",
            WHATSAPP_APP_SECRET="test_app_secret",
            WHATSAPP_VERIFY_TOKEN="test_verify_token",
            WHATSAPP_TOKEN_ENCRYPTION_KEY="test_encryption_key",
            WHATSAPP_SEND_BACKEND="META",
            WHATSAPP_SEND_WAIT_FOR_SENT_STATUS="true",
            WHATSAPP_DEFAULT_CONVERSATION_MODE="AGENTIC",
            WHATSAPP_DEFAULT_COUNTRY_CODE="254",
            WHATSAPP_LINK_CODE_TTL_SECONDS="300",
            WHATSAPP_CONVERSATION_TTL_SECONDS="900",
            WHATSAPP_AI_MODEL="test-model",
            WHATSAPP_AI_MAX_TOOL_CALLS="3",
        )

        # Values are compared as repr() strings, so "True" and "300" also prove the type
        # (a bool and an int), not just the text.
        assert values == {
            "WHATSAPP_ENABLED": "True",
            "WHATSAPP_GRAPH_API_VERSION": "'v27.0'",
            "WHATSAPP_APP_SECRET": "'test_app_secret'",
            "WHATSAPP_VERIFY_TOKEN": "'test_verify_token'",
            "WHATSAPP_TOKEN_ENCRYPTION_KEY": "'test_encryption_key'",
            "WHATSAPP_SEND_BACKEND": "'META'",
            "WHATSAPP_SEND_WAIT_FOR_SENT_STATUS": "True",
            "WHATSAPP_DEFAULT_CONVERSATION_MODE": "'AGENTIC'",
            "WHATSAPP_DEFAULT_COUNTRY_CODE": "'254'",
            "WHATSAPP_LINK_CODE_TTL_SECONDS": "300",
            "WHATSAPP_CONVERSATION_TTL_SECONDS": "900",
            "WHATSAPP_AI_MODEL": "'test-model'",
            "WHATSAPP_AI_MAX_TOOL_CALLS": "3",
        }

    def test_whatsapp_settings_have_safe_defaults_when_unset(self):
        # None removes the variable from the subprocess's environment (see read_settings).
        unset = {name: None for name in WHATSAPP_SETTINGS}

        values = read_settings(WHATSAPP_SETTINGS, **unset)

        # The defaults keep the channel off, send nothing to Meta ("LOG"), and leave every
        # secret empty, so the app runs without any WhatsApp configuration (agents.md 5.4).
        assert values == {
            "WHATSAPP_ENABLED": "False",
            "WHATSAPP_GRAPH_API_VERSION": "'v26.0'",
            "WHATSAPP_APP_SECRET": "''",
            "WHATSAPP_VERIFY_TOKEN": "''",
            "WHATSAPP_TOKEN_ENCRYPTION_KEY": "''",
            "WHATSAPP_SEND_BACKEND": "'LOG'",
            "WHATSAPP_SEND_WAIT_FOR_SENT_STATUS": "False",
            "WHATSAPP_DEFAULT_CONVERSATION_MODE": "'WHATSAPP_FORM'",
            "WHATSAPP_DEFAULT_COUNTRY_CODE": "'27'",
            "WHATSAPP_LINK_CODE_TTL_SECONDS": "600",
            "WHATSAPP_CONVERSATION_TTL_SECONDS": "1800",
            "WHATSAPP_AI_MODEL": "''",
            "WHATSAPP_AI_MAX_TOOL_CALLS": "5",
        }

    @pytest.mark.parametrize("name", REMOVED_SETTINGS)
    def test_the_platform_numbers_settings_are_never_read_from_the_environment(self, name):
        # Set in the environment, it still isn't a setting: reading it fails in the subprocess, as
        # it does here.
        with pytest.raises(subprocess.CalledProcessError):
            read_settings([name], **{name: "set-in-the-environment"})
        assert not hasattr(settings, name)
