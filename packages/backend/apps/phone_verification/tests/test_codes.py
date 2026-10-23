"""
Tests for apps/phone_verification: the channel-neutral store of one-time codes that prove a person
controls a phone number (plan decision D20, Step 1.7a).

Like the email confirmation in apps/users/tokens.py, except that a short typed code has to be
stored: it's too short to carry its own signature. So a code:
- is shown once, and only a keyed hash of it is stored
- expires, works once, and issuing a new one voids the user's older unused ones
- allows a few wrong guesses, then stops working
- is bound to one normalized phone number (D19) and one channel; checking it from another number or
  on another channel fails

The store knows nothing about WhatsApp: the WhatsApp linking (Step 1.7b), and later SMS, plug
into it with their own channel (D20).

Kind of test: integration (agents.md section 2.5). Why: codes are rows in the test database; nothing
is faked.
"""

from datetime import datetime, timedelta, timezone

import pytest

from apps.users.tests.factories import UserFactory

from ..constants import Channel
from ..models import PhoneVerificationCode
from ..services import MAX_ATTEMPTS, CodeCheckError, check_code, issue_code

pytestmark = pytest.mark.django_db

NUMBER = "27831234567"
TEN_MINUTES = 600
NOW = datetime(2026, 10, 18, 9, 0, tzinfo=timezone.utc)


@pytest.fixture
def user():
    return UserFactory()


def issue(user, number=NUMBER, channel=Channel.WHATSAPP_INBOUND):
    return issue_code(user=user, phone_number=number, channel=channel, ttl_seconds=TEN_MINUTES)


def check(code, number=NUMBER, channel=Channel.WHATSAPP_INBOUND):
    return check_code(phone_number=number, channel=channel, code=code)


class TestIssuing:
    def test_a_code_is_six_digits_and_shown_once(self, user):
        issued = issue(user)

        assert len(issued.code) == 6 and issued.code.isdigit()

    def test_only_a_hash_of_the_code_is_stored(self, user):
        issued = issue(user)

        row = PhoneVerificationCode.objects.values().get()
        assert issued.code not in str(row)
        assert row["phone_number"] == NUMBER
        assert row["channel"] == Channel.WHATSAPP_INBOUND

    def test_it_expires_after_the_given_time(self, user, freezer):
        freezer.move_to(NOW)

        issued = issue(user)

        assert issued.expires_at == NOW + timedelta(seconds=TEN_MINUTES)


class TestChecking:
    def test_the_right_code_from_the_same_number_names_the_user(self, user):
        issued = issue(user)

        assert check(issued.code) == user

    def test_a_code_works_once(self, user):
        issued = issue(user)
        check(issued.code)

        with pytest.raises(CodeCheckError) as raised:
            check(issued.code)

        assert raised.value.code == "no_code"

    def test_an_expired_code_is_refused(self, user, freezer):
        freezer.move_to(NOW)
        issued = issue(user)
        freezer.move_to(NOW + timedelta(seconds=TEN_MINUTES + 1))

        with pytest.raises(CodeCheckError) as raised:
            check(issued.code)

        assert raised.value.code == "no_code"

    def test_a_new_code_voids_the_users_older_ones(self, user):
        old = issue(user)
        new = issue(user)

        with pytest.raises(CodeCheckError):
            check(old.code)
        assert check(new.code) == user

    def test_a_code_checked_from_another_number_fails(self, user):
        # The proof is that the code came from this number (D20): another number proves nothing.
        issued = issue(user)

        with pytest.raises(CodeCheckError) as raised:
            check(issued.code, number="27839999999")

        assert raised.value.code == "no_code"
        # And it still works from the right number.
        assert check(issued.code) == user

    def test_a_code_checked_on_another_channel_fails(self, user):
        issued = issue(user)

        with pytest.raises(CodeCheckError):
            check(issued.code, channel=Channel.SMS)

    def test_a_wrong_code_is_refused(self, user):
        issued = issue(user)
        wrong = "000000" if issued.code != "000000" else "111111"

        with pytest.raises(CodeCheckError) as raised:
            check(wrong)

        assert raised.value.code == "wrong_code"


class TestGuessing:
    def test_after_too_many_wrong_guesses_even_the_right_code_stops_working(self, user):
        issued = issue(user)
        wrong = "000000" if issued.code != "000000" else "111111"
        for _ in range(MAX_ATTEMPTS):
            with pytest.raises(CodeCheckError):
                check(wrong)

        with pytest.raises(CodeCheckError) as raised:
            check(issued.code)

        assert raised.value.code == "no_code"

    def test_a_few_wrong_guesses_still_leave_the_right_code_working(self, user):
        issued = issue(user)
        wrong = "000000" if issued.code != "000000" else "111111"
        for _ in range(MAX_ATTEMPTS - 1):
            with pytest.raises(CodeCheckError):
                check(wrong)

        assert check(issued.code) == user
