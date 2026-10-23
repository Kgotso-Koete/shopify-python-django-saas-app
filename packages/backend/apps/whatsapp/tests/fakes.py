"""
Test doubles shared by the WhatsApp tests (test-support code, agents.md section 2.1).
"""

import threading
from contextlib import contextmanager
from unittest.mock import Mock

from django.db import connection, transaction

from ..constants import MessageStatus
from ..services import outbox


@contextmanager
def another_sender_holds_the_send_lock(contact_id: int):
    """
    While inside, a second database connection (a thread, standing in for another worker) holds the
    contact's send lock: the Postgres advisory lock services/outbox.py takes. An advisory lock needs
    no rows the other connection can see, so this works inside the normal test transaction.
    """
    locked = threading.Event()
    release = threading.Event()

    def hold_the_lock():
        # A thread gets its own database connection.
        try:
            with transaction.atomic():
                with connection.cursor() as cursor:
                    cursor.execute("SELECT pg_advisory_xact_lock(%s, %s)", [outbox.SEND_LOCK_NAMESPACE, contact_id])
                locked.set()
                release.wait(timeout=10)
        finally:
            connection.close()

    thread = threading.Thread(target=hold_the_lock)
    thread.start()
    if not locked.wait(timeout=10):
        raise RuntimeError("The second connection never took the send lock.")
    try:
        yield
    finally:
        release.set()
        thread.join(timeout=10)


def meta_response(status: int, body: dict) -> Mock:
    """A requests response from Meta with this status and JSON body."""
    response = Mock(status_code=status, ok=status < 400)
    response.json.return_value = body
    return response


def meta_error(code: int, status: int = 400) -> Mock:
    """
    Meta's error shape (error.message, type, code, error_data.details, fbtrace_id):
    https://developers.facebook.com/documentation/business-messaging/whatsapp/support/error-codes
    """
    return meta_response(
        status,
        {
            "error": {
                "message": f"(#{code}) Something went wrong",
                "type": "OAuthException",
                "code": code,
                "error_data": {"messaging_product": "whatsapp", "details": "Details from Meta"},
                "fbtrace_id": "AbCdEf123",
            }
        },
    )


class FakeBackend:
    """
    Stands in for the send backend (client.py's LogSendBackend or MetaSendBackend). It records each
    message it's given, answers like Meta with a new id, and raises the errors it's told to, in turn.
    Like Meta, one instance never hands out the same id twice, so reuse it across drains in a test.
    """

    def __init__(self, failures=(), status_after_send=MessageStatus.ACCEPTED):
        # One entry per send attempt: an exception to raise, or None to succeed; then always succeed.
        self.failures = list(failures)
        # What a successful send leaves the row as: Meta's backend leaves it `accepted`, waiting for
        # Meta's `sent` status by webhook; the log backend has no webhook, so it says `sent` at once.
        self.status_after_send = status_after_send
        self.sent = []
        self.attempts = 0
        # Called with (contact, message) before each send, so a test can look at the database then.
        self.before_send = None

    def send(self, contact, message):
        self.attempts += 1
        if self.before_send is not None:
            self.before_send(contact, message)
        if self.failures:
            failure = self.failures.pop(0)
            if failure is not None:
                raise failure
        self.sent.append(message)
        return f"wamid.OUT{len(self.sent):04d}"
