"""
Tests for the Shopify verification functions (HMAC and shop domain validation).
"""

import hmac
import hashlib
import json
import pytest
from apps.shopify.verification import is_valid_shop_domain, verify_query_hmac, verify_webhook_hmac

pytestmark = pytest.mark.django_db


def test_is_valid_shop_domain():
    # Valid domains
    assert is_valid_shop_domain("my-store.myshopify.com") is True
    assert is_valid_shop_domain("test-store-123.myshopify.com") is True
    # Shopify domains can actually be mixed case, we handle it if verification is strict?
    # Usually we lowercase, but the regex should ideally just accept lowercase or be case-insensitive.
    assert is_valid_shop_domain("UPPERCASE.myshopify.com") is True

    # Invalid domains
    assert is_valid_shop_domain("evil.myshopify.com.attacker.example") is False
    assert is_valid_shop_domain("my-store.example.com") is False
    assert is_valid_shop_domain("https://my-store.myshopify.com") is False
    assert is_valid_shop_domain("my-store.myshopify.com/") is False
    assert is_valid_shop_domain("my-store.myshopify.com/path") is False
    assert is_valid_shop_domain("") is False
    assert is_valid_shop_domain(None) is False


def test_verify_query_hmac():
    secret = "test_secret"

    # Happy path built in-memory
    params = {
        "shop": "test.myshopify.com",
        "timestamp": "1234567890",
        "host": "some-base64-string",
    }
    # Build query string exactly how Shopify does (sorted, no hmac or signature)
    query_string = "host=some-base64-string&shop=test.myshopify.com&timestamp=1234567890"
    valid_hmac = hmac.new(secret.encode(), query_string.encode(), hashlib.sha256).hexdigest()

    # Verification needs the hmac back in the params
    params_with_hmac = {**params, "hmac": valid_hmac}
    assert verify_query_hmac(params_with_hmac, secret) is True

    # Tampered value
    tampered_params = {**params, "hmac": "badhmac"}
    assert verify_query_hmac(tampered_params, secret) is False

    # Missing hmac
    assert verify_query_hmac(params, secret) is False

    # Extra parameters not included in signature should fail (as the signature would differ)
    extra_params = {**params, "hmac": valid_hmac, "attacker": "true"}
    assert verify_query_hmac(extra_params, secret) is False

    # Test Shopify's specific encoding rules for special characters
    special_params = {
        "shop": "test.myshopify.com",
        "timestamp": "1234567890",
        "foo&bar=baz": "val%ue&",
    }
    # Expected query string: foo%26bar%3Dbaz=val%25ue%26&shop=test.myshopify.com&timestamp=1234567890
    special_query_string = "foo%26bar%3Dbaz=val%25ue%26&shop=test.myshopify.com&timestamp=1234567890"
    special_hmac = hmac.new(secret.encode(), special_query_string.encode(), hashlib.sha256).hexdigest()
    special_params_with_hmac = {**special_params, "hmac": special_hmac}
    assert verify_query_hmac(special_params_with_hmac, secret) is True

    # (A real callback query will be added here in step 10)


def test_verify_webhook_hmac():
    secret = "test_secret"

    # Payload with spacing that would change if re-serialized by json.dumps
    # e.g., extra spaces after colons, which might be lost in python dict.
    raw_body = b'{"shop_id": 1234,  "domain":  "test.myshopify.com"}'

    import base64

    valid_hmac = base64.b64encode(hmac.new(secret.encode(), raw_body, hashlib.sha256).digest()).decode()

    assert verify_webhook_hmac(raw_body, valid_hmac, secret) is True

    # Tampered value
    assert verify_webhook_hmac(raw_body, "badhmac", secret) is False

    # Missing hmac
    assert verify_webhook_hmac(raw_body, None, secret) is False
    assert verify_webhook_hmac(raw_body, "", secret) is False
