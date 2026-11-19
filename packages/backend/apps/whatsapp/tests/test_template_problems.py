"""
Tests for telling the operator when a business's message templates can't be used (WhatsApp plan Step 4.7, user
story WA.D7.OP.J2.A1): late order updates fail until it's fixed, and fixing it (the wording, or the number's
access) is the operator's work.

- a template Meta rejected is emailed to OPERATOR_EMAILS once, naming the business, the number, the template
  and Meta's reason, whichever check finds it (the daily one, or the WhatsApp page opening); submitted again
  and rejected again, it's emailed again
- a submission Meta refuses (a revoked token, say) is emailed too, with Meta's error, and still raises
- with no OPERATOR_EMAILS nothing is sent, and a rejection isn't marked, so it's reported once one is set
- the Django admin lists every template with its number, status and Meta's reason, filterable by status

Kind of test: integration (agents.md section 2.5). Why: the numbers and templates are rows in the test
database, and the admin's pages go through Django's test client; Meta is never called (`requests.get` and
`requests.post` are replaced by fakes whose answers are canned), and upstream's send_email task is patched.
"""

import pytest
from django.urls import reverse
from django.utils import timezone

from apps.multitenancy.constants import TenantType
from apps.multitenancy.tests.factories import TenantFactory

from ..client import SendError
from ..constants import SendBackend
from ..models import WhatsAppTemplate
from ..services import templates
from .factories import ExternalAccountFactory
from .fakes import meta_error, meta_response

pytestmark = [pytest.mark.django_db, pytest.mark.story("WA.D7.OP.J2.A1")]

COMPONENTS = [{"type": "BODY", "text": "Hello, this is {{1}}.", "example": {"body_text": [["Acme"]]}}]


@pytest.fixture(autouse=True)
def on_meta(settings):
    settings.WHATSAPP_SEND_BACKEND = SendBackend.META
    settings.WHATSAPP_GRAPH_API_VERSION = "v26.0"


@pytest.fixture
def send_email(settings, mocker):
    settings.OPERATOR_EMAILS = ["ops@example.com"]
    return mocker.patch("common.emails.send_email")


@pytest.fixture
def account():
    organization = TenantFactory(type=TenantType.ORGANIZATION, name="Acme Outdoor")
    return ExternalAccountFactory(tenant=organization, display_phone_number="27000000777")


def stored(account, name="shop_order_paid", template_id="111", **fields):
    return WhatsAppTemplate.objects.create(
        waba_id=account.waba_id,
        name=name,
        template_id=template_id,
        content_sha256="0" * 64,
        submitted_at=timezone.now(),
        **fields,
    )


def meta_says(mocker, status, reason="NONE"):
    return mocker.patch(
        "apps.whatsapp.client.requests.get",
        return_value=meta_response(200, {"id": "111", "status": status, "rejected_reason": reason}),
    )


def emailed(send_email):
    """Each email sent, as (to, template name, data)."""
    return [(to, name, data) for (to, name, data, _lang) in (c.args[0] for c in send_email.apply_async.call_args_list)]


class TestARejection:
    def test_it_is_emailed_to_the_operator_with_the_business_number_template_and_reason(
        self, account, send_email, mocker
    ):
        meta_says(mocker, "REJECTED", "INVALID_FORMAT")
        template = stored(account)

        templates.check_statuses(account)

        [(to, name, data)] = emailed(send_email)
        assert to == ["ops@example.com"]
        assert name == "WHATSAPP_TEMPLATES_REFUSED"
        [problem] = data["problems"]
        assert problem == {
            "organization": "Acme Outdoor",
            "number": "27000000777",
            "template": "shop_order_paid",
            "reason": "Meta rejected it: INVALID_FORMAT",
        }
        template.refresh_from_db()
        assert template.reported_at is not None

    def test_it_is_emailed_once(self, account, send_email, mocker):
        meta_says(mocker, "REJECTED", "INVALID_FORMAT")
        stored(account)

        templates.check_statuses(account)
        templates.check_statuses(account)

        assert len(emailed(send_email)) == 1

    def test_the_page_opening_tells_the_operator_too(self, account, send_email, mocker):
        # The page then says the operator has been told (user story WA.D3.OM.J2.A2), so it must be true.
        meta_says(mocker, "REJECTED", "PROMOTIONAL")
        stored(account)

        templates.check_if_stale(account)

        [(_to, _name, data)] = emailed(send_email)
        assert data["problems"][0]["reason"] == "Meta rejected it: PROMOTIONAL"

    def test_submitted_again_and_rejected_again_it_is_emailed_again(self, account, send_email, mocker):
        meta_says(mocker, "REJECTED", "INVALID_FORMAT")
        stored(account)
        templates.check_statuses(account)
        # The operator fixes the wording; the edit goes back into review, then Meta rejects it again.
        mocker.patch("apps.whatsapp.client.requests.post", return_value=meta_response(200, {"success": True}))
        templates.submit(account, "shop_order_paid", category="UTILITY", language="en", components=COMPONENTS)

        templates.check_statuses(account)

        assert len(emailed(send_email)) == 2

    def test_an_approved_template_is_not_emailed(self, account, send_email, mocker):
        meta_says(mocker, "APPROVED")
        stored(account)

        templates.check_statuses(account)

        assert emailed(send_email) == []

    def test_without_an_operator_email_none_is_sent_and_none_is_marked(self, account, settings, mocker):
        settings.OPERATOR_EMAILS = []
        send_email = mocker.patch("common.emails.send_email")
        meta_says(mocker, "REJECTED", "INVALID_FORMAT")
        template = stored(account)

        templates.check_statuses(account)

        send_email.apply_async.assert_not_called()
        template.refresh_from_db()
        assert template.reported_at is None


class TestARefusedSubmission:
    def test_it_is_emailed_with_metas_error_and_still_raises(self, account, send_email, mocker):
        mocker.patch("apps.whatsapp.client.requests.post", return_value=meta_error(190, status=401))

        with pytest.raises(SendError):
            templates.submit(account, "shop_order_paid", category="UTILITY", language="en", components=COMPONENTS)

        [(to, name, data)] = emailed(send_email)
        assert (to, name) == (["ops@example.com"], "WHATSAPP_TEMPLATES_REFUSED")
        [problem] = data["problems"]
        assert problem["organization"] == "Acme Outdoor"
        assert problem["number"] == "27000000777"
        assert problem["template"] == "shop_order_paid"
        assert problem["reason"].startswith("Meta refused the submission: Meta error 190")

    def test_without_an_operator_email_none_is_sent(self, account, settings, mocker):
        settings.OPERATOR_EMAILS = []
        send_email = mocker.patch("common.emails.send_email")
        mocker.patch("apps.whatsapp.client.requests.post", return_value=meta_error(190, status=401))

        with pytest.raises(SendError):
            templates.submit(account, "shop_order_paid", category="UTILITY", language="en", components=COMPONENTS)

        send_email.apply_async.assert_not_called()


class TestTheAdmin:
    @pytest.fixture(autouse=True)
    def plain_static_files(self, settings):
        # Admin pages render {% static %}; plain storage serves files straight from the apps, as in
        # test_admin.py.
        settings.STORAGES = {
            **settings.STORAGES,
            "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
        }

    @pytest.fixture
    def operator_client(self, client, user_factory):
        # In this codebase User.is_staff is is_superuser, so only superusers can use the Django admin.
        client.force_login(user_factory(is_superuser=True))
        return client

    def changelist(self, operator_client, **query):
        response = operator_client.get(reverse("admin:whatsapp_whatsapptemplate_changelist"), query)
        assert response.status_code == 200
        return response.content.decode()

    def test_every_template_is_listed_with_its_number_status_and_reason(self, operator_client, account):
        stored(account, status="REJECTED", rejected_reason="INVALID_FORMAT")
        stored(account, name="shop_order_received", template_id="112", status="APPROVED")

        page = self.changelist(operator_client)

        assert "shop_order_paid" in page and "shop_order_received" in page
        assert "27000000777" in page
        assert "INVALID_FORMAT" in page
        assert "column-status" in page

    def test_it_filters_by_rejected(self, operator_client, account):
        stored(account, status="REJECTED", rejected_reason="INVALID_FORMAT")
        stored(account, name="shop_order_received", template_id="112", status="APPROVED")

        page = self.changelist(operator_client, status__exact="REJECTED")

        assert "shop_order_paid" in page
        assert "shop_order_received" not in page
