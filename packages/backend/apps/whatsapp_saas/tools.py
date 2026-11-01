"""
The assistant's tools for an organization's team on its internal communications number (plan Step
1.13, decisions D10 to D12, user story 8, Step 1.17).

A fixed list, each running one Step 1.9 or Step 1.12 operation, so the assistant can do what the
menus can and nothing more, with the same permission checks:
- the organization is the number's: no tool names one, and none lists, picks or creates one
  (maintainer's decision, 2026-10-22)
- a write asks the user to confirm with the menus' own summary (writes.py) and saves nothing; the
  model is told it's waiting for the user's press
- a refusal comes back as {"success": false, "error": ..., "code": ...}, in words the model can pass
  on; the shape the reference app found models read reliably
"""

import functools

from apps.whatsapp.agent.tools import Tool, ToolResult, Toolset

from . import display, use_cases, writes
from .use_cases import UseCaseError

AWAITING_CONFIRMATION = {
    "success": True,
    "status": "awaiting_confirmation",
    "message": "The user has been asked to confirm with buttons. Nothing is done until they press Confirm.",
}

NULLABLE_STRING = {"type": ["string", "null"]}

# A name the model made up gets confirmed by a user who never chose it (Step 2.8, finding 1: "create a
# new item" became an item called "New Item"), so every name says where it comes from.
USERS_NAME = {
    "type": "string",
    "description": "The name exactly as the user gave it; never make one up. If the user gave none, ask for it.",
}


def _tool(function):
    """Turns a refusal into the output the model reads."""

    @functools.wraps(function)
    def run(turn, **arguments):
        try:
            return function(turn, **arguments)
        except UseCaseError as error:
            return {"success": False, "error": str(error), "code": error.code}

    return run


def _organization(turn):
    """The number's organization, which the router puts in the conversation (Step 1.17)."""
    return turn.conversation.tenant


def _awaiting(messages) -> ToolResult:
    return ToolResult(dict(AWAITING_CONFIRMATION), messages=messages)


# The organization


@_tool
def rename_organization(turn, name):
    return _awaiting(writes.ask_to_rename_organization(turn, _organization(turn), name))


# Items


@_tool
def list_items(turn, page):
    tenant = _organization(turn)
    found = use_cases.list_items(turn.user, tenant, page=page or 1)
    return {
        "success": True,
        "organization": tenant.name,
        "items": [{"id": str(item.pk), "name": item.name} for item in found.items],
        "page": found.page,
        "total_pages": found.total_pages,
    }


@_tool
def create_item(turn, name):
    return _awaiting(writes.ask_to_create_item(turn, _organization(turn), name))


@_tool
def update_item(turn, item_id, name):
    return _awaiting(writes.ask_to_update_item(turn, _organization(turn), item_id, name))


@_tool
def delete_item(turn, item_id):
    return _awaiting(writes.ask_to_delete_item(turn, _organization(turn), item_id))


# Shopify products


@_tool
def list_stores(turn):
    stores = use_cases.list_stores(turn.user, _organization(turn))
    return {"success": True, "stores": [{"id": str(store.pk), "domain": store.shop_domain} for store in stores]}


@_tool
def list_products(turn, store_id, search, after, before):
    tenant = _organization(turn)
    if store_id is None:
        stores = use_cases.list_stores(turn.user, tenant)
        if not stores:
            return {
                "success": False,
                "error": f"No Shopify store is connected to {tenant.name}. It's connected on the website's Shopify page.",
                "code": "no_store",
            }
        if len(stores) > 1:
            return {
                "success": False,
                "error": "The organization has several stores. Call list_stores and pass the store_id the user means.",
                "code": "several_stores",
            }
        store_id = stores[0].pk
    page = use_cases.list_products(turn.user, tenant, store_id, after=after, before=before, query=search)
    return {
        "success": True,
        "store": page.store.shop_domain,
        "products": [
            {"title": product["title"], "price": display.price(product), "status": display.status(product)}
            for product in page.products
        ],
        "next_page_after": page.end_cursor if page.has_next else None,
        "previous_page_before": page.start_cursor if page.has_previous else None,
    }


TOOLS = Toolset(
    [
        Tool(
            "rename_organization",
            "Ask the user to confirm renaming the organization.",
            {"name": USERS_NAME},
            rename_organization,
        ),
        Tool(
            "list_items",
            "List the organization's items, 7 to a page, by name.",
            {"page": {"type": ["integer", "null"], "description": "The page, from 1; null for the first."}},
            list_items,
        ),
        Tool(
            "create_item",
            "Ask the user to confirm creating an item in the organization.",
            {"name": USERS_NAME},
            create_item,
        ),
        Tool(
            "update_item",
            "Ask the user to confirm renaming one of the organization's items.",
            {
                "item_id": {"type": "string", "description": "An id from list_items."},
                "name": USERS_NAME,
            },
            update_item,
        ),
        Tool(
            "delete_item",
            "Ask the user to confirm deleting one of the organization's items.",
            {"item_id": {"type": "string", "description": "An id from list_items."}},
            delete_item,
        ),
        Tool(
            "list_stores",
            "List the Shopify stores connected to the organization, with their ids.",
            {},
            list_stores,
        ),
        Tool(
            "list_products",
            "List a Shopify store's products, newest first, 7 to a page, optionally searched.",
            {
                "store_id": {
                    **NULLABLE_STRING,
                    "description": "An id from list_stores; null when the organization has one store.",
                },
                "search": {**NULLABLE_STRING, "description": "Words to search for; null for all products."},
                "after": {**NULLABLE_STRING, "description": "A next_page_after value, for the next page."},
                "before": {**NULLABLE_STRING, "description": "A previous_page_before value, for the previous page."},
            },
            list_products,
        ),
    ]
)
