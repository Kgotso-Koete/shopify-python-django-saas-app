"""
Tests for apps/whatsapp/phone_numbers.py: turning a phone number typed the way people type them into
the one format this app stores, international digits with no "+" (plan decision D19), e.g.
"27831234567", the format Meta's wa_id uses.

The result must be 8 to 15 digits, E.164's limit: https://www.itu.int/rec/T-REC-E.164
A well-shaped but wrong number can't be told apart here; the link code (user story 1) and the test
message (user story 11) prove a number is real.

Kind of test: unit (agents.md section 2.5). Why: one plain function, with no database or network;
the only setting it reads is overridden per test; nothing is faked.
"""

import pytest

from ..phone_numbers import InvalidPhoneNumber, normalize_phone_number

# The root conftest.py registers fixtures whose autouse parts need the database.
pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def south_africa(settings):
    settings.WHATSAPP_DEFAULT_COUNTRY_CODE = "27"


class TestTheWaysPeopleTypeANumber:
    @pytest.mark.parametrize(
        "typed",
        [
            "083 123-4567",  # local, with a space and a dash
            "0831234567",  # local, digits only
            "+27 83 123 4567",  # international, with "+"
            "+27 (0)83 123 4567",  # international, with the trunk "(0)" people often keep
            "0027 83 123 4567",  # international, with the "00" exit code
            "27831234567",  # already in the stored format
            "(083) 123.4567",  # brackets and dots
            "083/123/4567",  # slashes
            "  083 123 4567  ",  # stray spaces around it
        ],
    )
    def test_each_gives_the_stored_format(self, typed):
        assert normalize_phone_number(typed) == "27831234567"

    def test_underscores_are_separators_too(self):
        # The maintainer's own example (plan D19): "+2783-123_1234".
        assert normalize_phone_number("+2783-123_1234") == "27831231234"


class TestTheDefaultCountryCode:
    def test_a_local_number_takes_the_configured_country_code(self, settings):
        # Kenya: 254, and a local number starting with a single 0.
        settings.WHATSAPP_DEFAULT_COUNTRY_CODE = "254"

        assert normalize_phone_number("0712 345 678") == "254712345678"

    def test_a_number_with_its_own_country_code_ignores_the_default(self, settings):
        settings.WHATSAPP_DEFAULT_COUNTRY_CODE = "254"

        assert normalize_phone_number("+27 83 123 4567") == "27831234567"

    def test_the_caller_may_pass_the_country_code(self):
        # For a number whose country is known from elsewhere, such as an organization's own country.
        assert normalize_phone_number("020 7946 0958", default_country_code="44") == "442079460958"


class TestRefused:
    @pytest.mark.parametrize(
        "typed",
        [
            "",  # nothing
            "   ",  # only spaces
            "083 CALL NOW",  # letters
            "083 123 4567 ext 2",  # an extension
            "+27 83 +123 4567",  # a "+" anywhere but the start
            "0831",  # too short: 5 digits once the country code is added
            "+1234567",  # too short: 7 digits
            "+1234567890123456",  # too long: 16 digits
        ],
    )
    def test_a_number_that_cant_be_one_is_refused_with_a_clear_error(self, typed):
        with pytest.raises(InvalidPhoneNumber) as raised:
            normalize_phone_number(typed)

        # Shown to the person who typed it, so it says what was wrong in their words.
        assert "phone number" in str(raised.value)

    def test_the_error_is_a_value_error(self):
        # So form and serializer code that already catches ValueError handles it.
        assert issubclass(InvalidPhoneNumber, ValueError)

    def test_eight_and_fifteen_digits_are_the_limits(self):
        assert normalize_phone_number("+12345678") == "12345678"
        assert normalize_phone_number("+123456789012345") == "123456789012345"
