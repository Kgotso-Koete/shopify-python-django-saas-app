"""
Tests for publishing this app's WhatsApp Flows (plan Step 1.11a, decision D9, Step 1.17): the Flow
JSON in apps/whatsapp_saas/flows/, published once to each internal communications number's WhatsApp
Business account.

The reference app created a new Flow every time it started. Here each form's published Flow id is
stored with a hash of its JSON (WhatsAppFlow), so a run with nothing changed publishes nothing, and
a changed file publishes a new Flow, since Meta doesn't let a published one be edited. With the log
send backend nothing reaches Meta: fake ids are stored, so the menus work locally.

Since Step 1.17 connecting an internal number publishes its forms, through a Celery task queued once
the number is saved; the whatsapp_publish_flows command does the same for every active one.

Kind of test: integration (agents.md section 2.5). Why: the command and the task read the Flow files
and store WhatsAppFlow rows in the test database; Meta's HTTP is mocked, and so is the task's delay.
"""

import json
import shutil
from io import StringIO

import pytest
from django.core.management import CommandError, call_command

from apps.whatsapp import registry
from apps.whatsapp.constants import AccountPurpose
from apps.whatsapp.models import WhatsAppFlow
from apps.whatsapp.tests.factories import ExternalAccountFactory, InternalAccountFactory
from apps.whatsapp.tests.fakes import meta_response

from .. import tasks
from ..flows import FLOWS_DIR, SCREEN_NAMES

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def graph_api_version(settings):
    settings.WHATSAPP_GRAPH_API_VERSION = "v26.0"


@pytest.fixture
def internal():
    return InternalAccountFactory(waba_id="200000000000001")


@pytest.fixture
def meta(settings, mocker):
    settings.WHATSAPP_SEND_BACKEND = "META"
    answers = iter(
        meta_response(200, {"id": f"9000000000000{n:02d}", "success": True, "validation_errors": []}) for n in range(20)
    )
    return mocker.patch("apps.whatsapp.client.requests.post", side_effect=lambda *args, **kwargs: next(answers))


def publish():
    out = StringIO()
    call_command("whatsapp_publish_flows", stdout=out)
    return out.getvalue()


class TestPublishing:
    def test_each_form_is_published_to_the_internal_numbers_account_and_its_id_stored(self, internal, meta):
        publish()

        assert meta.call_count == len(SCREEN_NAMES)
        for call in meta.call_args_list:
            assert call.args[0] == "https://graph.facebook.com/v26.0/200000000000001/flows"
            assert call.kwargs["json"]["publish"] is True
            # The file as it is, as a string, as Meta asks.
            name = call.kwargs["json"]["name"].rsplit("-", 1)[0]
            assert json.loads(call.kwargs["json"]["flow_json"]) == json.loads((FLOWS_DIR / f"{name}.json").read_text())
        stored = WhatsAppFlow.objects.filter(waba_id="200000000000001")
        assert {flow.name for flow in stored} == set(SCREEN_NAMES)
        assert all(flow.flow_id.startswith("9000000000000") for flow in stored)

    def test_every_active_internal_number_gets_them(self, internal, settings):
        settings.WHATSAPP_SEND_BACKEND = "LOG"
        other = InternalAccountFactory(waba_id="200000000000002")
        InternalAccountFactory(waba_id="200000000000003", is_active=False)
        ExternalAccountFactory(waba_id="200000000000004")

        publish()

        assert set(WhatsAppFlow.objects.values_list("waba_id", flat=True)) == {internal.waba_id, other.waba_id}

    def test_a_second_run_with_nothing_changed_publishes_nothing(self, internal, meta):
        publish()
        meta.reset_mock()

        output = publish()

        meta.assert_not_called()
        assert "up to date" in output

    def test_a_changed_form_is_published_again_as_a_new_flow(self, internal, meta, tmp_path, mocker):
        for path in FLOWS_DIR.glob("*.json"):
            shutil.copy(path, tmp_path / path.name)
        mocker.patch("apps.whatsapp_saas.publishing.FLOWS_DIR", tmp_path)
        publish()
        first = WhatsAppFlow.objects.get(name="item").flow_id
        changed = json.loads((tmp_path / "item.json").read_text())
        changed["screens"][0]["title"] = "A new title"
        (tmp_path / "item.json").write_text(json.dumps(changed))
        meta.reset_mock()

        publish()

        assert meta.call_count == 1
        assert WhatsAppFlow.objects.get(name="item").flow_id != first

    def test_meta_s_validation_errors_stop_the_command_and_store_nothing(self, internal, settings, mocker):
        settings.WHATSAPP_SEND_BACKEND = "META"
        mocker.patch(
            "apps.whatsapp.client.requests.post",
            return_value=meta_response(
                200,
                {"id": "1", "success": False, "validation_errors": [{"error": "X", "message": "Bad component."}]},
            ),
        )

        with pytest.raises(CommandError) as raised:
            publish()

        assert "Bad component." in str(raised.value)
        assert not WhatsAppFlow.objects.exists()


class TestWithoutMeta:
    def test_the_log_backend_stores_fake_ids_and_calls_nothing(self, internal, settings, mocker):
        settings.WHATSAPP_SEND_BACKEND = "LOG"
        post = mocker.patch("apps.whatsapp.client.requests.post")

        publish()

        post.assert_not_called()
        assert all(flow.flow_id.startswith("log-") for flow in WhatsAppFlow.objects.all())
        assert WhatsAppFlow.objects.count() == len(SCREEN_NAMES)

    def test_without_an_internal_number_it_says_where_to_connect_one(self, settings):
        settings.WHATSAPP_SEND_BACKEND = "LOG"

        output = publish()

        # The website's WhatsApp page, in the sidebar since Step 1.19.
        assert "WhatsApp page" in output
        assert not WhatsAppFlow.objects.exists()


class TestOnConnecting:
    def test_the_handler_queues_publishing_for_the_new_number(self, internal, mocker):
        delay = mocker.patch.object(tasks.publish_forms, "delay")

        registry.handler_for(AccountPurpose.INTERNAL_COMMUNICATIONS).on_connected(internal)

        delay.assert_called_once_with(str(internal.pk))

    def test_the_task_publishes_the_forms_to_that_number(self, internal, settings):
        settings.WHATSAPP_SEND_BACKEND = "LOG"

        tasks.publish_forms(str(internal.pk))

        assert {flow.name for flow in WhatsAppFlow.objects.filter(waba_id=internal.waba_id)} == set(SCREEN_NAMES)

    def test_a_number_disconnected_before_the_task_ran_gets_nothing(self, internal, settings):
        settings.WHATSAPP_SEND_BACKEND = "LOG"
        internal.is_active = False
        internal.save()

        tasks.publish_forms(str(internal.pk))

        assert not WhatsAppFlow.objects.exists()


class TestANumberServingBoth:
    """One number for the team and the customers (plan Step 2.7) is the team's number, so it gets the forms."""

    @pytest.fixture
    def shared(self):
        return InternalAccountFactory(
            waba_id="200000000000009", purpose=AccountPurpose.INTERNAL_AND_EXTERNAL_COMMUNICATIONS
        )

    def test_the_command_publishes_to_it(self, shared, settings):
        settings.WHATSAPP_SEND_BACKEND = "LOG"

        publish()

        assert {flow.name for flow in WhatsAppFlow.objects.filter(waba_id="200000000000009")} == set(SCREEN_NAMES)

    def test_the_task_publishes_to_it(self, shared, settings):
        settings.WHATSAPP_SEND_BACKEND = "LOG"

        tasks.publish_forms(str(shared.pk))

        assert WhatsAppFlow.objects.filter(waba_id="200000000000009").count() == len(SCREEN_NAMES)
