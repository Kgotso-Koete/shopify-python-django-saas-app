"""
Verification of PayFast ITNs (Instant Transaction Notifications) before anything acts on them.

PayFast POSTs an ITN to PAYFAST_NOTIFY_URL for every completed payment (the first one and every
recurring charge) and when a subscription is cancelled. Anyone can POST to that URL, so an ITN is
only trusted after the checks PayFast's docs require
(https://developers.payfast.co.za/docs#step_4_confirm_payment):

1. signature   - the MD5 signature matches the posted fields and our passphrase;
2. source      - the request came from a PayFast server;
3. amount      - checked in services.process_itn, which knows the amount we expected;
4. server      - PayFast's /eng/query/validate endpoint answers "VALID" for the same data.

We also require the ITN's merchant_id to be ours.
"""

import logging
import socket

import requests
from django.conf import settings

from . import constants, signature

logger = logging.getLogger(__name__)

VALIDATE_TIMEOUT_SECONDS = 15


class ItnRejected(Exception):
    """The notification failed a security check and must not be acted on."""


def verify_itn(request) -> list:
    """
    Run the security checks on an ITN request and return its fields as ordered (key, value) pairs.
    Raises ItnRejected, with the failed check in the message, if any check fails.
    """
    pairs = signature.parse_itn_body(request.body)
    data = dict(pairs)

    # 1. Signature. Cheap and offline, so it runs first and filters out junk before any network call.
    if not signature.itn_signature_is_valid(pairs, settings.PAYFAST_PASSPHRASE):
        raise ItnRejected("invalid signature")

    if data.get("merchant_id") != settings.PAYFAST_MERCHANT_ID:
        raise ItnRejected(f"unexpected merchant_id {data.get('merchant_id')!r}")

    # 2. Source.
    if settings.PAYFAST_VERIFY_SOURCE_IP:
        ip = client_ip(request)
        if not source_is_payfast(ip):
            raise ItnRejected(f"source {ip} is not a PayFast server")

    # 4. Server confirmation, posted with the same parameter string the signature was computed over.
    if not confirm_with_payfast(signature.itn_param_string(pairs)):
        raise ItnRejected("PayFast did not confirm the notification")

    return pairs


def client_ip(request) -> str:
    """
    The IP the request came from. Behind Render or an AWS load balancer, REMOTE_ADDR is the proxy and
    the real client IP is the last entry the proxy appended to X-Forwarded-For; earlier entries were
    sent by the client itself and can be forged, so they're ignored.
    """
    forwarded_for = request.META.get("HTTP_X_FORWARDED_FOR", "")
    if forwarded_for:
        return forwarded_for.split(",")[-1].strip()
    return request.META.get("REMOTE_ADDR", "")


def resolve_payfast_hosts() -> set:
    """IP addresses currently behind PayFast's documented notification hosts (DNS errors are skipped)."""
    addresses = set()
    for host in constants.VALID_ITN_HOSTS:
        try:
            _, _, host_addresses = socket.gethostbyname_ex(host)
        except OSError:
            logger.warning("Could not resolve PayFast host %s", host)
            continue
        addresses.update(host_addresses)
    return addresses


def source_is_payfast(ip: str) -> bool:
    """True if `ip` is in PayFast's published ranges or resolves from one of its documented hosts."""
    return constants.is_published_payfast_ip(ip) or ip in resolve_payfast_hosts()


def confirm_with_payfast(param_string: str) -> bool:
    """Ask PayFast whether it really sent this notification. Any error counts as "no"."""
    try:
        response = requests.post(
            constants.validate_url(),
            data=param_string,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            timeout=VALIDATE_TIMEOUT_SECONDS,
        )
    except requests.RequestException as error:
        logger.warning("PayFast ITN validation request failed: %s", error)
        return False
    return response.text.strip() == "VALID"
