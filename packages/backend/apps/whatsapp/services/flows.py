"""
WhatsApp Flows: forms sent pre-filled, whose answers come back in the webhook (plan Step 1.11,
decision D9).

Publishing (Step 1.11a): a form's JSON is published once per WhatsApp Business account and its id
kept in WhatsAppFlow with a hash of the JSON, so nothing is published again until the file changes.
With the log send backend nothing reaches Meta, and a fake id is stored so the menus still work.

Opening and answering (Step 1.11b): what a form is for (its kind, and context such as the item being
edited) stays on the server, in the contact's conversation. The flow_token Meta carries is only a
signed reference to it, which expires with the conversation's menus, works for that conversation
alone, and is answered once. A conversation holds one open form: opening another replaces it.

Meta's references:
https://developers.facebook.com/docs/whatsapp/flows/reference/flowsapi
https://developers.facebook.com/docs/whatsapp/flows/guides/sendingaflow
"""

import hashlib
import secrets

from django.conf import settings
from django.core import signing
from django.utils import timezone

from ..builders import flow_message
from ..client import WhatsAppClient
from ..constants import SendBackend
from ..models import WhatsAppFlow

TOKEN_SALT = "apps.whatsapp.flows.form"


class FormNotAvailable(Exception):
    """The form isn't published on this number's WhatsApp Business account (whatsapp_publish_flows)."""


class FormExpired(Exception):
    """A form's answers that can't be used: expired, answered already, tampered, or not this contact's."""


def publish(account, name: str, flow_json: str) -> tuple[WhatsAppFlow, bool]:
    """
    Publish the form `name` from `flow_json` on the account's WhatsApp Business account, unless the
    same JSON is published already. Returns the stored flow and whether it was published now.
    """
    digest = hashlib.sha256(flow_json.encode("utf-8")).hexdigest()
    existing = WhatsAppFlow.objects.filter(waba_id=account.waba_id, name=name).first()
    if existing is not None and existing.json_sha256 == digest:
        return existing, False

    # Meta may refuse a name it has seen on the account, so each version gets its own.
    meta_name = f"{name}-{digest[:8]}"
    if settings.WHATSAPP_SEND_BACKEND == SendBackend.META:
        flow_id = WhatsAppClient(account).create_flow(meta_name, flow_json)
    else:
        flow_id = f"log-{meta_name}"

    flow, _ = WhatsAppFlow.objects.update_or_create(
        waba_id=account.waba_id,
        name=name,
        defaults={"flow_id": flow_id, "json_sha256": digest, "published_at": timezone.now()},
    )
    return flow, True


def flow_id_for(account, name: str) -> str | None:
    """The published id of the form `name` on the account's WhatsApp Business account, if any."""
    return WhatsAppFlow.objects.filter(waba_id=account.waba_id, name=name).values_list("flow_id", flat=True).first()


def open_form(turn, *, form: str, screen: str, data: dict, body: str, cta: str, kind: str, context: dict) -> list[dict]:
    """
    The message that opens the published form `form` on `screen`, pre-filled with `data`. Its
    answers come back to read_answers with `kind` and `context`, which never leave the server.
    """
    flow_id = flow_id_for(turn.contact.account, form)
    if flow_id is None:
        raise FormNotAvailable(form)
    form_id = secrets.token_urlsafe(8)
    turn.conversation.state["forms"] = {form_id: {"kind": kind, "context": context}}
    token = signing.dumps({"conversation": turn.conversation.pk, "form": form_id}, salt=TOKEN_SALT)
    return [flow_message(body, flow_id=flow_id, flow_token=token, cta=cta, screen=screen, data=data)]


def read_answers(turn, response: dict) -> tuple[str, dict, dict]:
    """
    A completed form's (kind, context, answers), from an nfm_reply's response_json. The form is
    used up: a second answer, like any other unusable one, raises FormExpired.
    """
    answers = dict(response)
    token = str(answers.pop("flow_token", ""))
    try:
        reference = signing.loads(token, salt=TOKEN_SALT, max_age=settings.WHATSAPP_CONVERSATION_TTL_SECONDS)
    except signing.BadSignature:
        # SignatureExpired is a BadSignature too.
        raise FormExpired() from None
    if reference.get("conversation") != turn.conversation.pk:
        raise FormExpired()
    pending = turn.conversation.state.get("forms", {}).pop(reference.get("form"), None)
    if pending is None:
        raise FormExpired()
    return pending["kind"], pending["context"], answers
