"""
Tests for sending a file, such as an invoice's PDF, as a WhatsApp document (WhatsApp plan phase 4, Step
4.5b, D15): the file is uploaded to Meta's media endpoint, never shared as a link, and the message names
the uploaded media.

- document_message builds Meta's document message, its caption fitted to Meta's limit
  (https://developers.facebook.com/documentation/business-messaging/whatsapp/messages/document-messages.md)
- the client uploads a file with POST /<PHONE_NUMBER_ID>/media and returns Meta's media id
  (https://developers.facebook.com/docs/whatsapp/cloud-api/reference/media); the log backend uploads
  nothing and returns a fake id that can't be mistaken for Meta's
- the send queue stores a document as an outbound DOCUMENT message

Kind of test: integration (agents.md section 2.5). Why: numbers, contacts and queued messages are rows in
the test database; Meta's HTTP is mocked.
"""

import pytest

from ..builders import DOCUMENT_CAPTION_MAX, document_message
from ..client import LogSendBackend, MetaSendBackend, WhatsAppClient
from ..constants import MessageDirection, MessageKind, MessageStatus
from ..services.outbox import queue_messages
from .factories import ContactFactory, ExternalAccountFactory
from .fakes import meta_response

pytestmark = pytest.mark.django_db

PDF = b"%PDF-1.3 an invoice"


@pytest.fixture(autouse=True)
def graph_api_version(settings, mocker):
    settings.WHATSAPP_GRAPH_API_VERSION = "v26.0"
    mocker.patch("apps.whatsapp.tasks.send_queued_messages.delay")


class TestTheMessage:
    def test_it_names_the_uploaded_media_with_a_filename_and_caption(self):
        assert document_message(
            "1013859600285441", filename="INV-2026-000001.pdf", caption="Invoice INV-2026-000001"
        ) == {
            "type": "document",
            "document": {
                "id": "1013859600285441",
                "filename": "INV-2026-000001.pdf",
                "caption": "Invoice INV-2026-000001",
            },
        }

    def test_a_long_caption_is_cut_to_metas_limit(self):
        message = document_message("1", filename="a.pdf", caption="x" * (DOCUMENT_CAPTION_MAX + 10))

        assert len(message["document"]["caption"]) == DOCUMENT_CAPTION_MAX


class TestUploading:
    def test_the_client_uploads_the_file_to_the_numbers_media_endpoint(self, mocker):
        account = ExternalAccountFactory(phone_number_id="100000000000777", access_token="EAAG-token")
        post = mocker.patch(
            "apps.whatsapp.client.requests.post", return_value=meta_response(200, {"id": "1013859600285441"})
        )

        media_id = WhatsAppClient(account).upload_media(
            PDF, filename="INV-2026-000001.pdf", mime_type="application/pdf"
        )

        assert media_id == "1013859600285441"
        [call] = post.call_args_list
        assert call.args[0] == "https://graph.facebook.com/v26.0/100000000000777/media"
        assert call.kwargs["data"] == {"messaging_product": "whatsapp", "type": "application/pdf"}
        assert call.kwargs["files"] == {"file": ("INV-2026-000001.pdf", PDF, "application/pdf")}
        # Multipart, so requests sets the Content-Type itself; only the token goes in a header.
        assert call.kwargs["headers"] == {"Authorization": "Bearer EAAG-token"}

    def test_the_meta_backend_uploads_through_the_client(self, mocker):
        account = ExternalAccountFactory()
        mocker.patch("apps.whatsapp.client.requests.post", return_value=meta_response(200, {"id": "42"}))

        assert MetaSendBackend().upload_media(account, PDF, filename="a.pdf", mime_type="application/pdf") == "42"

    def test_the_log_backend_uploads_nothing_and_returns_a_fake_id(self, mocker):
        post = mocker.patch("apps.whatsapp.client.requests.post")

        media_id = LogSendBackend().upload_media(
            ExternalAccountFactory(), PDF, filename="a.pdf", mime_type="application/pdf"
        )

        assert media_id.startswith("log.")
        post.assert_not_called()


def test_the_queue_stores_a_document_as_an_outbound_document_message():
    contact = ContactFactory()
    message = document_message("42", filename="a.pdf", caption="An invoice")

    [row] = queue_messages(contact, [message])

    assert (row.direction, row.kind, row.status, row.payload) == (
        MessageDirection.OUTBOUND,
        MessageKind.DOCUMENT,
        MessageStatus.QUEUED,
        message,
    )
