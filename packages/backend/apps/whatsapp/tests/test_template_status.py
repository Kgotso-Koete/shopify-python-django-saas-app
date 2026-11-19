"""
Tests for keeping each message template's review status (WhatsApp plan Step 4.7, user story WA.D3.OM.J2.A2,
decided 2026-11-08: the status comes from asking Meta's API, with no webhook, so no business has another
field to tick in its own Meta app).

- submitting a template keeps the status Meta answers with; an edit is in review again; the log backend's
  templates count as approved, since nothing is sent to Meta to review
- the check asks Meta for each stored template's status and keeps it, with Meta's reason for a rejection,
  translated to this app's own names (agents.md section 5.3b); the log backend's templates are never asked
- it runs once a day, as a command (cron, no worker) and a beat task (agents.md section 4.1), past any
  number Meta refuses
- the WhatsApp page lists each number's templates with their status, asking Meta again when the last answer
  is older than CHECK_AGAIN_AFTER; a failure there keeps the last status and doesn't break the page

Kind of test: integration (agents.md section 2.5). Why: the numbers and templates are rows in the test
database, and the page's query goes through the real GraphQL schema and permissions; Meta is never called:
`requests.get` and `requests.post` are replaced by fakes whose answers are canned. The exception is the
beat-schedule tests, which are sanity: they read settings in a fresh subprocess.
"""

from datetime import timedelta
from io import StringIO

import pytest
from django.core.management import call_command
from django.utils import timezone
from graphql_relay import to_global_id

from apps.multitenancy.constants import TenantType, TenantUserRole
from apps.multitenancy.tests.factories import TenantFactory, TenantMembershipFactory
from apps.users.tests.factories import UserFactory

from ..constants import SendBackend
from ..models import WhatsAppTemplate
from .factories import ExternalAccountFactory
from .fakes import meta_error, meta_response
from .utils import read_settings

pytestmark = [pytest.mark.django_db, pytest.mark.story("WA.D3.OM.J2.A2")]

COMPONENTS = [{"type": "BODY", "text": "Hello, this is {{1}}.", "example": {"body_text": [["Acme"]]}}]
CHANGED = [{"type": "BODY", "text": "Hi, this is {{1}}.", "example": {"body_text": [["Acme"]]}}]

ACCOUNTS = """
query($tenantId: ID!) {
  whatsAppAccounts(tenantId: $tenantId) {
    id
    templates { name status rejectedReason statusCheckedAt }
  }
}
"""


def templates():
    # Imported here, not at the top, so a missing function fails each test instead of the whole file.
    from apps.whatsapp.services import templates

    return templates


def submit(account, components=COMPONENTS):
    return templates().submit(account, "shop_test", category="UTILITY", language="en", components=components)


def stored(account, name="shop_test", template_id="111", **fields):
    """A template submitted to Meta earlier, as the database keeps it."""
    return WhatsAppTemplate.objects.create(
        waba_id=account.waba_id,
        name=name,
        template_id=template_id,
        content_sha256="0" * 64,
        submitted_at=timezone.now(),
        **fields,
    )


def status_answer(status, reason="NONE"):
    """Meta's answer about one template: its name, id, status and rejection reason."""
    return meta_response(200, {"id": "111", "name": "shop_test", "status": status, "rejected_reason": reason})


@pytest.fixture
def account():
    return ExternalAccountFactory()


@pytest.fixture
def on_meta(settings):
    settings.WHATSAPP_SEND_BACKEND = SendBackend.META
    settings.WHATSAPP_GRAPH_API_VERSION = "v26.0"


class TestSubmitting:
    def test_a_new_template_keeps_the_status_meta_answers_with(self, account, on_meta, mocker):
        mocker.patch(
            "apps.whatsapp.client.requests.post",
            return_value=meta_response(200, {"id": "111", "status": "PENDING", "category": "UTILITY"}),
        )

        template, _ = submit(account)

        assert template.status == "IN_REVIEW"
        assert template.status_checked_at is not None

    def test_one_meta_approves_at_once_is_approved(self, account, on_meta, mocker):
        # Meta may approve a utility template within seconds, and says so in its answer.
        mocker.patch(
            "apps.whatsapp.client.requests.post",
            return_value=meta_response(200, {"id": "111", "status": "APPROVED", "category": "UTILITY"}),
        )

        template, _ = submit(account)

        assert template.status == "APPROVED"

    def test_an_edit_is_in_review_again_without_its_old_reason(self, account, on_meta, mocker):
        mocker.patch("apps.whatsapp.client.requests.post", return_value=meta_response(200, {"success": True}))
        stored(account, status="REJECTED", rejected_reason="INVALID_FORMAT")

        template, changed = submit(account, CHANGED)

        assert changed
        assert template.status == "IN_REVIEW"
        assert template.rejected_reason == ""

    def test_the_log_backends_templates_count_as_approved(self, account, settings):
        settings.WHATSAPP_SEND_BACKEND = SendBackend.LOG

        template, _ = submit(account)

        assert template.status == "APPROVED"


class TestCheckingWithMeta:
    @pytest.mark.parametrize(
        ("metas", "ours"),
        [
            ("PENDING", "IN_REVIEW"),
            ("IN_APPEAL", "IN_REVIEW"),
            ("APPROVED", "APPROVED"),
            ("REJECTED", "REJECTED"),
            ("PAUSED", "PAUSED"),
            ("DISABLED", "DISABLED"),
        ],
    )
    def test_metas_status_is_kept_in_this_apps_own_names(self, account, on_meta, mocker, metas, ours):
        mocker.patch("apps.whatsapp.client.requests.get", return_value=status_answer(metas))
        template = stored(account)

        templates().check_statuses(account)

        template.refresh_from_db()
        assert template.status == ours
        assert template.status_checked_at is not None

    def test_a_rejection_keeps_metas_reason(self, account, on_meta, mocker):
        mocker.patch("apps.whatsapp.client.requests.get", return_value=status_answer("REJECTED", "INVALID_FORMAT"))
        template = stored(account)

        templates().check_statuses(account)

        template.refresh_from_db()
        assert template.rejected_reason == "INVALID_FORMAT"

    def test_meta_is_asked_about_each_template_by_its_id(self, account, on_meta, mocker):
        get = mocker.patch("apps.whatsapp.client.requests.get", return_value=status_answer("APPROVED"))
        stored(account, template_id="111")

        templates().check_statuses(account)

        [call] = get.call_args_list
        assert call.args[0] == "https://graph.facebook.com/v26.0/111"
        assert call.kwargs["params"] == {"fields": "name,status,rejected_reason"}
        assert call.kwargs["headers"]["Authorization"] == "Bearer test-access-token"

    def test_only_the_numbers_own_business_accounts_templates_are_checked(self, account, on_meta, mocker):
        get = mocker.patch("apps.whatsapp.client.requests.get", return_value=status_answer("APPROVED"))
        other = stored(ExternalAccountFactory(), template_id="222")

        templates().check_statuses(account)

        get.assert_not_called()
        other.refresh_from_db()
        assert other.status == "IN_REVIEW"

    def test_the_log_backends_templates_are_never_asked_about(self, account, on_meta, mocker):
        get = mocker.patch("apps.whatsapp.client.requests.get")
        stored(account, template_id="log-shop_test", status="APPROVED")

        templates().check_statuses(account)

        get.assert_not_called()

    def test_nothing_is_asked_on_the_log_backend(self, account, settings, mocker):
        settings.WHATSAPP_SEND_BACKEND = SendBackend.LOG
        get = mocker.patch("apps.whatsapp.client.requests.get")
        stored(account)

        templates().check_statuses(account)

        get.assert_not_called()

    def test_meta_refusing_raises_and_keeps_the_last_status(self, account, on_meta, mocker):
        from apps.whatsapp.client import SendError

        mocker.patch("apps.whatsapp.client.requests.get", return_value=meta_error(190, status=401))
        template = stored(account, status="APPROVED")

        with pytest.raises(SendError):
            templates().check_statuses(account)

        template.refresh_from_db()
        assert template.status == "APPROVED"


class TestTheDailyCheck:
    def test_the_command_checks_every_active_numbers_templates(self, on_meta, mocker):
        mocker.patch("apps.whatsapp.client.requests.get", return_value=status_answer("APPROVED"))
        first, second = ExternalAccountFactory(), ExternalAccountFactory()
        inactive = ExternalAccountFactory(is_active=False)
        checked = [stored(first), stored(second, template_id="112")]
        left = stored(inactive, template_id="113")
        out = StringIO()

        call_command("whatsapp_check_template_statuses", stdout=out)

        for template in checked:
            template.refresh_from_db()
            assert template.status == "APPROVED"
        left.refresh_from_db()
        assert left.status == "IN_REVIEW"
        assert "checked=2" in out.getvalue()

    def test_a_number_meta_refuses_doesnt_stop_the_others_and_the_command_fails_at_the_end(self, on_meta, mocker):
        from django.core.management import CommandError

        refused, accepted = ExternalAccountFactory(), ExternalAccountFactory()
        stored(refused, template_id="401")
        template = stored(accepted, template_id="200")

        def meta(url, **kwargs):
            return meta_error(190, status=401) if url.endswith("/401") else status_answer("APPROVED")

        mocker.patch("apps.whatsapp.client.requests.get", side_effect=meta)

        with pytest.raises(CommandError) as raised:
            call_command("whatsapp_check_template_statuses", stdout=StringIO())

        template.refresh_from_db()
        assert template.status == "APPROVED"
        assert str(refused) in str(raised.value)
        assert str(accepted) not in str(raised.value)

    def test_the_beat_task_runs_the_check(self, on_meta, mocker):
        from apps.whatsapp import tasks

        mocker.patch("apps.whatsapp.client.requests.get", return_value=status_answer("REJECTED"))
        template = stored(ExternalAccountFactory())

        tasks.check_template_statuses()

        template.refresh_from_db()
        assert template.status == "REJECTED"


class TestBeatSchedule:
    def test_the_check_is_scheduled_daily_when_whatsapp_is_enabled(self):
        schedule = read_settings(["CELERY_BEAT_SCHEDULE"], WHATSAPP_ENABLED="true")["CELERY_BEAT_SCHEDULE"]

        assert "'whatsapp-check-template-statuses'" in schedule
        assert "'apps.whatsapp.tasks.check_template_statuses'" in schedule
        assert "86400" in schedule  # every 24 hours, in seconds

    def test_it_isnt_scheduled_without_whatsapp(self):
        schedule = read_settings(["CELERY_BEAT_SCHEDULE"], WHATSAPP_ENABLED="false")["CELERY_BEAT_SCHEDULE"]

        assert "whatsapp" not in schedule


class TestTheWhatsAppPage:
    @pytest.fixture
    def organization(self):
        return TenantFactory(type=TenantType.ORGANIZATION)

    @pytest.fixture
    def member(self, graphene_client, organization):
        """A Member, who has whatsapp.view, working in the organization."""
        user = UserFactory()
        TenantMembershipFactory(user=user, tenant=organization, role=TenantUserRole.MEMBER)
        graphene_client.force_authenticate(user)
        graphene_client.set_tenant_dependent_context(organization, TenantUserRole.MEMBER)
        return user

    def listed(self, graphene_client, organization):
        response = graphene_client.query(
            ACCOUNTS, variable_values={"tenantId": to_global_id("TenantType", organization.id)}
        )
        assert "errors" not in response, response
        [account] = response["data"]["whatsAppAccounts"]
        return account["templates"]

    def test_each_number_lists_its_templates_with_their_status(
        self, graphene_client, organization, member, on_meta, mocker
    ):
        account = ExternalAccountFactory(tenant=organization)
        stored(account, name="shop_order_received", status="APPROVED", status_checked_at=timezone.now())
        stored(
            account,
            name="shop_order_paid",
            template_id="112",
            status="REJECTED",
            rejected_reason="INVALID_FORMAT",
            status_checked_at=timezone.now(),
        )
        stored(ExternalAccountFactory(), name="someone_elses", template_id="113")

        assert self.listed(graphene_client, organization) == [
            {
                "name": "shop_order_paid",
                "status": "REJECTED",
                "rejectedReason": "INVALID_FORMAT",
                "statusCheckedAt": mocker.ANY,
            },
            {"name": "shop_order_received", "status": "APPROVED", "rejectedReason": "", "statusCheckedAt": mocker.ANY},
        ]

    def test_a_status_checked_recently_isnt_asked_again(self, graphene_client, organization, member, on_meta, mocker):
        get = mocker.patch("apps.whatsapp.client.requests.get")
        account = ExternalAccountFactory(tenant=organization)
        stored(account, status_checked_at=timezone.now() - timedelta(minutes=1))

        self.listed(graphene_client, organization)

        get.assert_not_called()

    def test_an_older_status_is_asked_again_when_the_page_opens(
        self, graphene_client, organization, member, on_meta, mocker
    ):
        mocker.patch("apps.whatsapp.client.requests.get", return_value=status_answer("APPROVED"))
        account = ExternalAccountFactory(tenant=organization)
        stale = timezone.now() - templates().CHECK_AGAIN_AFTER - timedelta(minutes=1)
        stored(account, status_checked_at=stale)

        [template] = self.listed(graphene_client, organization)

        assert template["status"] == "APPROVED"

    def test_meta_failing_keeps_the_last_status_and_the_page_works(
        self, graphene_client, organization, member, on_meta, mocker
    ):
        mocker.patch("apps.whatsapp.client.requests.get", return_value=meta_error(190, status=401))
        account = ExternalAccountFactory(tenant=organization)
        stored(account)

        [template] = self.listed(graphene_client, organization)

        assert template["status"] == "IN_REVIEW"
