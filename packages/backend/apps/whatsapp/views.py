"""
The WhatsApp webhooks (plan Step 1.3c, decisions D6 and D7, Steps 1.18 and 2.9):
- /api/whatsapp/webhook/ for this service's own Meta app, whose verify token and App secret are the
  settings WHATSAPP_VERIFY_TOKEN and WHATSAPP_APP_SECRET
- /api/whatsapp/webhook/<public id>/ for each organization's own Meta app (Step 2.9), with the verify
  token and App secret stored with it; an address nobody was given is not found

Meta is neither logged in nor able to send a CSRF token, so the views are CSRF-exempt and public; their
authority is Meta's signature (agents.md section 3.5). Meta's rules for webhooks:
https://developers.facebook.com/docs/graph-api/webhooks/getting-started
- GET is the subscription check: answer hub.challenge only if hub.verify_token is the app's.
- POST carries events, signed with X-Hub-Signature-256 (HMAC-SHA256 of the raw body) with the App
  secret of the app the numbers are in, whichever organization's numbers they are.

Each address stores events only for the numbers on its app: a body signed by one app can't speak for a
number in another. The views stay thin: they check the signature, normalize the body, hand the events
to services.inbound, and queue the new messages. Nothing is stored before the signature passes.
Anything that can never succeed still gets a 200, because Meta retries everything else for days:
https://developers.facebook.com/documentation/business-messaging/whatsapp/webhooks/overview.md
"""

import hmac
import json
import logging
from dataclasses import dataclass
from functools import partial

from django.conf import settings
from django.db import transaction
from django.http import Http404, HttpResponse, HttpResponseBadRequest, HttpResponseForbidden, HttpResponseNotAllowed
from django.views.decorators.csrf import csrf_exempt

from .models import MetaApp, WhatsAppAccount
from .normalize import MalformedWebhook, normalize_webhook, receiving_phone_number_ids
from .services.inbound import store_events
from .tasks import process_inbound_message
from .verification import signature_is_valid

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class _App:
    """The Meta app an address receives for: its token, its secret, and how a log names its secret."""

    verify_token: str
    app_secret: str
    # None for this service's own app.
    meta_app: MetaApp | None
    signing_key_name: str
    mismatch_hint: str


def _our_app() -> _App:
    return _App(
        verify_token=settings.WHATSAPP_VERIFY_TOKEN,
        app_secret=settings.WHATSAPP_APP_SECRET,
        meta_app=None,
        signing_key_name="WHATSAPP_APP_SECRET",
        mismatch_hint="is it our Meta app's App secret?",
    )


def _organizations_app(meta_app: MetaApp) -> _App:
    return _App(
        verify_token=meta_app.verify_token,
        app_secret=meta_app.app_secret,
        meta_app=meta_app,
        # The App ID is no secret; it tells the operator which organization's app to look at.
        signing_key_name=f"the App secret registered for Meta app {meta_app.app_id}",
        mismatch_hint="was it reset in Meta's App Dashboard? It's updated on the organization's WhatsApp page",
    )


@csrf_exempt
def webhook_view(request):
    # A stray webhook must change nothing on a deployment that doesn't use WhatsApp.
    if not settings.WHATSAPP_ENABLED:
        raise Http404
    return _handle(request, _our_app())


@csrf_exempt
def app_webhook_view(request, public_id: str):
    if not settings.WHATSAPP_ENABLED:
        raise Http404
    meta_app = MetaApp.objects.filter(public_id=public_id).first()
    if meta_app is None:
        raise Http404
    return _handle(request, _organizations_app(meta_app))


def _handle(request, app: _App):
    if request.method == "GET":
        return _subscription_check(request, app)
    if request.method == "POST":
        return _receive_events(request, app)
    return HttpResponseNotAllowed(["GET", "POST"])


def _subscription_check(request, app: _App):
    """Meta's GET: echo hub.challenge, as plain text, only for the app's verify token."""
    mode = request.GET.get("hub.mode")
    token = request.GET.get("hub.verify_token", "")
    challenge = request.GET.get("hub.challenge", "")
    ours = app.verify_token
    # Compared in constant time; an empty setting matches nothing.
    if mode != "subscribe" or not token or not ours:
        return HttpResponseForbidden()
    if not hmac.compare_digest(token.encode("utf-8"), ours.encode("utf-8")):
        return HttpResponseForbidden()
    return HttpResponse(challenge, content_type="text/plain")


def _receive_events(request, app: _App):
    """Meta's POST: check the signature, then store and queue the events for the app's numbers."""
    raw_body = request.body
    try:
        payload = json.loads(raw_body)
    except (ValueError, UnicodeDecodeError):
        return HttpResponseBadRequest("The body is not JSON.")

    signature = request.META.get("HTTP_X_HUB_SIGNATURE_256")
    if not app.app_secret or not signature_is_valid(raw_body, signature, app.app_secret):
        # Step 1.22: say why, so a wrong App secret is found without guessing. Never the secret, the
        # signature or the body: the log shows only which check failed.
        logger.warning("WhatsApp webhook refused with 403: %s.", _refusal_reason(app, signature))
        return HttpResponseForbidden()

    # Signed but unusable: acknowledged, because a retry would never get better.
    try:
        numbers = receiving_phone_number_ids(payload)
        events = normalize_webhook(payload)
    except MalformedWebhook as error:
        logger.warning("Signed WhatsApp webhook with a malformed body (%s); acknowledged.", error)
        return HttpResponse(status=200)

    # Only the app's own active numbers: a number that isn't connected here, was disconnected (plan
    # Step 1.5), or is in another app has nothing this body may store under, so its events are
    # acknowledged and dropped.
    active_accounts = WhatsAppAccount.objects.filter(phone_number_id__in=numbers, is_active=True, meta_app=app.meta_app)
    accounts_by_number = {account.phone_number_id: account for account in active_accounts}

    # Queue each new message once its row is committed, so the worker always finds it (D7).
    for message_id in store_events(events, accounts_by_number):
        transaction.on_commit(partial(process_inbound_message.delay, message_id))
    return HttpResponse(status=200)


def _refusal_reason(app: _App, signature: str | None) -> str:
    """Which of the signature checks a refused POST failed, in words for the log."""
    if not app.app_secret:
        return f"{app.signing_key_name} is empty, so no signature can be checked"
    if not signature:
        return "the request has no X-Hub-Signature-256 header"
    return f"its X-Hub-Signature-256 signature doesn't match {app.signing_key_name} ({app.mismatch_hint})"
