"""
Tests for the order templates (WhatsApp plan phase 4, Step 4.3d-2, decisions 6, 23 and 24): what a store
customer gets about their order once the 24-hour window has closed, and how each business's WhatsApp
Business account gets the templates.

- since Step 4.7 (decision 30), one utility template for any stage, in English, with fixed wording around two
  blanks (the store, the order number), never starting or ending with one, and an Order details quick-reply
  button: the tap brings the customer back into the window, where the details are sent live from Shopify
- connecting a number that serves customers submits it, in a Celery task; a team-only or inactive
  number gets none; Meta refusing it is logged, and connecting again or the command tries again
- `whatsapp_publish_order_templates` submits it to every active number serving customers
- publishing retires the two templates it replaced (shop_order_received and shop_order_paid, with their View
  order link), deleting them on Meta and here

Kind of test: integration (agents.md section 2.5). Why: the numbers and templates are rows in the test
database; Meta is never called: the log send backend stores fake ids, or `requests.post` is replaced by
a fake whose answer is canned, and the Celery task's `delay` is patched where queuing is checked.
"""

import re
from io import StringIO

import pytest
from django.core.management import call_command
from django.utils import timezone

from apps.whatsapp.constants import AccountPurpose, SendBackend
from apps.whatsapp.tests.factories import ExternalAccountFactory, InternalAccountFactory

pytestmark = [pytest.mark.django_db, pytest.mark.story("WA.D5.SC.J1.A2")]

# Since Step 4.7 (decision 30): one template for any stage. The two it replaced are retired.
NAMES = ["shop_order_update"]
RETIRED = ["shop_order_paid", "shop_order_received"]
BLANK = re.compile(r"\{\{\d+\}\}")


def order_templates() -> dict:
    """The templates by name."""
    # Imported here, not at the top, so a missing module fails each test instead of the whole file.
    from apps.whatsapp_shop import templates

    return templates.order_templates()


def stored(account):
    from apps.whatsapp.models import WhatsAppTemplate

    return sorted(WhatsAppTemplate.objects.filter(waba_id=account.waba_id).values_list("name", flat=True))


def publish(account_id):
    from apps.whatsapp_shop.tasks import publish_order_templates

    publish_order_templates(str(account_id))


class TestTheTemplate:
    def test_there_is_one_for_every_stage(self):
        assert sorted(order_templates()) == NAMES

    def test_it_is_a_utility_template_in_english_with_two_blanks_and_an_order_details_button(self):
        template = order_templates()["shop_order_update"]

        assert template["category"] == "UTILITY"
        assert template["language"] == "en"
        body, buttons = template["components"]
        assert body["type"] == "BODY"
        assert (
            body["text"] == "Hello, this is {{1}}. There's an update on your order {{2}}. Tap Order details to see it."
        )
        assert BLANK.findall(body["text"]) == ["{{1}}", "{{2}}"]
        # Meta refuses a template that starts or ends with a blank.
        assert not body["text"].startswith("{{") and not body["text"].rstrip(".!").endswith("}}")
        assert len(body["example"]["body_text"][0]) == 2
        # A quick reply, not a link: the tap brings the customer back into the 24-hour window.
        assert buttons == {"type": "BUTTONS", "buttons": [{"type": "QUICK_REPLY", "text": "Order details"}]}


# Also the operator's story WA.D7.OP.J2.A1: connecting a number submits them.
@pytest.mark.story("WA.D7.OP.J2.A1")
class TestConnectingANumber:
    @pytest.mark.parametrize(
        "purpose", [AccountPurpose.EXTERNAL_COMMUNICATIONS, AccountPurpose.INTERNAL_AND_EXTERNAL_COMMUNICATIONS]
    )
    def test_a_number_serving_customers_has_its_templates_submitted_in_a_task(self, mocker, purpose):
        from apps.whatsapp import registry

        delay = mocker.patch("apps.whatsapp_shop.tasks.publish_order_templates.delay")
        account = ExternalAccountFactory(purpose=purpose)

        registry.handler_for(AccountPurpose.EXTERNAL_COMMUNICATIONS).on_connected(account)

        delay.assert_called_once_with(str(account.pk))

    def test_the_task_submits_both_to_the_numbers_business_account(self):
        account = ExternalAccountFactory()

        publish(account.pk)

        assert stored(account) == NAMES

    def test_a_team_only_or_inactive_number_gets_none(self):
        team = InternalAccountFactory()
        inactive = ExternalAccountFactory(is_active=False)

        publish(team.pk)
        publish(inactive.pk)

        assert stored(team) == []
        assert stored(inactive) == []

    def test_meta_refusing_them_is_logged_not_raised(self, mocker, settings, caplog):
        settings.WHATSAPP_SEND_BACKEND = SendBackend.META
        response = mocker.Mock(ok=False, status_code=400)
        response.json.return_value = {"error": {"code": 100, "message": "Invalid parameter"}}
        mocker.patch("apps.whatsapp.client.requests.post", return_value=response)
        account = ExternalAccountFactory()

        publish(account.pk)

        assert stored(account) == []
        assert any("templates" in record.message for record in caplog.records)


# Also the operator's story WA.D7.OP.J2.A1: the command covers every number, past any Meta refuses.
@pytest.mark.story("WA.D7.OP.J2.A1")
class TestTheCommand:
    def test_it_submits_them_to_every_active_number_serving_customers(self):
        first, second = ExternalAccountFactory(), ExternalAccountFactory()
        team = InternalAccountFactory()
        out = StringIO()

        call_command("whatsapp_publish_order_templates", stdout=out)

        assert stored(first) == NAMES
        assert stored(second) == NAMES
        assert stored(team) == []
        assert "shop_order_update" in out.getvalue()

    def test_a_number_meta_refuses_doesnt_stop_the_others_and_the_command_fails_at_the_end(self, mocker, settings):
        # WhatsApp plan Step 4.6: one business's bad token (or a demo number's fake one) must not leave
        # every later number without its templates, and cron must still see a failure.
        from django.core.management import CommandError

        settings.WHATSAPP_SEND_BACKEND = SendBackend.META
        refused = ExternalAccountFactory(waba_id="300000000000001")
        accepted = ExternalAccountFactory(waba_id="300000000000002")

        def meta(url, **kwargs):
            # Meta refuses everything for the first number's business account, and accepts the second's.
            response = mocker.Mock(ok=refused.waba_id not in url, status_code=400)
            response.json.return_value = (
                {"error": {"code": 190, "message": "Invalid OAuth access token"}}
                if refused.waba_id in url
                else {"id": "888", "status": "PENDING", "category": "UTILITY"}
            )
            return response

        mocker.patch("apps.whatsapp.client.requests.post", side_effect=meta)
        out = StringIO()

        with pytest.raises(CommandError) as raised:
            call_command("whatsapp_publish_order_templates", stdout=out)

        assert stored(refused) == []
        assert stored(accepted) == NAMES
        assert "Invalid OAuth access token" in out.getvalue()
        assert str(refused) in str(raised.value)
        assert str(accepted) not in str(raised.value)


class TestRetiringTheOldTemplates:
    """
    Step 4.7 (decision 30): shop_order_received and shop_order_paid, with their View order link, are replaced by
    shop_order_update. Publishing deletes them from the business's account and from the service's records, so
    they no longer show on the WhatsApp page.
    """

    def stored_old(self, account):
        from apps.whatsapp.models import WhatsAppTemplate

        for name in RETIRED:
            WhatsAppTemplate.objects.create(
                waba_id=account.waba_id,
                name=name,
                template_id=f"9{len(name)}",
                content_sha256="0" * 64,
                submitted_at=timezone.now(),
            )

    def test_publishing_deletes_them_on_meta_and_here(self, mocker, settings):
        settings.WHATSAPP_SEND_BACKEND = SendBackend.META
        response = mocker.Mock(ok=True)
        response.json.return_value = {"id": "888", "status": "PENDING", "category": "UTILITY", "success": True}
        mocker.patch("apps.whatsapp.client.requests.post", return_value=response)
        delete = mocker.patch("apps.whatsapp.client.requests.delete", return_value=response)
        account = ExternalAccountFactory()
        self.stored_old(account)

        publish(account.pk)

        assert stored(account) == NAMES
        # Meta deletes a template by its name, from the WhatsApp Business account.
        deleted = sorted(call.kwargs["params"]["name"] for call in delete.call_args_list)
        assert deleted == RETIRED
        assert all(call.args[0].endswith(f"/{account.waba_id}/message_templates") for call in delete.call_args_list)

    def test_one_meta_no_longer_has_is_forgotten_here_too(self, mocker, settings):
        settings.WHATSAPP_SEND_BACKEND = SendBackend.META
        response = mocker.Mock(ok=True)
        response.json.return_value = {"id": "888", "status": "PENDING", "category": "UTILITY", "success": True}
        mocker.patch("apps.whatsapp.client.requests.post", return_value=response)
        gone = mocker.Mock(ok=False, status_code=400)
        gone.json.return_value = {"error": {"code": 100, "message": "Template not found"}}
        mocker.patch("apps.whatsapp.client.requests.delete", return_value=gone)
        account = ExternalAccountFactory()
        self.stored_old(account)

        publish(account.pk)

        assert stored(account) == NAMES

    def test_the_log_backend_forgets_them_without_asking_meta(self, mocker, settings):
        settings.WHATSAPP_SEND_BACKEND = SendBackend.LOG
        delete = mocker.patch("apps.whatsapp.client.requests.delete")
        account = ExternalAccountFactory()
        self.stored_old(account)

        publish(account.pk)

        assert stored(account) == NAMES
        delete.assert_not_called()
