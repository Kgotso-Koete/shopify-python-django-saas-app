"""
The ITN endpoint PayFast posts payment notifications to (PAYFAST_NOTIFY_URL, /api/payfast/notify/).

PayFast is neither logged in nor able to send a CSRF token, so the view is CSRF-exempt and public;
the ITN security checks in apps.payfast.itn take the place of both.
"""

import logging

from django.conf import settings
from django.http import Http404, HttpResponse, HttpResponseBadRequest
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from . import itn, services

logger = logging.getLogger(__name__)


@csrf_exempt
@require_POST
def itn_view(request):
    # A stray ITN must not change anything in a deployment that doesn't use PayFast.
    if settings.PAYMENT_BACKEND != settings.PAYMENT_BACKEND_PAYFAST:
        raise Http404

    try:
        pairs = itn.verify_itn(request)
        outcome = services.process_itn(dict(pairs))
    except itn.ItnRejected as rejection:
        # Anything but a 200 makes PayFast retry (immediately, after 10 minutes, then with backoff),
        # which is right for a transient failure such as the validate call timing out.
        logger.warning("Rejected PayFast ITN: %s", rejection)
        return HttpResponseBadRequest("Rejected")

    logger.info("PayFast ITN %s: %s", dict(pairs).get("pf_payment_id"), outcome)
    # "Return a header 200 to prevent further retries" (https://developers.payfast.co.za/docs#step_4_confirm_payment).
    return HttpResponse("OK")
