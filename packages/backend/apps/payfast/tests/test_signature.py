"""
Tests for apps/payfast/signature.py: the three MD5 signatures PayFast uses.

1. Checkout signature (https://developers.payfast.co.za/docs#step_2_signature): non-blank fields,
   in the order they appear in the docs' attribute tables, URL-encoded, plus the passphrase.
2. ITN signature (https://developers.payfast.co.za/docs#step_4_confirm_payment): every posted field
   in the order received (blanks included) up to `signature`, plus the passphrase.
3. API signature (https://developers.payfast.co.za/api#authentication): header, body and query
   variables plus the passphrase, sorted alphabetically, excluding `testing`.

The oracle for the expected values is PayFast's own published reference implementation (PHP, since
PayFast's server is PHP), reproduced below in Python, rather than our own code.
"""

import hashlib
from urllib.parse import quote_plus

import pytest

from .. import signature

pytestmark = pytest.mark.django_db

PASSPHRASE = "jt7NOE43FZPn"  # the passphrase used in PayFast's own documentation examples


def php_urlencode(value: str) -> str:
    """PHP's urlencode(): like quote_plus, but it also encodes '~' (as %7E)."""
    return quote_plus(value, safe="").replace("~", "%7E")


def payfast_reference_signature(ordered_pairs, passphrase=None):
    """
    The docs' PHP generateSignature(), step for step: skip blank values, "key=urlencode(trim(value))"
    joined with '&', then "&passphrase=urlencode(trim(passphrase))", then MD5.
    """
    output = "&".join(f"{key}={php_urlencode(str(value).strip())}" for key, value in ordered_pairs if value != "")
    if passphrase is not None:
        output += f"&passphrase={php_urlencode(passphrase.strip())}"
    return hashlib.md5(output.encode()).hexdigest()


class TestCheckoutSignature:
    def test_fields_are_ordered_as_in_payfast_docs_not_as_given(self):
        # Deliberately scrambled input order: the function must reorder to the documented order.
        fields = {
            "cycles": "0",
            "item_name": "Monthly plan",
            "merchant_key": "46f0cd694581a",
            "custom_str1": "note",
            "amount": "199.00",
            "subscription_type": "1",
            "merchant_id": "10000100",
            "notify_url": "https://api.example.com/api/payfast/notify/",
            "frequency": "3",
            "m_payment_id": "abc",
            "recurring_amount": "199.00",
            "billing_date": "2026-10-07",
            "email_address": "owner@example.com",
        }
        expected_order = [
            "merchant_id",
            "merchant_key",
            "notify_url",
            "email_address",
            "m_payment_id",
            "amount",
            "item_name",
            "custom_str1",
            "subscription_type",
            "billing_date",
            "recurring_amount",
            "frequency",
            "cycles",
        ]

        assert [key for key, _ in signature.ordered_checkout_fields(fields)] == expected_order
        assert signature.checkout_signature(fields, PASSPHRASE) == payfast_reference_signature(
            [(key, fields[key]) for key in expected_order], PASSPHRASE
        )

    def test_blank_fields_are_left_out(self):
        with_blanks = {"merchant_id": "10000100", "name_first": "", "amount": "5.00", "item_name": "Donation"}
        without_blanks = {"merchant_id": "10000100", "amount": "5.00", "item_name": "Donation"}

        assert signature.checkout_signature(with_blanks, PASSPHRASE) == signature.checkout_signature(
            without_blanks, PASSPHRASE
        )

    def test_values_are_url_encoded_like_php(self):
        # Spaces as '+', upper-case percent escapes, and '~' encoded, as PHP's urlencode does.
        fields = {"merchant_id": "10000100", "amount": "5.00", "item_name": "Tea & cake ~ R5/cup"}

        assert signature.checkout_param_string(fields) == (
            "merchant_id=10000100&amount=5.00&item_name=Tea+%26+cake+%7E+R5%2Fcup"
        )

    def test_an_empty_passphrase_is_not_appended(self):
        fields = {"merchant_id": "10000100", "amount": "5.00", "item_name": "Donation"}

        assert signature.checkout_signature(fields, "") == payfast_reference_signature(list(fields.items()))

    def test_unknown_fields_are_rejected(self):
        # A field outside the documented list would have no defined position in the signature string.
        with pytest.raises(ValueError, match="made_up_field"):
            signature.checkout_signature({"merchant_id": "1", "made_up_field": "x"}, PASSPHRASE)


class TestItnSignature:
    # A raw ITN body as PayFast posts it: form-encoded, in PayFast's own order, with empty fields.
    RAW_BODY = (
        b"m_payment_id=SuperUnique1&pf_payment_id=1089250&payment_status=COMPLETE"
        b"&item_name=test+product&item_description=&amount_gross=200.00&amount_fee=-4.60"
        b"&amount_net=195.40&custom_str1=&name_first=John&email_address=john%40example.com"
        b"&merchant_id=10000100&token=dc0521d3-55fe-269b-fa00-b647310d760f&billing_date=2026-10-07"
    )
    ORDERED_PAIRS = [
        ("m_payment_id", "SuperUnique1"),
        ("pf_payment_id", "1089250"),
        ("payment_status", "COMPLETE"),
        ("item_name", "test product"),
        ("item_description", ""),
        ("amount_gross", "200.00"),
        ("amount_fee", "-4.60"),
        ("amount_net", "195.40"),
        ("custom_str1", ""),
        ("name_first", "John"),
        ("email_address", "john@example.com"),
        ("merchant_id", "10000100"),
        ("token", "dc0521d3-55fe-269b-fa00-b647310d760f"),
        ("billing_date", "2026-10-07"),
    ]

    def reference_itn_signature(self):
        # The docs' ITN loop url-encodes EVERY posted value, blanks included, in received order.
        param_string = "&".join(f"{key}={php_urlencode(value)}" for key, value in self.ORDERED_PAIRS)
        return hashlib.md5(f"{param_string}&passphrase={php_urlencode(PASSPHRASE)}".encode()).hexdigest()

    def signed_body(self, signature_value=None):
        return self.RAW_BODY + b"&signature=" + (signature_value or self.reference_itn_signature()).encode()

    def test_parse_keeps_received_order_and_blank_values(self):
        assert signature.parse_itn_body(self.signed_body())[:-1] == self.ORDERED_PAIRS

    def test_param_string_includes_blanks_and_stops_at_signature(self):
        param_string = signature.itn_param_string(signature.parse_itn_body(self.signed_body() + b"&after=ignored"))

        assert "item_description=&" in param_string
        assert "signature" not in param_string
        assert "after" not in param_string

    def test_valid_signature_is_accepted(self):
        assert signature.itn_signature_is_valid(signature.parse_itn_body(self.signed_body()), PASSPHRASE)

    def test_tampered_amount_is_rejected(self):
        tampered = self.signed_body().replace(b"amount_gross=200.00", b"amount_gross=2.00")

        assert not signature.itn_signature_is_valid(signature.parse_itn_body(tampered), PASSPHRASE)

    def test_wrong_passphrase_is_rejected(self):
        assert not signature.itn_signature_is_valid(signature.parse_itn_body(self.signed_body()), "wrong")

    def test_missing_signature_is_rejected(self):
        assert not signature.itn_signature_is_valid(signature.parse_itn_body(self.RAW_BODY), PASSPHRASE)


class TestApiSignature:
    def test_headers_body_and_passphrase_are_sorted_alphabetically(self):
        headers = {"merchant-id": "10000100", "version": "v1", "timestamp": "2026-09-30T12:00:00+02:00"}
        body = {"amount": "19900", "frequency": "6"}

        expected_string = (
            "amount=19900&frequency=6&merchant-id=10000100&passphrase=jt7NOE43FZPn"
            "&timestamp=2026-09-30T12%3A00%3A00%2B02%3A00&version=v1"
        )
        assert signature.api_signature(headers, body, PASSPHRASE) == hashlib.md5(expected_string.encode()).hexdigest()

    def test_testing_parameter_and_blank_values_are_excluded(self):
        # "When in test mode the testing parameter should be excluded from the signature."
        headers = {"merchant-id": "10000100", "version": "v1", "timestamp": "2026-09-30T12:00:00+02:00"}

        assert signature.api_signature(headers, {"testing": "true", "cycles": ""}, PASSPHRASE) == (
            signature.api_signature(headers, {}, PASSPHRASE)
        )
