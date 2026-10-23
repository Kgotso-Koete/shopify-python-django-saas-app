"""
One stored format for phone numbers (plan decision D19): international digits with no "+", e.g.
"27831234567", the format Meta's wa_id uses:
https://developers.facebook.com/documentation/business-messaging/whatsapp/webhooks/reference/messages.md

Hand-written rather than the `phonenumbers` library (maintainer's choice, 2026-10-15). It accepts the
common ways people type a number:
- separators are removed: spaces, "-", "_", ".", "/" and brackets
- a trunk "(0)" after the country code is dropped ("+27 (0)83 …")
- a leading "+" or "00" means the country code is already there
- a single leading "0" is replaced by the default country code (WHATSAPP_DEFAULT_COUNTRY_CODE)
- anything else must already start with its country code

The result must be 8 to 15 digits, E.164's limit (https://www.itu.int/rec/T-REC-E.164). A
well-shaped but wrong number passes; the link code and the test message prove a number is real.
"""

import re

from django.conf import settings

E164_MIN_DIGITS = 8
E164_MAX_DIGITS = 15

# A trunk "(0)" kept after a country code, as in "+27 (0)83 123 4567".
TRUNK_ZERO = re.compile(r"(?<=\d)\s*\(0\)")
# Everything people put between digits.
SEPARATORS = re.compile(r"[\s\-_./()]")

EXAMPLE = "+27 83 123 4567 or 083 123 4567"


class InvalidPhoneNumber(ValueError):
    """The text can't be a phone number. Its message is written for the person who typed it."""


def normalize_phone_number(typed: str, default_country_code: str | None = None) -> str:
    """
    `typed` as international digits with no "+" (e.g. "27831234567"). A local number (one leading
    0) takes `default_country_code`, or WHATSAPP_DEFAULT_COUNTRY_CODE when none is given.
    Raises InvalidPhoneNumber when it can't be a phone number.
    """
    text = SEPARATORS.sub("", TRUNK_ZERO.sub("", typed.strip()))
    if not text:
        raise InvalidPhoneNumber(f"Enter a phone number, such as {EXAMPLE}.")

    if text.startswith("+"):
        digits = text[1:]
    elif text.startswith("00"):
        digits = text[2:]
    elif text.startswith("0"):
        country_code = default_country_code or settings.WHATSAPP_DEFAULT_COUNTRY_CODE
        digits = country_code + text[1:]
    else:
        digits = text

    # Letters, an extension, or a "+" anywhere but the start.
    if not digits.isdigit():
        raise InvalidPhoneNumber(f"A phone number may only contain digits, such as {EXAMPLE}.")
    if not E164_MIN_DIGITS <= len(digits) <= E164_MAX_DIGITS:
        raise InvalidPhoneNumber(
            f"A phone number has {E164_MIN_DIGITS} to {E164_MAX_DIGITS} digits with its country code, "
            f"such as {EXAMPLE}."
        )
    return digits
