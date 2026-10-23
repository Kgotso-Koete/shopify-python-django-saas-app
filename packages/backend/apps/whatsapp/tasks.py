"""
Celery tasks for the WhatsApp app.

The webhook only verifies, stores and queues (plan decision D7); the slow work of deciding what to
reply happens here, in the worker.
"""

import logging

from config.celery import app as celery_app

logger = logging.getLogger(__name__)


@celery_app.task
def process_inbound_message(message_id: int) -> None:
    """
    Handle one stored inbound message. Queued by the webhook once the message's row is committed.

    The router (services/router.py) picks the reply: menus, Flows or the AI assistant. A message
    that no longer exists, or was already answered, is skipped there.
    """
    from apps.whatsapp.services import router

    router.route(message_id)


# max_retries=None: the limit is outbox.MAX_SEND_RETRIES, checked below, so that after the last
# retry the queue is closed off cleanly (give_up) instead of Celery raising MaxRetriesExceededError.
@celery_app.task(bind=True, max_retries=None)
def send_queued_messages(self, contact_id: int) -> None:
    """
    Send one contact's queued replies, in order (plan D21). Queued on commit whenever replies are
    queued, and in strict mode whenever Meta reports a status on one of the contact's messages.

    A passing failure is retried with a growing delay. The retry sends the same stored row, so the
    work that produced the reply never runs again.
    """
    from django.conf import settings

    from apps.whatsapp.client import RetryableSendError
    from apps.whatsapp.services import outbox

    try:
        outbox.drain(contact_id)
    except RetryableSendError as error:
        if settings.CELERY_TASK_ALWAYS_EAGER:
            # No worker: Celery would run the retry at once, ignoring its countdown. Leave the message
            # queued for the whatsapp_send_queued command, run from cron, which gives the wait (Step 1.4d).
            logger.warning("WhatsApp contact id=%s: sending failed for now; left queued (no worker).", contact_id)
            return
        if self.request.retries >= outbox.MAX_SEND_RETRIES:
            logger.warning("WhatsApp contact id=%s: sending failed after every retry; giving up.", contact_id)
            outbox.give_up(contact_id, error)
            return
        raise self.retry(exc=error, countdown=outbox.retry_delay(self.request.retries))
