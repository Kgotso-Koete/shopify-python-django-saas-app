"""
Tests for the WhatsApp system check, apps/whatsapp/checks.py.

Django runs system checks on every manage.py command and at server start. This one reports a
WhatsApp setup that is switched on but can't work, so the mistake shows at deploy time instead of
as webhooks that silently fail in production. With WhatsApp switched off it requires nothing, so a
fresh clone runs without any WhatsApp configuration.

Kind of test: sanity (agents.md section 2.5). Why: they prove a misconfigured deployment fails at
startup; nothing is faked.
"""

import base64

import pytest
from django.test import override_settings

from ..checks import check_whatsapp_settings

# The root conftest.py registers fixtures whose autouse parts need the database.
pytestmark = pytest.mark.django_db

# A Fernet key is 32 random bytes, url-safe base64 encoded. This one is 32 zero characters:
# the right shape for the check, useless as a secret, and obviously fake.
FAKE_FERNET_KEY = base64.urlsafe_b64encode(b"0" * 32).decode()

# A complete, valid WhatsApp configuration. Each test changes one value to break it, so a failing
# test points at exactly one rule.
VALID_WHATSAPP_SETTINGS = {
    "WHATSAPP_ENABLED": True,
    "WHATSAPP_GRAPH_API_VERSION": "v26.0",
    "WHATSAPP_APP_SECRET": "test_app_secret",
    "WHATSAPP_VERIFY_TOKEN": "test_verify_token",
    "WHATSAPP_TOKEN_ENCRYPTION_KEY": FAKE_FERNET_KEY,
    "WHATSAPP_SEND_BACKEND": "LOG",
    "WHATSAPP_DEFAULT_CONVERSATION_MODE": "WHATSAPP_FORM",
    "WHATSAPP_DEFAULT_COUNTRY_CODE": "27",
    "WHATSAPP_AI_MODEL": "gpt-5.1",
    "OPENAI_MODEL": "gpt-3.5-turbo-instruct",
}


def error_ids(**overrides):
    """Run the check with VALID_WHATSAPP_SETTINGS plus `overrides`, and return the error ids."""
    with override_settings(**{**VALID_WHATSAPP_SETTINGS, **overrides}):
        return [error.id for error in check_whatsapp_settings(app_configs=None)]


class TestWhatsAppSwitchedOff:
    def test_nothing_is_required_when_whatsapp_is_off(self):
        # Every value is empty or wrong, yet there are no errors: a deployment that doesn't use
        # WhatsApp must not be forced to configure it.
        assert (
            error_ids(
                WHATSAPP_ENABLED=False,
                WHATSAPP_GRAPH_API_VERSION="",
                WHATSAPP_APP_SECRET="",
                WHATSAPP_VERIFY_TOKEN="",
                WHATSAPP_TOKEN_ENCRYPTION_KEY="",
                WHATSAPP_SEND_BACKEND="nonsense",
                WHATSAPP_DEFAULT_CONVERSATION_MODE="nonsense",
            )
            == []
        )


class TestWhatsAppSwitchedOn:
    def test_a_complete_configuration_passes(self):
        assert error_ids() == []

    def test_missing_app_secret_is_an_error(self):
        # Our Meta app's secret signs every number's webhooks (plan Step 1.18); without it every
        # event is refused.
        assert error_ids(WHATSAPP_APP_SECRET="") == ["whatsapp.E001"]

    def test_missing_verify_token_is_an_error(self):
        # Without it, Meta's subscription check on the webhook URL can never succeed.
        assert error_ids(WHATSAPP_VERIFY_TOKEN="") == ["whatsapp.E002"]

    def test_missing_encryption_key_is_an_error(self):
        # Credentials can't be stored without it (plan decision D5).
        assert error_ids(WHATSAPP_TOKEN_ENCRYPTION_KEY="") == ["whatsapp.E003"]

    def test_malformed_encryption_key_is_its_own_error(self):
        # A different id from "missing", so the message can say how to generate a real key.
        assert error_ids(WHATSAPP_TOKEN_ENCRYPTION_KEY="not-a-fernet-key") == ["whatsapp.E004"]

    def test_unknown_send_backend_is_an_error(self):
        # A typo such as "metta" must not silently fall back to sending nothing.
        assert error_ids(WHATSAPP_SEND_BACKEND="metta") == ["whatsapp.E005"]

    def test_meta_send_backend_is_accepted(self):
        assert error_ids(WHATSAPP_SEND_BACKEND="META") == []

    def test_the_old_lowercase_values_are_refused(self):
        # Values are the enums' member names since Step 1.16 (agents.md section 5.3b), so an .env
        # still holding the old spelling fails at startup instead of being half understood.
        assert error_ids(WHATSAPP_SEND_BACKEND="meta") == ["whatsapp.E005"]
        assert error_ids(WHATSAPP_DEFAULT_CONVERSATION_MODE="agentic") == ["whatsapp.E006"]

    def test_unknown_conversation_mode_is_an_error(self):
        # Only the two modes the router knows: "WHATSAPP_FORM" and "AGENTIC".
        assert error_ids(WHATSAPP_DEFAULT_CONVERSATION_MODE="ai") == ["whatsapp.E006"]

    def test_agentic_conversation_mode_is_accepted(self):
        assert error_ids(WHATSAPP_DEFAULT_CONVERSATION_MODE="AGENTIC") == []

    def test_an_assistant_by_default_with_a_model_that_cant_call_tools_is_an_error(self):
        # An empty WHATSAPP_AI_MODEL falls back to OPENAI_MODEL, which upstream's .env.shared sets
        # to an instruct model for its SaaS ideas; instruct models have no function tools.
        assert error_ids(WHATSAPP_DEFAULT_CONVERSATION_MODE="AGENTIC", WHATSAPP_AI_MODEL="") == ["whatsapp.E009"]
        assert error_ids(WHATSAPP_DEFAULT_CONVERSATION_MODE="AGENTIC", WHATSAPP_AI_MODEL="gpt-3.5-turbo-instruct") == [
            "whatsapp.E009"
        ]

    def test_with_menus_by_default_the_model_isnt_checked(self):
        # Chosen on 2026-10-20: the check applies when the assistant is what users get by default.
        assert error_ids(WHATSAPP_DEFAULT_CONVERSATION_MODE="WHATSAPP_FORM", WHATSAPP_AI_MODEL="") == []

    @pytest.mark.parametrize("version", ["26.0", "v26", "latest", ""])
    def test_malformed_graph_api_version_is_an_error(self, version):
        # Meta's versions look like "v26.0"; anything else would build broken request URLs.
        assert error_ids(WHATSAPP_GRAPH_API_VERSION=version) == ["whatsapp.E007"]

    @pytest.mark.parametrize("country_code", ["", "+27", "0027", "2700", "ZA"])
    def test_a_default_country_code_that_isnt_1_to_3_digits_is_an_error(self, country_code):
        # Country codes are 1 to 3 digits (E.164); anything else would store every local number
        # wrongly (plan D19).
        assert error_ids(WHATSAPP_DEFAULT_COUNTRY_CODE=country_code) == ["whatsapp.E008"]

    def test_each_problem_is_reported_separately(self):
        # Several mistakes at once are all reported in one run, in id order, so they can be fixed
        # together instead of one deploy at a time.
        assert error_ids(
            WHATSAPP_APP_SECRET="",
            WHATSAPP_VERIFY_TOKEN="",
            WHATSAPP_TOKEN_ENCRYPTION_KEY="",
        ) == ["whatsapp.E001", "whatsapp.E002", "whatsapp.E003"]
