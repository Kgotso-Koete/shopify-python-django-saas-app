"""
Message templates on a WhatsApp Business account (plan phase 4, Step 4.3d-2, decisions 6 and 24): the
channel's part, which any app's templates go through, as flows.py is for forms.

- **Submitted once, under a fixed name:** a template is created on the account's WhatsApp Business
  account and kept in WhatsAppTemplate with a hash of what it was submitted with, so nothing is sent to
  Meta again until that changes.
- **A change edits the same template:** unlike a published Flow, an approved template can be edited, so
  templates don't pile up on the account with each change. Meta reviews the edit again, and allows one
  a day and 10 in 30 days; a refused edit raises, and the stored hash stays the old one, so the next
  try edits again.
- **With the log send backend** nothing reaches Meta, and a fake id is kept. It starts with `log-`, and
  on the meta backend a template holding one counts as never submitted, so switching from log to meta
  creates it on Meta rather than calling it up to date (plan Step 4.6).
- **Meta's review status is kept** (plan Step 4.7, user story WA.D3.OM.J2.A2, decided 2026-11-08): from
  Meta's answer when it's submitted, then by asking Meta (check_statuses) once a day (check_all, from the
  whatsapp_check_template_statuses command or the beat task) and when the WhatsApp page opens
  (check_if_stale). There's no webhook for it: each business connects its numbers through its own Meta app
  (Step 2.9), and a webhook would need every business to subscribe that app to one more field. The log
  backend's templates count as approved, since nothing is sent to Meta to review.
- **The operator is told** (user story WA.D7.OP.J2.A1) by email to OPERATOR_EMAILS: when Meta refuses a
  submission (submit), and once per rejection found by any check (report_rejections), naming the business,
  the number, the template and Meta's reason, since late order updates fail until it's fixed.

https://developers.facebook.com/docs/whatsapp/business-management-api/message-templates
"""

import hashlib
import json
import logging
from datetime import timedelta

from django.conf import settings
from django.db.models import Q
from django.utils import timezone

from ..client import SendError, WhatsAppClient
from ..constants import SendBackend, TemplateStatus
from ..emails import WhatsAppTemplatesRefusedEmail
from ..models import WhatsAppAccount, WhatsAppTemplate

logger = logging.getLogger(__name__)

# The start of the fake ids the log backend keeps; flows.py's fake Flow ids start the same way.
FAKE_ID_PREFIX = "log-"

# The WhatsApp page asks Meta again only when the last answer is older than this, so reloading the page
# doesn't call Meta each time.
CHECK_AGAIN_AFTER = timedelta(minutes=10)

# Meta's statuses in this app's names (agents.md section 5.3b). Any other, such as one Meta adds later,
# counts as DISABLED: it can't be sent.
STATUS_FROM_META = {
    "PENDING": TemplateStatus.IN_REVIEW,
    "IN_APPEAL": TemplateStatus.IN_REVIEW,
    "APPROVED": TemplateStatus.APPROVED,
    "REJECTED": TemplateStatus.REJECTED,
    "PAUSED": TemplateStatus.PAUSED,
    "DISABLED": TemplateStatus.DISABLED,
}


def submit(
    account, name: str, *, category: str, language: str, components: list[dict]
) -> tuple[WhatsAppTemplate, bool]:
    """
    Submit the template `name` to the account's WhatsApp Business account, or edit it there if it was
    submitted with other content, unless it was submitted with this content already. Returns the stored
    template and whether Meta was asked now. Raises a SendError when Meta refuses it.
    """
    content = {"category": category, "language": language, "components": components}
    digest = hashlib.sha256(json.dumps(content, sort_keys=True).encode("utf-8")).hexdigest()
    on_meta = _on_meta()
    existing = WhatsAppTemplate.objects.filter(waba_id=account.waba_id, name=name).first()
    if existing is not None and on_meta and existing.template_id.startswith(FAKE_ID_PREFIX):
        # Kept by the log backend, so Meta has never seen it: create it there, as if nothing were stored.
        existing = None
    if existing is not None and existing.content_sha256 == digest:
        return existing, False

    try:
        if not on_meta:
            template_id, status = f"{FAKE_ID_PREFIX}{name}", TemplateStatus.APPROVED
        elif existing is not None:
            WhatsAppClient(account).edit_template(existing.template_id, components=components)
            # Meta reviews an edit again.
            template_id, status = existing.template_id, TemplateStatus.IN_REVIEW
        else:
            answer = WhatsAppClient(account).create_template(
                name, category=category, language=language, components=components
            )
            template_id, status = answer["id"], _status_from(answer.get("status", "PENDING"))
    except SendError as error:
        # Late order updates fail until it's fixed, and fixing it is the operator's work (WA.D7.OP.J2.A1).
        _tell_the_operator([_problem(account, name, f"Meta refused the submission: {error}")])
        raise

    now = timezone.now()
    template, _ = WhatsAppTemplate.objects.update_or_create(
        waba_id=account.waba_id,
        name=name,
        defaults={
            "template_id": template_id,
            "content_sha256": digest,
            "submitted_at": now,
            "status": status,
            "rejected_reason": "",
            "status_checked_at": now,
            "reported_at": None,
        },
    )
    return template, True


def retire(account, name: str) -> None:
    """
    Stop keeping the template `name` on the account's WhatsApp Business account (WhatsApp plan Step 4.7,
    decision 30): delete it on Meta, then here, so it no longer shows on the WhatsApp page. One Meta refuses to
    delete (already gone, say) is forgotten here all the same; one only the log backend kept isn't asked about.
    """
    stored = WhatsAppTemplate.objects.filter(waba_id=account.waba_id, name=name).first()
    if stored is None:
        return
    if _on_meta() and not stored.template_id.startswith(FAKE_ID_PREFIX):
        try:
            WhatsAppClient(account).delete_template(name)
        except SendError as error:
            logger.warning("WhatsApp account id=%s: deleting template %s failed: %s", account.pk, name, error)
    stored.delete()


def check_statuses(account) -> list[WhatsAppTemplate]:
    """
    Ask Meta for the review status of each template stored for the account's WhatsApp Business account, and
    keep it, with Meta's reason for a rejection. Returns the templates whose status changed. Nothing is asked
    on the log backend, or about a template the log backend kept. Raises a SendError when Meta refuses, with
    the templates not asked yet keeping their last status. Then the operator is emailed, once, about each
    rejected template no email has named yet (report_rejections).
    """
    if not _on_meta():
        return []
    client = WhatsAppClient(account)
    changed = []
    for template in _submitted_to_meta(account):
        answer = client.get_template(template.template_id)
        status = _status_from(answer.get("status", ""))
        reason = answer.get("rejected_reason", "") if status == TemplateStatus.REJECTED else ""
        if (status, reason) != (template.status, template.rejected_reason):
            changed.append(template)
        template.status, template.rejected_reason, template.status_checked_at = status, reason, timezone.now()
        if status != TemplateStatus.REJECTED:
            # A later rejection is news again.
            template.reported_at = None
        template.save(update_fields=["status", "rejected_reason", "status_checked_at", "reported_at", "updated_at"])
    report_rejections(account)
    return changed


def report_rejections(account) -> None:
    """
    Email the operator, once, the templates of the account's business account that Meta rejected and no email
    has named yet (user story WA.D7.OP.J2.A1). With no OPERATOR_EMAILS nothing is sent and nothing is marked,
    so they're reported once an address is set.
    """
    if not settings.OPERATOR_EMAILS:
        return
    rejected = list(
        WhatsAppTemplate.objects.filter(
            waba_id=account.waba_id, status=TemplateStatus.REJECTED, reported_at__isnull=True
        ).order_by("name")
    )
    if not rejected:
        return
    _tell_the_operator(
        [_problem(account, template.name, f"Meta rejected it: {template.rejected_reason}") for template in rejected]
    )
    WhatsAppTemplate.objects.filter(pk__in=[template.pk for template in rejected]).update(reported_at=timezone.now())


def check_if_stale(account) -> None:
    """
    Check the account's templates with Meta when any was last checked longer ago than CHECK_AGAIN_AFTER, or
    never, for the WhatsApp page. A failure is logged, and the last statuses stay, so the page still opens.
    """
    stale = Q(status_checked_at__isnull=True) | Q(status_checked_at__lt=timezone.now() - CHECK_AGAIN_AFTER)
    if not _submitted_to_meta(account).filter(stale).exists():
        return
    try:
        check_statuses(account)
    except SendError as error:
        logger.warning("WhatsApp account id=%s: checking its templates' status failed: %s", account.pk, error)


def check_all() -> dict:
    """
    Check the templates of every active number with Meta, one number at a time, going on past any Meta
    refuses. Returns {"checked": <numbers checked>, "failed": {<number>: <error>}}. Run once a day by the
    whatsapp_check_template_statuses command (cron, no worker needed) and the beat task (agents.md section
    4.1). Numbers sharing a WhatsApp Business account are asked about once.
    """
    result = {"checked": 0, "failed": {}}
    seen_waba_ids = set()
    for account in WhatsAppAccount.objects.filter(is_active=True).order_by("created_at", "pk"):
        if account.waba_id in seen_waba_ids or not _submitted_to_meta(account).exists():
            continue
        seen_waba_ids.add(account.waba_id)
        try:
            check_statuses(account)
        except SendError as error:
            logger.warning("WhatsApp account id=%s: checking its templates' status failed: %s", account.pk, error)
            result["failed"][account] = error
        else:
            result["checked"] += 1
    return result


def _on_meta() -> bool:
    return settings.WHATSAPP_SEND_BACKEND == SendBackend.META


def _problem(account, template_name: str, reason: str) -> dict:
    """One line of the operator's email: whose number, which template, and what Meta said."""
    return {
        "organization": account.tenant.name,
        "number": account.display_phone_number,
        "template": template_name,
        "reason": reason,
    }


def _tell_the_operator(problems: list[dict]) -> None:
    """One email to OPERATOR_EMAILS listing the problems; none while no address is set."""
    if not settings.OPERATOR_EMAILS:
        return
    WhatsAppTemplatesRefusedEmail(to=list(settings.OPERATOR_EMAILS), data={"problems": problems}).send()


def _submitted_to_meta(account):
    """The account's business account's templates that reached Meta, so not the log backend's."""
    return (
        WhatsAppTemplate.objects.filter(waba_id=account.waba_id)
        .exclude(template_id__startswith=FAKE_ID_PREFIX)
        .order_by("name")
    )


def _status_from(metas: str) -> str:
    return STATUS_FROM_META.get(metas, TemplateStatus.DISABLED)
