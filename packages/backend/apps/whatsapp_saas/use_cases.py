"""
The operations an organization's team can run on WhatsApp (plan Steps 1.9 and 1.12b, decision D10,
user stories 4 to 7 and 9). Menus, Flows and the assistant all call these, so there's one set of rules
for all three. Since Step 1.17 they don't list, pick or create organizations; those use cases stay,
with their tests, for the website-parity audit of Step 1.9.

Each operation checks exactly what its GraphQL field checks (the audit in plan Step 1.9), and saves
through the website's own serializer, given a server-built context with the linked user, so
validation isn't written twice and upstream code isn't edited:
- membership: an accepted TenantMembership, rechecked on every call, so a stale selection grants
  nothing; anything else is "not found", never "forbidden", so nobody learns what exists
- permissions: user_has_permission with the same codes as the GraphQL fields
- the organization always comes from the conversation, which is the number's organization (Step
  1.17), never from message text

Each write has a check_ twin that runs the same checks and validation without saving (Step 1.11b):
a form's answers are checked before the user is asked to confirm, and checked again when they do.
"""

import copy
from dataclasses import dataclass
from types import SimpleNamespace

from django.core.exceptions import ValidationError
from django.core.paginator import Paginator

from apps.demo.models import CrudDemoItem
from apps.demo.serializers import CrudDemoItemSerializer
from apps.multitenancy.models import Tenant, TenantMembership, user_has_permission
from apps.multitenancy.serializers import TenantSerializer
from apps.shopify.models import ShopifyShop
from apps.shopify.products import ShopifyReconnectRequired, ShopifyTryAgainLater, fetch_products
from common.acl.policies import IsTenantAdminAccess
from common.action_logging.service import log_update

# Lists hold at most 7 items, so Previous, Next and Main menu always fit in Meta's 10 rows (D17).
PAGE_SIZE = 7


class UseCaseError(Exception):
    """An operation that didn't happen, with a reason the user can read. `code` is for the caller."""

    def __init__(self, message: str, code: str):
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class Page:
    """One page of a list, and where it sits among the others."""

    items: list
    page: int
    total_pages: int
    has_previous: bool
    has_next: bool


@dataclass(frozen=True)
class ProductPage:
    """
    One page of a store's products, as plain dicts from fetch_products. Shopify pages by cursor:
    the next page starts after end_cursor, the previous one ends before start_cursor.
    """

    store: ShopifyShop
    products: list[dict]
    has_previous: bool
    has_next: bool
    start_cursor: str | None
    end_cursor: str | None


# Organizations (user stories 4 and 5)


def list_organizations(user) -> list[Tenant]:
    """Every organization the user is an accepted member of, by name. Mirrors allTenants."""
    tenant_ids = TenantMembership.objects.filter(user=user).values_list("tenant_id", flat=True)
    return list(Tenant.objects.filter(pk__in=tenant_ids).order_by("name", "pk"))


def select_organization(user, tenant_id) -> Tenant:
    """The organization to work in; only one the user is an accepted member of."""
    membership = _first(TenantMembership.objects.select_related("tenant"), user=user, tenant_id=tenant_id)
    if membership is None:
        raise _not_found("Organization")
    return membership.tenant


def create_organization(user, name: str) -> Tenant:
    """Create an organization, the creator becoming its owner. Mirrors createTenant (any user)."""
    return _new_organization(user, name).save()


def check_create_organization(user, name: str) -> None:
    _new_organization(user, name)


def rename_organization(user, tenant, name: str) -> Tenant:
    """
    Rename an organization. Mirrors updateTenant: admin access (IsTenantAdminAccess) and
    org.settings.edit, and the same action-log entry its @action_logged writes.
    """
    serializer = _renamed_organization(user, tenant, name)
    old = copy.copy(serializer.instance)
    renamed = serializer.save()
    # Respects the organization's own action-logging switch, as @action_logged does.
    log_update(tenant_id=tenant.pk, entity_type="tenant", old_instance=old, new_instance=renamed, actor_user=user)
    return renamed


def check_rename_organization(user, tenant, name: str) -> None:
    _renamed_organization(user, tenant, name)


def can_rename_organization(user, tenant) -> bool:
    """Whether to offer Rename organization; a courtesy only, since the rename checks again."""
    if tenant is None:
        return False
    try:
        _require_rename(user, tenant)
    except UseCaseError:
        return False
    return True


def _new_organization(user, name: str) -> TenantSerializer:
    serializer = TenantSerializer(data={"name": name}, context=_context(user))
    _validate(serializer)
    return serializer


def _renamed_organization(user, tenant, name: str) -> TenantSerializer:
    _require_rename(user, tenant)
    # Saved from a fresh copy: the conversation's tenant may be stale, and saving it would undo
    # changes made since it was selected (the serializer saves every field).
    current = Tenant.objects.get(pk=tenant.pk)
    serializer = TenantSerializer(instance=current, data={"name": name}, partial=True, context=_context(user))
    _validate(serializer)
    return serializer


def _require_rename(user, tenant) -> None:
    membership = _membership(user, tenant)
    request = SimpleNamespace(user=user, tenant=tenant, user_role=membership.role)
    if not IsTenantAdminAccess().is_request_from_tenant_admin(request, None, None):
        raise _denied("rename this organization")
    if not user_has_permission(user, tenant, "org.settings.edit"):
        raise _denied("rename this organization")


# CRUD items (user story 6)


def list_items(user, tenant, page: int) -> Page:
    """A page of the organization's items, by name. Mirrors allCrudDemoItems (features.crud.view)."""
    _require(user, tenant, "features.crud.view", "see this organization's items")
    paginator = Paginator(CrudDemoItem.objects.filter(tenant=tenant).order_by("name", "pk"), PAGE_SIZE)
    # get_page shows the last page for a number past the end, and the first for nonsense.
    current = paginator.get_page(page)
    return Page(
        items=list(current.object_list),
        page=current.number,
        total_pages=paginator.num_pages,
        has_previous=current.has_previous(),
        has_next=current.has_next(),
    )


def get_item(user, tenant, item_id) -> CrudDemoItem:
    """One of the organization's items. Mirrors crudDemoItem (features.crud.view)."""
    _require(user, tenant, "features.crud.view", "see this organization's items")
    return _item(tenant, item_id)


def create_item(user, tenant, name: str) -> CrudDemoItem:
    """Mirrors createCrudDemoItem (features.crud.manage), through CrudDemoItemSerializer."""
    return _new_item(user, tenant, name).save()


def check_create_item(user, tenant, name: str) -> None:
    _new_item(user, tenant, name)


def update_item(user, tenant, item_id, name: str) -> CrudDemoItem:
    """Mirrors updateCrudDemoItem (features.crud.manage)."""
    return _updated_item(user, tenant, item_id, name).save()


def check_update_item(user, tenant, item_id, name: str) -> CrudDemoItem:
    """The item as it is now, if it may be renamed to `name`."""
    return _updated_item(user, tenant, item_id, name).instance


def delete_item(user, tenant, item_id) -> None:
    """Mirrors deleteCrudDemoItem (features.crud.manage)."""
    check_delete_item(user, tenant, item_id).delete()


def check_delete_item(user, tenant, item_id) -> CrudDemoItem:
    """The item, if the user may delete it."""
    _require(user, tenant, "features.crud.manage", "change this organization's items")
    return _item(tenant, item_id)


def can_manage_items(user, tenant) -> bool:
    """Whether to show Edit and Delete; a courtesy only, since the writes check again."""
    return bool(
        tenant is not None
        and TenantMembership.objects.filter(user=user, tenant=tenant).exists()
        and user_has_permission(user, tenant, "features.crud.manage")
    )


# Shopify products (user story 7)


def list_stores(user, tenant) -> list[ShopifyShop]:
    """The organization's connected stores, by domain. Mirrors shopifyShops (shopify.view)."""
    _require(user, tenant, "shopify.view", "see this organization's products")
    return list(ShopifyShop.objects.filter(tenant=tenant).order_by("shop_domain", "pk"))


def get_store(user, tenant, store_id) -> ShopifyShop:
    """One of the organization's stores (shopify.view); another organization's is "not found"."""
    _require(user, tenant, "shopify.view", "see this organization's products")
    store = _first(ShopifyShop.objects, tenant=tenant, pk=store_id)
    if store is None:
        raise _not_found("Store")
    return store


def list_products(
    user, tenant, store_id, *, after: str | None = None, before: str | None = None, query: str | None = None
) -> ProductPage:
    """
    A page of a store's products, newest first, optionally searched. Mirrors shopifyProducts
    (shopify.view, and only a store of the selected organization); Shopify is asked only after both.
    """
    store = get_store(user, tenant, store_id)
    try:
        page = fetch_products(store, first=PAGE_SIZE, after=after, before=before, query=query, newest_first=True)
    except ShopifyReconnectRequired as error:
        raise UseCaseError(str(error), "reconnect_required") from error
    except ShopifyTryAgainLater as error:
        raise UseCaseError(str(error), "try_again_later") from error
    info = page["page_info"]
    return ProductPage(
        store=store,
        products=page["products"],
        has_previous=info["has_previous_page"],
        has_next=info["has_next_page"],
        start_cursor=info["start_cursor"],
        end_cursor=info["end_cursor"],
    )


def can_view_products(user, tenant) -> bool:
    """Whether to offer Products; a courtesy only, since the reads check again."""
    return bool(
        tenant is not None
        and TenantMembership.objects.filter(user=user, tenant=tenant).exists()
        and user_has_permission(user, tenant, "shopify.view")
    )


def _new_item(user, tenant, name: str) -> CrudDemoItemSerializer:
    _require(user, tenant, "features.crud.manage", "change this organization's items")
    serializer = CrudDemoItemSerializer(data={"name": name, "tenant_id": str(tenant.pk)}, context=_context(user))
    _validate(serializer)
    return serializer


def _updated_item(user, tenant, item_id, name: str) -> CrudDemoItemSerializer:
    _require(user, tenant, "features.crud.manage", "change this organization's items")
    item = _item(tenant, item_id)
    serializer = CrudDemoItemSerializer(instance=item, data={"name": name}, partial=True, context=_context(user))
    _validate(serializer)
    return serializer


# Shared checks


def _membership(user, tenant):
    """The user's accepted membership of `tenant`; anything else is "not found"."""
    membership = TenantMembership.objects.filter(user=user, tenant=tenant).first()
    if membership is None:
        raise _not_found("Organization")
    return membership


def _require(user, tenant, permission: str, doing: str) -> None:
    _membership(user, tenant)
    if not user_has_permission(user, tenant, permission):
        raise _denied(doing)


def _item(tenant, item_id) -> CrudDemoItem:
    item = _first(CrudDemoItem.objects, tenant=tenant, pk=item_id)
    if item is None:
        raise _not_found("Item")
    return item


def _first(queryset, **filters):
    """
    The first row matching `filters`, or None, also for an id that can't be one, which the database
    or the id field refuses: the assistant may pass any string it likes (Step 1.13).
    """
    try:
        return queryset.filter(**filters).first()
    except (ValueError, TypeError, ValidationError):
        return None


def _context(user) -> dict:
    """What the website's serializers read from a request: the user, here the linked one (D10)."""
    return {"request": SimpleNamespace(user=user)}


def _validate(serializer) -> None:
    if not serializer.is_valid():
        field, messages = next(iter(serializer.errors.items()))
        label = "" if field == "non_field_errors" else f"{field.replace('_', ' ').capitalize()}: "
        raise UseCaseError(f"{label}{messages[0]}", "invalid")


def _not_found(what: str) -> UseCaseError:
    return UseCaseError(f"{what} not found.", "not_found")


def _denied(doing: str) -> UseCaseError:
    return UseCaseError(f"You don't have permission to {doing}.", "permission_denied")
