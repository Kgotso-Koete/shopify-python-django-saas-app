"""
Celery tasks for the WhatsApp app for an organization's team.
"""

import logging

from config.celery import app as celery_app

logger = logging.getLogger(__name__)


@celery_app.task
def publish_forms(account_id: str) -> None:
    """
    Publish the forms to a number newly serving the team: internal (plan Step 1.17), or serving both
    (Step 2.7). Queued by the handler's on_connected once the number is saved. A number disconnected,
    or no longer serving the team, since is skipped.
    """
    from apps.whatsapp.client import SendError
    from apps.whatsapp.constants import TEAM_PURPOSES
    from apps.whatsapp.models import WhatsAppAccount

    from .publishing import publish_forms as publish

    account = WhatsAppAccount.objects.filter(pk=account_id, purpose__in=TEAM_PURPOSES, is_active=True).first()
    if account is None:
        return
    try:
        publish(account)
    except SendError as error:
        # The menus say the forms aren't set up, and connecting the number again tries again.
        logger.warning("WhatsApp account id=%s: publishing its forms failed: %s", account_id, error)
