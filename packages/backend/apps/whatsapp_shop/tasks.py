"""
Celery tasks for the WhatsApp app for an organization's store customers.
"""

import logging

from config.celery import app as celery_app

logger = logging.getLogger(__name__)


@celery_app.task
def publish_order_templates(account_id: str) -> None:
    """
    Submit the order templates (templates.py, plan phase 4, Step 4.3d-2) to a number newly serving
    customers. Queued by the store handler's on_connected once the number is saved, since Meta's calls
    take a while. A number disconnected, or no longer serving customers, since is skipped.
    """
    from apps.whatsapp.client import SendError
    from apps.whatsapp.models import WhatsAppAccount

    from .templates import CUSTOMER_PURPOSES, publish_order_templates as publish

    account = WhatsAppAccount.objects.filter(pk=account_id, purpose__in=CUSTOMER_PURPOSES, is_active=True).first()
    if account is None:
        return
    try:
        publish(account)
    except SendError as error:
        # Late order updates fail until it's done; connecting the number again, or the command, tries again.
        logger.warning("WhatsApp account id=%s: submitting its order templates failed: %s", account_id, error)
