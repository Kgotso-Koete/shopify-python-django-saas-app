"""
An organization's own Meta apps, registered on its WhatsApp page, and which app each of its numbers
is on (plan Step 2.9). The GraphQL API calls these after its permission checks.

The maintainer's decisions (plan Step 2.9, 2026-11-01):
1. an app belongs to one organization, and its App ID can be registered only once across the service
2. the app's webhook address id and verify token are generated here, never chosen by a person; the
   token can be regenerated
3. each app is registered once, on its own card, and the connect form picks one of them
4. removing an app is refused while a connected number uses it; its secret can be updated
5. a connected number's app can be changed without reconnecting

Nothing here calls Meta: a wrong App secret shows as that app's webhooks refused with 403, with the
reason logged (views.py).
"""

from django.conf import settings
from django.db import transaction
from django.urls import reverse

from ..models import MetaApp, WhatsAppAccount, new_verify_token
from .accounts import AccountError, find_account, find_app


def webhook_url(app: MetaApp) -> str:
    """The app's callback URL, to paste into its webhook settings in Meta's App Dashboard."""
    return f"{settings.API_URL}{reverse('whatsapp-app-webhook', args=[app.public_id])}"


def register_app(*, tenant, app_id: str, app_secret: str) -> MetaApp:
    """Register `tenant`'s own Meta app, giving it a webhook address and a verify token of its own."""
    app_id, app_secret = app_id.strip(), app_secret.strip()
    if not app_id:
        raise AccountError("App ID is required.", code="required", field="app_id")
    if not app_secret:
        raise AccountError("App secret is required.", code="required", field="app_secret")
    if not app_id.isdigit():
        # Meta's App IDs are numbers; anything else is most likely the secret in the wrong field.
        raise AccountError(
            "An App ID is digits only: copy it from the top of your app's page in Meta's App Dashboard.",
            code="invalid_app_id",
            field="app_id",
        )

    existing = MetaApp.objects.filter(app_id=app_id).first()
    if existing is not None and existing.tenant_id != tenant.pk:
        # The same answer whoever the other organization is.
        raise AccountError(
            "This Meta app is already connected to another organization.", code="already_connected", field="app_id"
        )
    if existing is not None:
        raise AccountError(
            "This Meta app is already registered: it's in your list of Meta apps.",
            code="already_registered",
            field="app_id",
        )

    app = MetaApp(tenant=tenant, app_id=app_id)
    app.app_secret = app_secret
    app.verify_token = new_verify_token()
    app.save()
    return app


def update_secret(*, tenant, meta_app_id, app_secret: str) -> MetaApp:
    """Replace the App secret, after it's reset in Meta's App Dashboard."""
    app_secret = app_secret.strip()
    if not app_secret:
        raise AccountError("App secret is required.", code="required", field="app_secret")
    app = find_app(tenant, meta_app_id)
    app.app_secret = app_secret
    app.save(update_fields=["app_secret_encrypted", "updated_at"])
    return app


def regenerate_verify_token(*, tenant, meta_app_id) -> MetaApp:
    """A new verify token, for the business to paste into Meta; the address stays the same."""
    app = find_app(tenant, meta_app_id)
    app.verify_token = new_verify_token()
    app.save(update_fields=["verify_token_encrypted", "updated_at"])
    return app


@transaction.atomic
def remove_app(*, tenant, meta_app_id) -> None:
    """
    Remove the app, unless a connected number uses it (decision 4): removing it would silently cut that
    number off. Disconnected numbers on it go back to this service's app, as when they're connected
    again without choosing one.
    """
    app = find_app(tenant, meta_app_id, for_update=True)
    connected = app.accounts.filter(is_active=True).order_by("display_phone_number")
    if connected.exists():
        numbers = ", ".join(account.display_phone_number or account.phone_number_id for account in connected)
        raise AccountError(f"Disconnect its numbers first: {numbers}.", code="app_in_use")
    app.accounts.update(meta_app=None)
    app.delete()


@transaction.atomic
def set_account_app(*, tenant, account_id, meta_app_id) -> WhatsAppAccount:
    """
    Put a connected number on one of its organization's apps, or on this service's app when
    `meta_app_id` is None (decision 5). Its webhooks are checked with that app's secret from then on.
    """
    account = find_account(tenant, account_id, for_update=True)
    if not account.is_active:
        raise AccountError("This number is disconnected. Connect it again first.", code="not_connected")
    account.meta_app = find_app(tenant, meta_app_id, field="meta_app_id") if meta_app_id else None
    account.save(update_fields=["meta_app", "updated_at"])
    return account
