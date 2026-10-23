"""
Checking that a webhook really came from Meta (plan decision D6).

Meta's webhook rules: https://developers.facebook.com/docs/graph-api/webhooks/getting-started
- Every POST carries X-Hub-Signature-256: "sha256=" plus the HMAC-SHA256 of the raw request body,
  keyed with the Meta app's App secret: ours, WHATSAPP_APP_SECRET (plan Step 1.18).
"""

import hashlib
import hmac

SIGNATURE_PREFIX = "sha256="


def signature_is_valid(raw_body: bytes, signature_header: str | None, secret: str) -> bool:
    """
    True only if `signature_header` is Meta's signature of exactly `raw_body` under `secret`.

    The HMAC covers the raw bytes, so this must run on the body as received, before any JSON
    parsing: re-serialized JSON, even if equal, has different bytes.
    """
    # Fail closed: with no secret nothing can be trusted, so nothing is (unlike the reference app,
    # which accepted every request when its secret was unset).
    if not secret or not signature_header or not signature_header.startswith(SIGNATURE_PREFIX):
        return False

    expected = hmac.new(secret.encode("utf-8"), raw_body, hashlib.sha256).hexdigest()
    received = signature_header[len(SIGNATURE_PREFIX) :]
    # compare_digest takes the same time whatever the input, so the comparison leaks nothing about
    # how much of a forged signature was right.
    return hmac.compare_digest(expected, received)
