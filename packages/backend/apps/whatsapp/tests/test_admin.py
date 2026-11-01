"""
Tests for the WhatsApp Django admin (apps/whatsapp/admin.py, plan Step 1.5b, D18): the operator's
view of every number, with the same troubleshooting tools organization admins get in the WhatsApp
tab (user story 23), for when an organization asks the operator for help.

- the account's secrets are never shown, nor an organization's Meta app's (plan Step 2.9)
- Meta's status, a verification code by SMS or voice, and re-subscribing the app are admin actions
- registering with the PIN and entering a code have a small form page each, as PayFast's refund does
- every repair is recorded in the admin's own history, without the PIN or the code

Kind of test: integration (agents.md section 2.5). Why: requests go through the Django admin pages
with Django's test client, against the test database; Meta's HTTP is mocked.
"""

import pytest
from django.contrib.admin.models import LogEntry
from django.urls import reverse

from .factories import InternalAccountFactory, MetaAppFactory
from .fakes import meta_error, meta_response

pytestmark = pytest.mark.django_db

ACCESS_TOKEN = "EAAGnumber-secret-token"
PIN = "654321"


@pytest.fixture(autouse=True)
def plain_static_files(settings):
    # Admin pages render {% static %}; plain storage serves files straight from the apps, as in
    # apps/payfast/tests/test_admin.py.
    settings.STORAGES = {
        **settings.STORAGES,
        "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
    }
    settings.WHATSAPP_GRAPH_API_VERSION = "v26.0"


@pytest.fixture
def operator_client(client, user_factory):
    # In this codebase User.is_staff is is_superuser, so only superusers can use the Django admin.
    client.force_login(user_factory(is_superuser=True))
    return client


@pytest.fixture
def number():
    return InternalAccountFactory(access_token=ACCESS_TOKEN)


@pytest.fixture
def meta_post(mocker):
    return mocker.patch("apps.whatsapp.client.requests.post", return_value=meta_response(200, {"success": True}))


def run_action(operator_client, action, account):
    return operator_client.post(
        reverse("admin:whatsapp_whatsappaccount_changelist"),
        {"action": action, "_selected_action": [account.pk]},
        follow=True,
    )


class TestPages:
    @pytest.mark.parametrize("model_name", ["whatsappaccount", "whatsappcontact", "whatsappmessage"])
    def test_each_changelist_loads(self, operator_client, number, model_name):
        assert operator_client.get(reverse(f"admin:whatsapp_{model_name}_changelist")).status_code == 200

    def test_the_account_page_never_shows_its_secrets(self, operator_client, number):
        response = operator_client.get(reverse("admin:whatsapp_whatsappaccount_change", args=[number.pk]))

        page = response.content.decode()
        assert response.status_code == 200
        assert ACCESS_TOKEN not in page
        assert number.access_token_encrypted not in page

    def test_an_organizations_meta_app_is_listed_and_its_secrets_never_shown(self, operator_client):
        # Plan Step 2.9: the operator can find, and free, an App ID another organization needs.
        app = MetaAppFactory(app_secret="meta-app-secret-value")

        listing = operator_client.get(reverse("admin:whatsapp_metaapp_changelist"))
        response = operator_client.get(reverse("admin:whatsapp_metaapp_change", args=[app.pk]))

        assert app.app_id in listing.content.decode()
        page = response.content.decode()
        assert response.status_code == 200
        for secret in ["meta-app-secret-value", app.app_secret_encrypted, app.verify_token, app.verify_token_encrypted]:
            assert secret not in page
        assert "access_token_encrypted" not in page


class TestActions:
    def test_meta_s_status_is_shown_as_a_message(self, operator_client, number, mocker):
        mocker.patch(
            "apps.whatsapp.client.requests.get",
            return_value=meta_response(200, {"status": "CONNECTED", "code_verification_status": "VERIFIED"}),
        )

        response = run_action(operator_client, "check_status", number)

        page = response.content.decode()
        assert "CONNECTED" in page
        assert "VERIFIED" in page

    @pytest.mark.parametrize("action, method", [("request_code_sms", "SMS"), ("request_code_voice", "VOICE")])
    def test_a_code_is_requested_by_sms_or_voice(self, operator_client, number, meta_post, action, method):
        run_action(operator_client, action, number)

        assert meta_post.call_args.kwargs["params"]["code_method"] == method

    def test_the_app_is_subscribed_again(self, operator_client, number, meta_post):
        run_action(operator_client, "subscribe_app", number)

        assert meta_post.call_args.args[0].endswith(f"/{number.waba_id}/subscribed_apps")

    def test_meta_s_error_is_shown_with_its_explanation(self, operator_client, number, meta_post):
        meta_post.return_value = meta_error(136024)

        response = run_action(operator_client, "request_code_sms", number)

        assert "already verified" in response.content.decode()


class TestRegisterAndVerifyPages:
    def test_the_account_page_links_to_both_forms(self, operator_client, number):
        page = operator_client.get(reverse("admin:whatsapp_whatsappaccount_change", args=[number.pk])).content.decode()

        assert reverse("admin:whatsapp_whatsappaccount_register", args=[number.pk]) in page
        assert reverse("admin:whatsapp_whatsappaccount_verify", args=[number.pk]) in page

    def test_registering_warns_about_meta_s_limit_first(self, operator_client, number):
        page = operator_client.get(
            reverse("admin:whatsapp_whatsappaccount_register", args=[number.pk])
        ).content.decode()

        assert "10" in page and "72 hours" in page

    def test_registering_passes_the_pin_to_meta_and_records_it_without_the_pin(
        self, operator_client, number, meta_post
    ):
        response = operator_client.post(
            reverse("admin:whatsapp_whatsappaccount_register", args=[number.pk]), {"pin": PIN}, follow=True
        )

        assert response.status_code == 200
        assert meta_post.call_args.kwargs["json"] == {"messaging_product": "whatsapp", "pin": PIN}
        [entry] = LogEntry.objects.filter(object_id=str(number.pk))
        assert "register" in entry.get_change_message()
        assert PIN not in entry.change_message

    def test_a_wrong_pin_shape_is_refused_on_the_form(self, operator_client, number, meta_post):
        response = operator_client.post(
            reverse("admin:whatsapp_whatsappaccount_register", args=[number.pk]), {"pin": "12"}
        )

        assert "6 digits" in response.content.decode()
        meta_post.assert_not_called()

    def test_verifying_sends_the_code_to_meta(self, operator_client, number, meta_post):
        operator_client.post(
            reverse("admin:whatsapp_whatsappaccount_verify", args=[number.pk]), {"code": "123456"}, follow=True
        )

        assert meta_post.call_args.kwargs["data"] == {"code": "123456"}
