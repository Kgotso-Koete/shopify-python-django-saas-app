"""
Tests for apps/whatsapp/verification.py: checking that a webhook really came from Meta (plan
decision D6).

Meta signs every webhook POST with X-Hub-Signature-256: "sha256=" plus the HMAC-SHA256 of the raw
body, keyed with the Meta app's secret:
https://developers.facebook.com/docs/graph-api/webhooks/getting-started

Kind of test: unit (agents.md section 2.5). Why: a plain signature function, with no database or
network; nothing is faked.
"""

import hashlib
import hmac

import pytest

from ..verification import signature_is_valid

# The root conftest.py registers fixtures whose autouse parts need the database.
pytestmark = pytest.mark.django_db

SECRET = "test-app-secret"
BODY = b'{"object":"whatsapp_business_account","entry":[]}'


def sign(body: bytes, secret: str) -> str:
    """The header Meta would send for `body` signed with `secret`."""
    return "sha256=" + hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()


class TestSignatureIsValid:
    def test_a_correct_signature_is_valid(self):
        assert signature_is_valid(BODY, sign(BODY, SECRET), SECRET) is True

    def test_a_signature_made_with_another_secret_is_invalid(self):
        assert signature_is_valid(BODY, sign(BODY, "another-secret"), SECRET) is False

    def test_a_body_changed_by_one_byte_is_invalid(self):
        # The signature covers the exact raw bytes, so even a re-serialized but equal JSON fails.
        tampered = BODY.replace(b"[]", b"[ ]")

        assert signature_is_valid(tampered, sign(BODY, SECRET), SECRET) is False

    def test_a_missing_header_is_invalid(self):
        assert signature_is_valid(BODY, None, SECRET) is False
        assert signature_is_valid(BODY, "", SECRET) is False

    def test_a_header_without_the_sha256_prefix_is_invalid(self):
        bare_hex = sign(BODY, SECRET).removeprefix("sha256=")

        assert signature_is_valid(BODY, bare_hex, SECRET) is False

    def test_an_empty_secret_refuses_everything(self):
        # Fail closed: with no secret configured, nothing is trusted, not even a body "signed" with
        # an empty key. The reference app did the opposite and accepted every request.
        assert signature_is_valid(BODY, sign(BODY, ""), "") is False
