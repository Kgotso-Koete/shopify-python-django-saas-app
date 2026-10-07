import secrets
import datetime
from urllib.parse import urlencode

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from apps.shopify.models import ShopifyOAuthState, ShopifyShop
from apps.shopify.client import ShopifyAdminClient


def get_redirect_uri() -> str:
    return f"{settings.API_URL}/api/shopify/auth/callback/"


def start_install(shop_domain: str, tenant=None, user=None) -> str:
    """
    Start the Shopify OAuth flow.
    Creates a single-use state nonce and returns the Shopify authorize URL.
    Deletes any expired OAuth states to keep the table clean.
    """
    # Cleanup expired states
    expiration_cutoff = timezone.now() - datetime.timedelta(seconds=settings.SHOPIFY_AUTH_TIMEOUT)
    ShopifyOAuthState.objects.filter(created_at__lt=expiration_cutoff).delete()

    nonce = secrets.token_urlsafe(32)
    ShopifyOAuthState.objects.create(
        nonce=nonce,
        shop_domain=shop_domain,
        tenant=tenant,
        created_by=user,
    )

    params = {
        "client_id": settings.SHOPIFY_API_KEY,
        "scope": ",".join(settings.SHOPIFY_SCOPES),
        "redirect_uri": get_redirect_uri(),
        "state": nonce,
    }
    qs = urlencode(params)
    return f"https://{shop_domain}/admin/oauth/authorize?{qs}"


@transaction.atomic
def complete_install(shop_domain: str, code: str, state_nonce: str) -> ShopifyShop:
    """
    Complete the Shopify OAuth flow.
    Consumes the state nonce, exchanges the code for tokens, checks granted scopes,
    and creates or updates the ShopifyShop record.
    """
    # 1. Consume state (must exist, unexpired, same shop)
    # Using select_for_update to avoid race conditions on the nonce
    try:
        state = ShopifyOAuthState.objects.select_for_update().get(nonce=state_nonce)
    except ShopifyOAuthState.DoesNotExist:
        raise ValidationError("Invalid or already consumed state nonce.")

    if state.shop_domain != shop_domain:
        raise ValidationError("State nonce does not match the shop domain.")

    age = (timezone.now() - state.created_at).total_seconds()
    if age > settings.SHOPIFY_AUTH_TIMEOUT:
        # Don't bother deleting here — this whole block is @transaction.atomic
        # so the delete would be rolled back by the ValidationError anyway.
        # Expired states are cleaned up by start_install() periodically.
        raise ValidationError("State nonce has expired.")

    # We hold the data, delete the state
    tenant = state.tenant
    state.delete()

    # 2. Exchange code for access token
    client = ShopifyAdminClient(shop_domain=shop_domain)
    token_response = client.exchange_code(code)

    # 3. Confirm granted scopes
    granted_scopes = set(token_response.scope.split(","))
    required_scopes = set(settings.SHOPIFY_SCOPES)
    if not required_scopes.issubset(granted_scopes):
        raise ValidationError(
            f"Merchant did not grant all required scopes. Missing: {required_scopes - granted_scopes}"
        )

    # 4. Upsert ShopifyShop
    shop, created = ShopifyShop.objects.get_or_create(
        shop_domain=shop_domain, defaults={"installed_at": timezone.now()}
    )

    shop.access_token = token_response.access_token
    shop.refresh_token = token_response.refresh_token
    shop.access_token_expires_at = timezone.now() + datetime.timedelta(seconds=token_response.expires_in)
    shop.refresh_token_expires_at = timezone.now() + datetime.timedelta(seconds=token_response.refresh_token_expires_in)
    shop.scopes = token_response.scope
    shop.installed_at = shop.installed_at or timezone.now()
    shop.uninstalled_at = None
    shop.needs_reinstall = False

    # If it was a web-app started install (has tenant in state), link it immediately.
    # If the shop already had a tenant, we keep it (reinstall case), unless state dictates a new one.
    if tenant:
        shop.tenant = tenant

    shop.save()
    return shop


# ---------------------------------------------------------------------------
# Webhook handlers (called from webhooks.py, either sync or via Celery task)
# ---------------------------------------------------------------------------


def handle_uninstalled(shop_domain: str, payload: dict) -> None:
    """
    app/uninstalled: wipe tokens and set uninstalled_at, but keep the tenant link
    so a reinstall reconnects the store automatically (plan section 2.8, decision D4).
    """
    try:
        shop = ShopifyShop.objects.get(shop_domain=shop_domain)
    except ShopifyShop.DoesNotExist:
        return

    shop.access_token = None
    shop.refresh_token = None
    shop.access_token_expires_at = None
    shop.refresh_token_expires_at = None
    shop.uninstalled_at = timezone.now()
    shop.save(
        update_fields=[
            "access_token_encrypted",
            "refresh_token_encrypted",
            "access_token_expires_at",
            "refresh_token_expires_at",
            "uninstalled_at",
        ]
    )


@transaction.atomic
def handle_shop_redact(shop_domain: str, payload: dict) -> None:
    """
    shop/redact (48 h after uninstall): anonymize the ShopifyShop row and redact
    all delivery payloads for that shop (tombstone approach, plan section 3.5).

    The row remains so we have a structural audit trail ("a redact happened for
    row N on date D") without keeping any personal or shop data.
    """
    from apps.shopify.models import ShopifyWebhookDelivery

    try:
        shop = ShopifyShop.objects.select_for_update().get(shop_domain=shop_domain)
    except ShopifyShop.DoesNotExist:
        return

    # Anonymize: replace the shop domain with a hash so the row stays as a tombstone
    import hashlib

    hashed_domain = hashlib.sha256(shop_domain.encode("utf-8")).hexdigest()[:32]
    shop.shop_domain = f"redacted-{hashed_domain}"
    shop.access_token = None
    shop.refresh_token = None
    shop.access_token_expires_at = None
    shop.refresh_token_expires_at = None
    shop.tenant = None
    shop.scopes = ""
    shop.save()

    # Redact all delivery payloads for the original shop domain (including the
    # redact delivery itself, which was already recorded by the webhook view).
    ShopifyWebhookDelivery.objects.filter(shop_domain=shop_domain).update(payload={})


def handle_customers_redact(shop_domain: str, payload: dict) -> None:
    """
    customers/redact: this slice stores no customer data, so we just record the
    request (the delivery row was already created by the webhook view).
    The first feature that stores customer data must make this handler real.
    """
    # Nothing to do yet — the delivery is already persisted for audit.


def handle_customers_data_request(shop_domain: str, payload: dict) -> None:
    """
    customers/data_request: this slice stores no customer data, so we just record
    the request (the delivery row was already created by the webhook view).
    The first feature that stores customer data must make this handler real.
    """
    # Nothing to do yet — the delivery is already persisted for audit.
