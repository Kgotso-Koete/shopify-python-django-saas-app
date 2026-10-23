"""
The writes an organization's team confirms in chat (plan decision D11), shared by the menus and the
assistant (Steps 1.10, 1.11b and 1.13), so both ask with the same summary and run the same action.
Creating an organization isn't one: everything happens in the number's organization (Step 1.17).

Each ask_to_ function runs the write's check_ use case first, raising UseCaseError if it couldn't
happen, and then stores it with confirmations.ask_to_confirm; nothing is saved until Confirm. The
actions, registered in apps.py, run when it's pressed, and their use case checks again.
"""

import functools

from apps.whatsapp.services import confirmations
from apps.whatsapp.services.confirmations import ActionRefused

from . import use_cases
from .use_cases import UseCaseError

CREATE_ITEM_ACTION = "items.create"
UPDATE_ITEM_ACTION = "items.update"
DELETE_ITEM_ACTION = "items.delete"
RENAME_ORGANIZATION_ACTION = "organizations.rename"


def ask_to_create_item(turn, tenant, name: str) -> list[dict]:
    name = name.strip()
    use_cases.check_create_item(turn.user, tenant, name)
    return confirmations.ask_to_confirm(
        turn,
        action=CREATE_ITEM_ACTION,
        arguments={"name": name},
        summary=f"Create {name} in {tenant.name}?",
        tenant=tenant,
    )


def ask_to_update_item(turn, tenant, item_id, name: str) -> list[dict]:
    name = name.strip()
    item = use_cases.check_update_item(turn.user, tenant, item_id, name)
    return confirmations.ask_to_confirm(
        turn,
        action=UPDATE_ITEM_ACTION,
        arguments={"item_id": str(item.pk), "name": name},
        summary=f"Rename {item.name} to {name}?",
        tenant=tenant,
    )


def ask_to_delete_item(turn, tenant, item_id) -> list[dict]:
    item = use_cases.check_delete_item(turn.user, tenant, item_id)
    return confirmations.ask_to_confirm(
        turn,
        action=DELETE_ITEM_ACTION,
        arguments={"item_id": str(item.pk)},
        summary=f"Delete {item.name}? This can't be undone.",
        tenant=tenant,
    )


def ask_to_rename_organization(turn, tenant, name: str) -> list[dict]:
    name = name.strip()
    use_cases.check_rename_organization(turn.user, tenant, name)
    return confirmations.ask_to_confirm(
        turn,
        action=RENAME_ORGANIZATION_ACTION,
        arguments={"name": name},
        summary=f"Rename {tenant.name} to {name}?",
        tenant=tenant,
    )


def _refusable(action):
    """A use case's refusal, such as a permission lost since asking, becomes the reply."""

    @functools.wraps(action)
    def run(user, tenant, **arguments) -> str:
        try:
            return action(user, tenant, **arguments)
        except UseCaseError as error:
            raise ActionRefused(str(error)) from error

    return run


@_refusable
def create_item_action(user, tenant, name) -> str:
    item = use_cases.create_item(user, tenant, name)
    return f"Created {item.name} in {tenant.name}."


@_refusable
def update_item_action(user, tenant, item_id, name) -> str:
    item = use_cases.update_item(user, tenant, item_id, name)
    return f"Saved: the item is now called {item.name}."


@_refusable
def delete_item_action(user, tenant, item_id) -> str:
    name = use_cases.get_item(user, tenant, item_id).name
    use_cases.delete_item(user, tenant, item_id)
    return f"Deleted {name}."


@_refusable
def rename_organization_action(user, tenant, name) -> str:
    renamed = use_cases.rename_organization(user, tenant, name)
    return f"Renamed: the organization is now called {renamed.name}."


ACTIONS = {
    CREATE_ITEM_ACTION: create_item_action,
    UPDATE_ITEM_ACTION: update_item_action,
    DELETE_ITEM_ACTION: delete_item_action,
    RENAME_ORGANIZATION_ACTION: rename_organization_action,
}
