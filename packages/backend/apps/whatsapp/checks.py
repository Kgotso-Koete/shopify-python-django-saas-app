"""
Django system checks for the WhatsApp configuration.

They run on every `manage.py` command and when the server starts, so a deployment that switches
WhatsApp on (WHATSAPP_ENABLED) with a missing key or a mistyped value fails loudly at startup,
instead of as webhooks that silently fail. With WhatsApp off they require nothing. Registered in
apps.WhatsAppConfig.ready().

Our Meta app's App secret signs every number's webhooks, and its verify token answers Meta's
subscription check (plan Step 1.18):
https://developers.facebook.com/docs/graph-api/webhooks/getting-started
"""

import base64
import binascii
import re

from django.conf import settings
from django.core.checks import Error

from .constants import ConversationMode, SendBackend

# Meta's Graph API versions look like "v26.0" (https://developers.facebook.com/docs/graph-api/changelog).
GRAPH_API_VERSION_PATTERN = re.compile(r"v\d+\.\d+")
# Country codes are 1 to 3 digits (E.164, https://www.itu.int/rec/T-REC-E.164), written without "+".
COUNTRY_CODE_PATTERN = re.compile(r"\d{1,3}")

# How to make a key for WHATSAPP_TOKEN_ENCRYPTION_KEY, shown with the key errors below.
FERNET_KEY_HINT = (
    'Generate one with: python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"'
)


def check_whatsapp_settings(app_configs, **kwargs):
    """Return a list of configuration errors; an empty list means WhatsApp is off, or correctly set up."""
    # A deployment that doesn't use WhatsApp needs no WhatsApp configuration at all.
    if not settings.WHATSAPP_ENABLED:
        return []

    # Each problem is its own error, in id order, so every mistake shows up in one run.
    errors = []

    if not settings.WHATSAPP_APP_SECRET:
        errors.append(
            Error(
                "WHATSAPP_APP_SECRET must be set when WHATSAPP_ENABLED is True: it checks the signature "
                "on every webhook Meta sends for the numbers connected to our Meta app.",
                hint="It's in the Meta app's App settings, Basic, App secret.",
                id="whatsapp.E001",
            )
        )

    if not settings.WHATSAPP_VERIFY_TOKEN:
        errors.append(
            Error(
                "WHATSAPP_VERIFY_TOKEN must be set when WHATSAPP_ENABLED is True: Meta sends it back "
                "when it checks the webhook URL.",
                hint="Choose a long random string, and enter the same value as the verify token in the "
                "Meta app's webhook settings.",
                id="whatsapp.E002",
            )
        )

    # A missing key and a malformed one are separate errors, so each message says what to do.
    encryption_key = settings.WHATSAPP_TOKEN_ENCRYPTION_KEY
    if not encryption_key:
        errors.append(
            Error(
                "WHATSAPP_TOKEN_ENCRYPTION_KEY must be set when WHATSAPP_ENABLED is True: it encrypts "
                "the WhatsApp credentials stored in the database.",
                hint=FERNET_KEY_HINT,
                id="whatsapp.E003",
            )
        )
    elif not is_valid_fernet_key(encryption_key):
        errors.append(
            Error(
                "WHATSAPP_TOKEN_ENCRYPTION_KEY must be a valid Fernet key: 32 bytes, url-safe base64 encoded.",
                hint=FERNET_KEY_HINT,
                id="whatsapp.E004",
            )
        )

    if settings.WHATSAPP_SEND_BACKEND not in SendBackend.values:
        errors.append(
            Error(
                f"WHATSAPP_SEND_BACKEND is {settings.WHATSAPP_SEND_BACKEND!r}, expected one of {SendBackend.values}.",
                id="whatsapp.E005",
            )
        )

    if settings.WHATSAPP_DEFAULT_CONVERSATION_MODE not in ConversationMode.values:
        errors.append(
            Error(
                f"WHATSAPP_DEFAULT_CONVERSATION_MODE is {settings.WHATSAPP_DEFAULT_CONVERSATION_MODE!r}, "
                f"expected one of {ConversationMode.values}.",
                id="whatsapp.E006",
            )
        )

    if not GRAPH_API_VERSION_PATTERN.fullmatch(settings.WHATSAPP_GRAPH_API_VERSION):
        errors.append(
            Error(
                f"WHATSAPP_GRAPH_API_VERSION is {settings.WHATSAPP_GRAPH_API_VERSION!r}, expected a Meta "
                "Graph API version such as 'v26.0'.",
                id="whatsapp.E007",
            )
        )

    # Every local number is stored with this code (plan D19), so a wrong one stores them all wrongly.
    if not COUNTRY_CODE_PATTERN.fullmatch(settings.WHATSAPP_DEFAULT_COUNTRY_CODE):
        errors.append(
            Error(
                f"WHATSAPP_DEFAULT_COUNTRY_CODE is {settings.WHATSAPP_DEFAULT_COUNTRY_CODE!r}, expected a "
                "country code of 1 to 3 digits without '+', such as '27'.",
                id="whatsapp.E008",
            )
        )

    # The assistant needs function tools (plan Step 1.13), which instruct models don't have. An
    # empty WHATSAPP_AI_MODEL means OPENAI_MODEL, which upstream's .env.shared sets to one. Checked
    # when the assistant is what users get by default (maintainer's choice, 2026-10-20).
    ai_model = settings.WHATSAPP_AI_MODEL or settings.OPENAI_MODEL
    if settings.WHATSAPP_DEFAULT_CONVERSATION_MODE == ConversationMode.AGENTIC and (
        not ai_model or "instruct" in ai_model
    ):
        errors.append(
            Error(
                f"The WhatsApp assistant's model is {ai_model!r}, which can't call tools, and "
                "WHATSAPP_DEFAULT_CONVERSATION_MODE is 'AGENTIC'.",
                hint="Set WHATSAPP_AI_MODEL to a model with function calling, such as 'gpt-5.1'.",
                id="whatsapp.E009",
            )
        )

    return errors


def is_valid_fernet_key(key: str) -> bool:
    """True if `key` has the shape of a Fernet key: url-safe base64 that decodes to exactly 32 bytes."""
    try:
        return len(base64.urlsafe_b64decode(key)) == 32
    except (binascii.Error, ValueError):
        # Not base64 at all (for example wrong padding or characters).
        return False
