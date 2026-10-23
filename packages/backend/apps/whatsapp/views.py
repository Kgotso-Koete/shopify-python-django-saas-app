"""
The WhatsApp webhook, /api/whatsapp/webhook/ (plan Step 1.3c, decisions D6 and D7, Step 1.18).

Meta is neither logged in nor able to send a CSRF token, so the view is CSRF-exempt and public; its
authority is Meta's signature (agents.md section 3.5). Meta's rules for webhooks:
https://developers.facebook.com/docs/graph-api/webhooks/getting-started
- GET is the subscription check: answer hub.challenge only if hub.verify_token is our Meta app's.
- POST carries events, signed with X-Hub-Signature-256 (HMAC-SHA256 of the raw body) with our Meta
  app's App secret, whichever organization's number they're for.

The view stays thin: it checks the signature, normalizes the body, hands the events to
services.inbound, and queues the new messages. Nothing is stored before the signature passes.
Anything that can never succeed still gets a 200, because Meta retries everything else for days:
https://developers.facebook.com/documentation/business-messaging/whatsapp/webhooks/overview.md
"""

import hmac
import json
import logging
from functools import partial

from django.conf import settings
from django.db import transaction
from django.http import Http404, HttpResponse, HttpResponseBadRequest, HttpResponseForbidden, HttpResponseNotAllowed
from django.views.decorators.csrf import csrf_exempt

from .models import WhatsAppAccount
from .normalize import MalformedWebhook, normalize_webhook, receiving_phone_number_ids
from .services.inbound import store_events
from .tasks import process_inbound_message
from .verification import signature_is_valid

logger = logging.getLogger(__name__)


@csrf_exempt
def webhook_view(request):
    # A stray webhook must change nothing on a deployment that doesn't use WhatsApp.
    if not settings.WHATSAPP_ENABLED:
        raise Http404
    if request.method == "GET":
        return _subscription_check(request)
    if request.method == "POST":
        return _receive_events(request)
    return HttpResponseNotAllowed(["GET", "POST"])


def _subscription_check(request):
    """Meta's GET: echo hub.challenge, as plain text, only for our Meta app's verify token."""
    mode = request.GET.get("hub.mode")
    token = request.GET.get("hub.verify_token", "")
    challenge = request.GET.get("hub.challenge", "")
    ours = settings.WHATSAPP_VERIFY_TOKEN
    # Compared in constant time; an empty setting matches nothing.
    if mode != "subscribe" or not token or not ours:
        return HttpResponseForbidden()
    if not hmac.compare_digest(token.encode("utf-8"), ours.encode("utf-8")):
        return HttpResponseForbidden()
    return HttpResponse(challenge, content_type="text/plain")


def _receive_events(request):
    """Meta's POST: check the signature, then store and queue the events."""
    raw_body = request.body
    try:
        payload = json.loads(raw_body)
    except (ValueError, UnicodeDecodeError):
        return HttpResponseBadRequest("The body is not JSON.")

    secret = settings.WHATSAPP_APP_SECRET
    if not secret or not signature_is_valid(raw_body, request.META.get("HTTP_X_HUB_SIGNATURE_256"), secret):
        return HttpResponseForbidden()

    # Signed but unusable: acknowledged, because a retry would never get better.
    try:
        numbers = receiving_phone_number_ids(payload)
        events = normalize_webhook(payload)
    except MalformedWebhook as error:
        logger.warning("Signed WhatsApp webhook with a malformed body (%s); acknowledged.", error)
        return HttpResponse(status=200)

    # Only active accounts: a number that isn't connected here, or was disconnected (plan Step 1.5),
    # has nothing to store its events under, so they're acknowledged and dropped.
    active_accounts = WhatsAppAccount.objects.filter(phone_number_id__in=numbers, is_active=True)
    accounts_by_number = {account.phone_number_id: account for account in active_accounts}

    # Queue each new message once its row is committed, so the worker always finds it (D7).
    for message_id in store_events(events, accounts_by_number):
        transaction.on_commit(partial(process_inbound_message.delay, message_id))
    return HttpResponse(status=200)
