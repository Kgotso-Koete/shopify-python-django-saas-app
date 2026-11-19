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


@celery_app.task
def publish_link_template(account_id: str) -> None:
    """
    Submit the link code template (services/identity.py, phase 7, user story WA.D1.OM.J1.A3) to a team number,
    queued when one connects while PHONE_VERIFICATION_CHANNEL is WHATSAPP_TEMPLATE. A number disconnected, or
    no longer the team's, since is skipped; Meta refusing is logged (and the operator emailed, by submit).
    """
    from apps.whatsapp.client import SendError
    from apps.whatsapp.constants import TEAM_PURPOSES
    from apps.whatsapp.models import WhatsAppAccount
    from apps.whatsapp.services import identity

    account = WhatsAppAccount.objects.filter(pk=account_id, purpose__in=TEAM_PURPOSES, is_active=True).first()
    if account is None:
        return
    try:
        identity.publish_link_template(account)
    except SendError as error:
        logger.warning("WhatsApp account id=%s: submitting its link code template failed: %s", account_id, error)


@celery_app.task
def check_template_statuses() -> dict:
    """
    Ask Meta for the review status of every active number's message templates (plan Step 4.7, user story
    WA.D3.OM.J2.A2), once a day from beat. Without a worker, the whatsapp_check_template_statuses command
    does the same from cron (agents.md section 4.1). Returns how many numbers were checked and how many
    Meta refused.
    """
    from apps.whatsapp.services import templates

    result = templates.check_all()
    return {"checked": result["checked"], "failed": len(result["failed"])}


# max_retries=None: the limit is the message's age, outbox.QUEUED_MESSAGE_MAX_AGE_SECONDS, checked below,
# so that the queue is closed off cleanly (give_up) instead of Celery raising MaxRetriesExceededError.
@celery_app.task(bind=True, max_retries=None)
def send_queued_messages(self, contact_id: int) -> None:
    """
    Send one contact's queued replies, in order (plan D21). Queued on commit whenever replies are
    queued, and in strict mode whenever Meta reports a status on one of the contact's messages.

    A passing failure is retried with a growing delay until the message has been queued for an hour
    (Step 4.7, user story WA.D5.SY.J1.A1), the same limit the send sweep has without a worker. The retry
    sends the same stored row, so the work that produced the reply never runs again.
    """
    from django.conf import settings

    from apps.whatsapp.client import RetryableSendError
    from apps.whatsapp.services import outbox

    try:
        outbox.drain(contact_id)
    except RetryableSendError as error:
        if settings.CELERY_TASK_ALWAYS_EAGER:
            # No worker: Celery would run the retry at once, ignoring its countdown. Leave the message
            # queued for the send sweep, which gives the wait: the whatsapp_send_queued command from cron
            # (Step 1.4d), or the next webhook (outbox.sweep_if_due, Step 4.7).
            logger.warning("WhatsApp contact id=%s: sending failed for now; left queued (no worker).", contact_id)
            return
        if outbox.waited_too_long(contact_id):
            logger.warning("WhatsApp contact id=%s: sending failed for an hour; giving up.", contact_id)
            outbox.give_up(contact_id, error)
            return
        raise self.retry(exc=error, countdown=outbox.retry_delay(self.request.retries))
