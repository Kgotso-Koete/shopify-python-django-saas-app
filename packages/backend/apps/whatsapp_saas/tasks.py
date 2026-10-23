"""
Celery tasks for the WhatsApp app for an organization's team.
"""

import logging

from config.celery import app as celery_app

logger = logging.getLogger(__name__)


@celery_app.task
def publish_forms(account_id: str) -> None:
    """
    Publish the forms to a newly connected internal communications number (plan Step 1.17). Queued
    by the handler's on_connected once the number is saved. A number disconnected since is skipped.
    """
    from apps.whatsapp.client import SendError
    from apps.whatsapp.constants import AccountPurpose
    from apps.whatsapp.models import WhatsAppAccount

    from .publishing import publish_forms as publish

    account = WhatsAppAccount.objects.filter(
        pk=account_id, purpose=AccountPurpose.INTERNAL_COMMUNICATIONS, is_active=True
    ).first()
    if account is None:
        return
    try:
        publish(account)
    except SendError as error:
        # The menus say the forms aren't set up, and connecting the number again tries again.
        logger.warning("WhatsApp account id=%s: publishing its forms failed: %s", account_id, error)
