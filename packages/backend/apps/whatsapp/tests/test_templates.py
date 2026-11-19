"""
Tests for message templates on a WhatsApp Business account (WhatsApp plan phase 4, Step 4.3d-2,
decisions 6 and 24): the channel's part, which any app's templates go through.

- submitting a template creates it on the account's WhatsApp Business account once, with a fixed name
- submitting the same content again does nothing; changed content edits the same template, since Meta
  lets an approved template be edited (unlike a published Flow), so templates don't pile up
- with the log send backend nothing reaches Meta, and a fake id is kept
- the client's create and edit calls, as Meta's Message Templates API takes them
- a template message, with its body's blanks and its URL button's suffix, queued like any other

Kind of test: integration (agents.md section 2.5). Why: the accounts, templates and queued messages are
rows in the test database; Meta is never called: `requests.post` is replaced by a fake whose answer is
canned, and the send task's `delay` is patched.
"""

import pytest
from django.test import override_settings

from apps.whatsapp.client import SendError
from apps.whatsapp.constants import MessageKind, SendBackend
from apps.whatsapp.services import outbox

from .factories import ContactFactory, ExternalAccountFactory

pytestmark = pytest.mark.django_db

COMPONENTS = [
    {"type": "BODY", "text": "Hello, this is {{1}}.", "example": {"body_text": [["Acme"]]}},
]
CHANGED = [
    {"type": "BODY", "text": "Hi, this is {{1}}.", "example": {"body_text": [["Acme"]]}},
]


def templates():
    # Imported here, not at the top, so a missing module fails each test instead of the whole file.
    from apps.whatsapp.services import templates

    return templates


def stored():
    from apps.whatsapp.models import WhatsAppTemplate

    return WhatsAppTemplate.objects


def submit(account, components=COMPONENTS):
    return templates().submit(account, "shop_test", category="UTILITY", language="en", components=components)


@pytest.fixture
def account():
    return ExternalAccountFactory()


@pytest.fixture
def meta(mocker, settings):
    """Meta's API, faked at requests.post: creating answers with an id, editing with success."""
    settings.WHATSAPP_SEND_BACKEND = SendBackend.META
    response = mocker.Mock(ok=True)
    response.json.return_value = {"id": "1234567890", "status": "PENDING", "category": "UTILITY", "success": True}
    return mocker.patch("apps.whatsapp.client.requests.post", return_value=response)


class TestSubmitting:
    def test_a_new_template_is_created_on_the_accounts_business_account(self, account, meta):
        template, changed = submit(account)

        assert changed
        assert template.waba_id == account.waba_id
        assert template.name == "shop_test"
        assert template.template_id == "1234567890"
        [call] = meta.call_args_list
        assert call.args[0].endswith(f"/{account.waba_id}/message_templates")
        assert call.kwargs["json"] == {
            "name": "shop_test",
            "category": "UTILITY",
            "language": "en",
            "components": COMPONENTS,
        }

    def test_the_same_content_again_does_nothing(self, account, meta):
        submit(account)

        template, changed = submit(account)

        assert not changed
        assert meta.call_count == 1

    def test_changed_content_edits_the_same_template(self, account, meta):
        submit(account)

        template, changed = submit(account, CHANGED)

        assert changed
        assert template.template_id == "1234567890"
        edit = meta.call_args_list[-1]
        assert edit.args[0].endswith("/1234567890")
        assert edit.kwargs["json"] == {"components": CHANGED}
        assert stored().filter(name="shop_test").count() == 1

    def test_each_business_account_gets_its_own(self, account, meta):
        other = ExternalAccountFactory()

        submit(account)
        submit(other)

        assert meta.call_count == 2

    @override_settings(WHATSAPP_SEND_BACKEND=SendBackend.LOG)
    def test_the_log_backend_reaches_nothing_and_keeps_a_fake_id(self, account, mocker):
        post = mocker.patch("apps.whatsapp.client.requests.post")

        template, changed = submit(account)

        assert changed
        assert template.template_id == "log-shop_test"
        post.assert_not_called()

    def test_a_fake_id_from_the_log_backend_is_submitted_for_real_on_meta(self, account, meta, settings):
        # Step 4.6: a developer submits on LOG, then switches to META. The fake id never reached Meta,
        # so the same content must be created there, not reported up to date.
        settings.WHATSAPP_SEND_BACKEND = SendBackend.LOG
        submit(account)
        settings.WHATSAPP_SEND_BACKEND = SendBackend.META

        template, changed = submit(account)

        assert changed
        assert template.template_id == "1234567890"
        [call] = meta.call_args_list
        assert call.args[0].endswith(f"/{account.waba_id}/message_templates")
        assert stored().filter(name="shop_test").count() == 1

    def test_changed_content_after_a_fake_id_is_created_not_edited(self, account, meta, settings):
        # There's no template on Meta to edit: editing "log-shop_test" would be refused.
        settings.WHATSAPP_SEND_BACKEND = SendBackend.LOG
        submit(account)
        settings.WHATSAPP_SEND_BACKEND = SendBackend.META

        template, changed = submit(account, CHANGED)

        assert changed
        assert template.template_id == "1234567890"
        [call] = meta.call_args_list
        assert call.args[0].endswith(f"/{account.waba_id}/message_templates")
        assert call.kwargs["json"]["components"] == CHANGED

    def test_meta_refusing_it_raises_and_keeps_nothing(self, account, meta):
        meta.return_value.ok = False
        meta.return_value.status_code = 400
        meta.return_value.json.return_value = {"error": {"code": 100, "message": "Invalid parameter"}}

        with pytest.raises(SendError):
            submit(account)

        assert not stored().exists()


class TestATemplateMessage:
    def test_it_carries_the_bodys_blanks_and_the_buttons_suffix(self):
        from apps.whatsapp.builders import template_message

        message = template_message("shop_test", language="en", body=["Acme", "#1001"], url_suffix="tok")

        assert message == {
            "type": "template",
            "template": {
                "name": "shop_test",
                "language": {"code": "en"},
                "components": [
                    {
                        "type": "body",
                        "parameters": [{"type": "text", "text": "Acme"}, {"type": "text", "text": "#1001"}],
                    },
                    {
                        "type": "button",
                        "sub_type": "url",
                        "index": "0",
                        "parameters": [{"type": "text", "text": "tok"}],
                    },
                ],
            },
        }

    def test_a_quick_reply_buttons_payload_comes_back_when_its_tapped(self):
        # WhatsApp plan Step 4.7 (decision 30): the payload is what Meta sends back when the customer taps it.
        # https://developers.facebook.com/docs/whatsapp/cloud-api/guides/send-message-templates
        from apps.whatsapp.builders import template_message

        message = template_message("shop_test", language="en", body=["Acme"], quick_reply_payload="order:abc")

        assert message["template"]["components"][1] == {
            "type": "button",
            "sub_type": "quick_reply",
            "index": "0",
            "parameters": [{"type": "payload", "payload": "order:abc"}],
        }

    def test_it_is_queued_as_a_template(self, mocker):
        from apps.whatsapp.builders import template_message

        mocker.patch("apps.whatsapp.tasks.send_queued_messages.delay")
        contact = ContactFactory()

        [row] = outbox.queue_messages(contact, [template_message("shop_test", language="en", body=["Acme"])])

        assert row.kind == MessageKind.TEMPLATE
