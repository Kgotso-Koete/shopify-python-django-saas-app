"""
Tests for apps/whatsapp/services/number_tools.py: the number troubleshooting tools (plan D18,
Step 1.5b, user story 23). They wrap Meta's repair calls in checked, logged operations:

- the input is checked before Meta is asked (SMS or VOICE, a numeric code, a 6-digit PIN)
- every repair call writes an action-log entry, whatever Meta answered, without the code or the PIN
- each of Meta's errors comes back with a plain explanation and a link to Meta's page
- the PIN and the code are never stored

Meta's references: https://developers.facebook.com/documentation/business-messaging/whatsapp/business-phone-numbers/phone-numbers.md
https://developers.facebook.com/documentation/business-messaging/whatsapp/business-phone-numbers/registration.md
https://developers.facebook.com/documentation/business-messaging/whatsapp/support/error-codes

Kind of test: integration (agents.md section 2.5). Why: the tools read accounts and write action-log
rows in the test database; Meta's HTTP is mocked.
"""

import json

import pytest

from apps.multitenancy.models import ActionLog
from apps.users.tests.factories import UserFactory

from ..services import number_tools
from ..services.number_tools import NumberToolError
from .factories import ExternalAccountFactory
from .fakes import meta_error, meta_response

pytestmark = pytest.mark.django_db

PIN = "654321"
CODE = "123456"


@pytest.fixture(autouse=True)
def graph_api_version(settings):
    settings.WHATSAPP_GRAPH_API_VERSION = "v26.0"


@pytest.fixture
def account():
    return ExternalAccountFactory(phone_number_id="100000000000777", display_phone_number="+27 83 000 0777")


@pytest.fixture
def admin():
    return UserFactory()


@pytest.fixture
def meta_post(mocker):
    return mocker.patch("apps.whatsapp.client.requests.post", return_value=meta_response(200, {"success": True}))


def log_entries(account):
    return list(ActionLog.objects.filter(entity_type="whatsapp_account", entity_id=str(account.id)))


class TestStatus:
    def test_meta_s_fields_come_back_as_they_are(self, account, mocker):
        meta_status = {"status": "CONNECTED", "code_verification_status": "VERIFIED", "quality_rating": "GREEN"}
        mocker.patch("apps.whatsapp.client.requests.get", return_value=meta_response(200, meta_status))

        assert number_tools.get_status(account) == meta_status


class TestCheckedBeforeMetaIsAsked:
    @pytest.mark.parametrize("method", ["sms", "Voice"])
    def test_sms_and_voice_are_accepted_in_any_case(self, account, admin, meta_post, method):
        number_tools.request_code(account, method=method, actor=admin)

        assert meta_post.call_args.kwargs["params"]["code_method"] == method.upper()

    def test_any_other_method_is_refused(self, account, admin, meta_post):
        with pytest.raises(NumberToolError) as raised:
            number_tools.request_code(account, method="email", actor=admin)

        assert (raised.value.code, raised.value.field) == ("invalid_method", "method")
        meta_post.assert_not_called()

    @pytest.mark.parametrize("code", ["", "12a456", "12"])
    def test_a_code_that_isnt_digits_is_refused(self, account, admin, meta_post, code):
        with pytest.raises(NumberToolError) as raised:
            number_tools.verify_code(account, code=code, actor=admin)

        assert (raised.value.code, raised.value.field) == ("invalid_code", "code")
        meta_post.assert_not_called()

    @pytest.mark.parametrize("pin", ["", "12345", "1234567", "12a456"])
    def test_a_pin_that_isnt_6_digits_is_refused(self, account, admin, meta_post, pin):
        with pytest.raises(NumberToolError) as raised:
            number_tools.register(account, pin=pin, actor=admin)

        assert (raised.value.code, raised.value.field) == ("invalid_pin", "pin")
        meta_post.assert_not_called()

    def test_a_disconnected_number_has_no_token_to_ask_with(self, account, admin, meta_post):
        account.is_active = False
        account.save()

        with pytest.raises(NumberToolError) as raised:
            number_tools.subscribe_app(account, actor=admin)

        assert raised.value.code == "not_connected"
        meta_post.assert_not_called()


class TestRepairs:
    def test_registering_passes_the_pin_to_meta_and_stores_it_nowhere(self, account, admin, meta_post):
        number_tools.register(account, pin=PIN, actor=admin)

        assert meta_post.call_args.kwargs["json"]["pin"] == PIN
        # Not on the account, and not in the action log.
        account_row = json.dumps(list(type(account).objects.filter(pk=account.pk).values()), default=str)
        log_rows = json.dumps(list(ActionLog.objects.values()), default=str)
        assert PIN not in account_row
        assert PIN not in log_rows

    @pytest.mark.parametrize(
        "operation, call",
        [
            ("request_code", lambda account, admin: number_tools.request_code(account, method="SMS", actor=admin)),
            ("verify_code", lambda account, admin: number_tools.verify_code(account, code=CODE, actor=admin)),
            ("register", lambda account, admin: number_tools.register(account, pin=PIN, actor=admin)),
            ("subscribe_app", lambda account, admin: number_tools.subscribe_app(account, actor=admin)),
        ],
    )
    def test_every_repair_is_written_to_the_action_log_without_the_code_or_pin(
        self, account, admin, meta_post, operation, call
    ):
        call(account, admin)

        [entry] = log_entries(account)
        assert entry.actor_user == admin
        assert entry.tenant_id == account.tenant_id
        assert entry.metadata["operation"] == operation
        assert entry.metadata["outcome"] == "succeeded"
        assert PIN not in json.dumps(entry.metadata) and CODE not in json.dumps(entry.metadata)
        assert PIN not in json.dumps(entry.changes) and CODE not in json.dumps(entry.changes)

    def test_a_refused_repair_is_logged_too_with_meta_s_code(self, account, admin, meta_post):
        # Meta counts every registration attempt against its 72-hour limit, so failures are recorded.
        meta_post.return_value = meta_error(133005)

        with pytest.raises(NumberToolError):
            number_tools.register(account, pin=PIN, actor=admin)

        [entry] = log_entries(account)
        assert entry.metadata["outcome"] == "failed"
        assert entry.metadata["meta_error_code"] == 133005


class TestMetaErrorsExplained:
    @pytest.mark.parametrize(
        "meta_code, code, words",
        [
            (133016, "too_many_attempts", "72 hours"),  # 10 registrations per 72 hours, then blocked
            (136024, "already_verified", "already verified"),  # no code needed
            (133005, "wrong_pin", "PIN"),  # the two-step verification PIN is wrong
            (133006, "verify_first", "verified"),  # verify with a code before registering
        ],
    )
    def test_each_known_error_has_its_own_explanation_and_a_link(
        self, account, admin, meta_post, meta_code, code, words
    ):
        meta_post.return_value = meta_error(meta_code)

        with pytest.raises(NumberToolError) as raised:
            number_tools.register(account, pin=PIN, actor=admin)

        assert raised.value.code == code
        assert raised.value.meta_code == meta_code
        assert words in str(raised.value)
        assert str(meta_code) in str(raised.value)
        assert raised.value.help_url.startswith("https://developers.facebook.com/")

    def test_an_unknown_error_shows_meta_s_own_message(self, account, admin, meta_post):
        # Meta doesn't document a code for a wrong verification code, so its own words are shown.
        meta_post.return_value = meta_error(100)

        with pytest.raises(NumberToolError) as raised:
            number_tools.verify_code(account, code=CODE, actor=admin)

        assert raised.value.code == "meta_refused"
        assert "Something went wrong" in str(raised.value)
        assert (
            raised.value.help_url
            == "https://developers.facebook.com/documentation/business-messaging/whatsapp/support/error-codes"
        )
