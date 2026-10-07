import logging
from urllib.parse import urlencode

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.signing import TimestampSigner
from django.http import HttpResponseBadRequest, HttpResponseRedirect, Http404
from django_ratelimit.decorators import ratelimit
from graphql_relay import to_global_id

from apps.shopify.models import ShopifyShop
from apps.shopify.verification import is_valid_shop_domain, verify_query_hmac
from apps.shopify.services import start_install, complete_install


logger = logging.getLogger(__name__)


def _redirect_to_shops_list(shop):
    # The web app's shops list lives under /:tenantId/, keyed by the tenant's GraphQL id
    # (as TenantType resolves it). Without it, the web app reads "shopify" as the tenant id.
    tenant_path = to_global_id("TenantType", shop.tenant.id)
    return HttpResponseRedirect(f"{settings.WEB_APP_URL}/{tenant_path}/shopify?connected={shop.shop_domain}")


@ratelimit(key="ip", rate="30/m", block=True)
def install_view(request):
    if not settings.SHOPIFY_ENABLED:
        raise Http404("Shopify integration is disabled.")

    shop_domain = request.GET.get("shop")
    if not shop_domain or not is_valid_shop_domain(shop_domain):
        return HttpResponseBadRequest("Missing or invalid 'shop' parameter.")

    try:
        if not verify_query_hmac(request.GET.dict(), settings.SHOPIFY_API_SECRET):
            logger.warning("HMAC verification returned False for install_view.")
            return HttpResponseBadRequest("HMAC verification failed.")
    except Exception as e:
        logger.warning(f"HMAC verification failed for install_view: {e}")
        return HttpResponseBadRequest("HMAC verification failed.")

    shop = ShopifyShop.objects.filter(shop_domain=shop_domain).first()

    # If the shop is already installed, active, and has a token, we don't need to re-authorize.
    if shop and shop.access_token and not shop.needs_reinstall and not shop.uninstalled_at:
        if shop.tenant_id:
            return _redirect_to_shops_list(shop)
        else:
            signer = TimestampSigner()
            claim = signer.sign(str(shop.id))
            qs = urlencode({"claim": claim})
            return HttpResponseRedirect(f"{settings.WEB_APP_URL}/shopify/link?{qs}")

    # Not installed or needs reinstall, start the OAuth flow.
    authorize_url = start_install(shop_domain)
    return HttpResponseRedirect(authorize_url)


@ratelimit(key="ip", rate="30/m", block=True)
def callback_view(request):
    if not settings.SHOPIFY_ENABLED:
        raise Http404("Shopify integration is disabled.")

    shop_domain = request.GET.get("shop")
    code = request.GET.get("code")
    state_nonce = request.GET.get("state")

    if not shop_domain or not is_valid_shop_domain(shop_domain):
        return HttpResponseBadRequest("Missing or invalid 'shop' parameter.")

    try:
        if not verify_query_hmac(request.GET.dict(), settings.SHOPIFY_API_SECRET):
            logger.warning("HMAC verification returned False for callback_view.")
            return HttpResponseBadRequest("HMAC verification failed.")
    except Exception as e:
        logger.warning(f"HMAC verification failed for callback_view: {e}")
        return HttpResponseBadRequest("HMAC verification failed.")

    if not code or not state_nonce:
        return HttpResponseBadRequest("Missing 'code' or 'state' parameters.")

    try:
        shop = complete_install(shop_domain, code, state_nonce)
    except ValidationError as e:
        logger.warning(f"Failed to complete install: {e}")
        return HttpResponseBadRequest(str(e.message) if hasattr(e, "message") else str(e))

    if shop.tenant_id:
        return _redirect_to_shops_list(shop)
    else:
        signer = TimestampSigner()
        claim = signer.sign(str(shop.id))
        qs = urlencode({"claim": claim})
        return HttpResponseRedirect(f"{settings.WEB_APP_URL}/shopify/link?{qs}")
