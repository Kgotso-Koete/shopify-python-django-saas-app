"""
The three MD5 signatures PayFast uses. Pure functions, with no Django or network access, so they are
easy to test against PayFast's reference implementation (apps/payfast/tests/test_signature.py).

Why three? PayFast signs each channel differently, and mixing them up is the most common cause of
"signature mismatch" errors:

1. Checkout form (browser -> PayFast): fields in the docs' order, blanks skipped.
   https://developers.payfast.co.za/docs#step_2_signature
2. ITN (PayFast -> us): fields in the order PayFast posted them, blanks kept, up to `signature`.
   https://developers.payfast.co.za/docs#step_4_confirm_payment
3. API (us -> api.payfast.co.za): everything sorted alphabetically, including the passphrase.
   https://developers.payfast.co.za/api#authentication

PayFast's server is PHP, so values are encoded exactly like PHP's urlencode(): spaces as '+',
upper-case percent escapes, and '~' encoded as %7E (Python's quote_plus would leave '~' alone).
"""

import hashlib
from urllib.parse import parse_qsl, quote_plus

# Every checkout field we may send, in the order the PayFast docs list them. The docs require the
# signature string to follow "the order in which they appear in the attributes description"
# (https://developers.payfast.co.za/docs#step_2_signature): merchant details, customer details,
# transaction details, transaction options, payment methods (docs#step_1_form_fields), then the
# subscription fields in their own table's order (docs#subscriptions).
CHECKOUT_FIELD_ORDER = (
    # Merchant details
    "merchant_id",
    "merchant_key",
    "return_url",
    "cancel_url",
    "notify_url",
    "fica_idnumber",
    # Customer details
    "name_first",
    "name_last",
    "email_address",
    "cell_number",
    # Transaction details
    "m_payment_id",
    "amount",
    "item_name",
    "item_description",
    "custom_int1",
    "custom_int2",
    "custom_int3",
    "custom_int4",
    "custom_int5",
    "custom_str1",
    "custom_str2",
    "custom_str3",
    "custom_str4",
    "custom_str5",
    # Transaction options
    "email_confirmation",
    "confirmation_address",
    # Payment methods
    "payment_method",
    # Subscriptions (recurring billing)
    "subscription_type",
    "billing_date",
    "recurring_amount",
    "frequency",
    "cycles",
    "subscription_notify_email",
    "subscription_notify_webhook",
    "subscription_notify_buyer",
)


def php_urlencode(value) -> str:
    """Encode `value` the way PHP's urlencode() does, which is what PayFast's server compares against."""
    return quote_plus(str(value), safe="").replace("~", "%7E")


def _md5(text: str) -> str:
    return hashlib.md5(text.encode("utf-8")).hexdigest()  # noqa: S324 - MD5 is mandated by PayFast


def _with_passphrase(param_string: str, passphrase: str) -> str:
    if passphrase:
        return f"{param_string}&passphrase={php_urlencode(passphrase.strip())}"
    return param_string


# --- 1. Checkout -------------------------------------------------------------------------------


def ordered_checkout_fields(fields: dict) -> list:
    """
    Return the non-blank checkout fields as (key, value) pairs in PayFast's documented order.
    Raises ValueError for a field PayFast doesn't document, since it has no defined position.
    """
    unknown = sorted(set(fields) - set(CHECKOUT_FIELD_ORDER))
    if unknown:
        raise ValueError(f"Unknown PayFast checkout field(s): {', '.join(unknown)}")
    return [
        (key, str(fields[key]).strip())
        for key in CHECKOUT_FIELD_ORDER
        if key in fields and fields[key] is not None and str(fields[key]).strip() != ""
    ]


def checkout_param_string(fields: dict) -> str:
    """The "key=value&..." string that the checkout signature is computed over (without passphrase)."""
    return "&".join(f"{key}={php_urlencode(value)}" for key, value in ordered_checkout_fields(fields))


def checkout_signature(fields: dict, passphrase: str) -> str:
    """Signature for the checkout form's hidden `signature` input."""
    return _md5(_with_passphrase(checkout_param_string(fields), passphrase))


# --- 2. ITN ------------------------------------------------------------------------------------


def parse_itn_body(raw_body: bytes) -> list:
    """
    Decode a form-encoded ITN body into (key, value) pairs, keeping PayFast's order and blank values.
    Django's request.POST (a QueryDict) doesn't promise to keep order, so the raw body is parsed instead.
    """
    return parse_qsl(raw_body.decode("utf-8"), keep_blank_values=True)


def itn_param_string(pairs: list) -> str:
    """
    Every field up to (not including) `signature`, blanks included, re-encoded like PHP does.
    The same string is posted to PayFast's /eng/query/validate endpoint.
    """
    parts = []
    for key, value in pairs:
        if key == "signature":
            break
        parts.append(f"{key}={php_urlencode(value)}")
    return "&".join(parts)


def itn_signature_is_valid(pairs: list, passphrase: str) -> bool:
    """True if the ITN's `signature` field matches the signature we compute from its other fields."""
    received = dict(pairs).get("signature")
    if not received:
        return False
    return _md5(_with_passphrase(itn_param_string(pairs), passphrase)) == received.lower()


# --- 3. API ------------------------------------------------------------------------------------


def api_signature(headers: dict, body: dict, passphrase: str) -> str:
    """
    Signature for the `signature` header on api.payfast.co.za calls: all header, body and query
    variables plus the passphrase, sorted alphabetically, non-blank, URL-encoded. The sandbox's
    `testing` flag is left out, as the docs require.
    """
    variables = {**headers, **body, "passphrase": passphrase}
    variables.pop("testing", None)
    return _md5(
        "&".join(
            f"{key}={php_urlencode(str(value).strip())}"
            for key, value in sorted(variables.items())
            if value is not None and str(value).strip() != ""
        )
    )
