"""
Tests for choosing the organization's plan from its team's WhatsApp number (plan phase 4, Step 4.1,
decision 9): "Plans and billing" in the main menu, and the assistant's send_plans_link tool, send a
**Choose a plan** link to the organization's Subscriptions page on the website.

- only members with billing.manage (the Owner, by default) get the link; anyone else is told to ask
  the organization's owner, as the website says
- the menu offers it only to them, and a press after losing the permission is refused
- the link is the organization's own Subscriptions page, keyed by its GraphQL id as the website's
  routes are; nothing secret travels in it, since the page checks login and billing.manage itself
- the assistant is told to send the link, never to describe plans or prices itself

Kind of test: integration (agents.md section 2.5). Why: users, organizations, roles, identities and
conversations are rows in the test database, routed through the real router and handler; nothing is
faked but the send task's Celery delay.
"""

import json

import pytest
from graphql_relay import to_global_id

from apps.multitenancy.constants import TenantType, TenantUserRole
from apps.multitenancy.models import (
    OrganizationRole,
    OrganizationRolePermission,
    Permission,
    invalidate_user_permissions_cache,
)
from apps.multitenancy.tests.factories import TenantFactory
from apps.whatsapp.models import WhatsAppConversation
from apps.whatsapp.services.router import Turn

from .. import prompts, use_cases
from ..tools import TOOLS
from ..use_cases import UseCaseError
from .chat import main_menu, send, team_member

pytestmark = [pytest.mark.django_db, pytest.mark.story("WA.D6.OM.J1.A2")]

ASK_THE_OWNER = "Ask the organization's owner to choose a plan."


@pytest.fixture(autouse=True)
def setup(settings, mocker):
    settings.WHATSAPP_DEFAULT_CONVERSATION_MODE = "WHATSAPP_FORM"
    settings.WEB_APP_URL = "https://app.example.com"
    mocker.patch("apps.whatsapp.tasks.send_queued_messages.delay")


@pytest.fixture
def acme():
    return TenantFactory(type=TenantType.ORGANIZATION, name="Acme")


def subscriptions_page(tenant):
    # The website's tenant routes are keyed by the organization's GraphQL id (apps/shopify/views.py does the same).
    return f"https://app.example.com/{to_global_id('TenantType', tenant.id)}/subscriptions"


def owner_of(tenant):
    return team_member(tenant, role=TenantUserRole.OWNER)


def grant_billing_manage_to_admins(tenant):
    """Give `tenant`'s Admin role billing.manage, as an Owner can on the website's roles page."""
    admins = OrganizationRole.objects.get(tenant=tenant, system_role_type=TenantUserRole.ADMIN)
    OrganizationRolePermission.objects.create(role=admins, permission=Permission.objects.get(code="billing.manage"))
    for membership in admins.tenant.user_memberships.all():
        invalidate_user_permissions_cache(membership.user_id, tenant.id)


def turn_for(contact):
    """An assistant turn for `contact`'s linked member, in the number's organization (Step 1.17)."""
    conversation, _ = WhatsAppConversation.objects.get_or_create(contact=contact, tenant=contact.account.tenant)
    return Turn(message=None, contact=contact, conversation=conversation, user=contact.identity.user, mode="AGENTIC")


def run_tool(contact):
    """The assistant's send_plans_link, which takes no arguments, run as `contact`'s linked member."""
    return TOOLS.run(turn_for(contact), "send_plans_link", json.dumps({}))


class TestTheUseCase:
    def test_the_owner_gets_the_organizations_subscriptions_page(self, acme):
        owner = owner_of(acme).identity.user

        assert use_cases.subscriptions_link(owner, acme) == subscriptions_page(acme)

    @pytest.mark.parametrize("role", [TenantUserRole.ADMIN, TenantUserRole.MEMBER])
    def test_anyone_without_billing_manage_is_told_to_ask_the_owner(self, acme, role):
        user = team_member(acme, role=role).identity.user

        with pytest.raises(UseCaseError) as refused:
            use_cases.subscriptions_link(user, acme)

        assert str(refused.value) == ASK_THE_OWNER
        assert refused.value.code == "permission_denied"

    def test_someone_outside_the_organization_finds_nothing(self, acme):
        stranger = owner_of(TenantFactory(type=TenantType.ORGANIZATION)).identity.user

        with pytest.raises(UseCaseError) as refused:
            use_cases.subscriptions_link(stranger, acme)

        assert refused.value.code == "not_found"


class TestTheMenu:
    def test_the_owner_is_offered_plans_and_billing_and_gets_the_link(self, acme):
        contact = owner_of(acme)
        menu = main_menu(contact)

        [link] = send(contact, press=menu.press("Plans and billing"))

        assert link.link == {"display_text": "Choose a plan", "url": subscriptions_page(acme)}
        assert "Acme" in link.body

    @pytest.mark.parametrize("role", [TenantUserRole.ADMIN, TenantUserRole.MEMBER])
    def test_anyone_else_is_not_offered_it(self, acme, role):
        assert "Plans and billing" not in main_menu(team_member(acme, role=role)).titles

    def test_a_role_given_billing_manage_is_offered_it(self, acme):
        contact = team_member(acme, role=TenantUserRole.ADMIN)
        grant_billing_manage_to_admins(acme)

        assert "Plans and billing" in main_menu(contact).titles

    def test_a_press_after_losing_billing_manage_is_refused(self, acme):
        # An Owner always has every permission (apps/multitenancy/models.py), so the permission is lost
        # by a role that was given it: here, Admins.
        contact = team_member(acme, role=TenantUserRole.ADMIN)
        grant_billing_manage_to_admins(acme)
        menu = main_menu(contact)
        OrganizationRolePermission.objects.filter(role__tenant=acme, permission__code="billing.manage").delete()
        # Permissions are cached per user and organization; upstream's role editing clears it like this.
        invalidate_user_permissions_cache(contact.identity.user_id, acme.id)

        [refused, *_] = send(contact, press=menu.press("Plans and billing"))

        assert ASK_THE_OWNER in refused.body


class TestTheAssistant:
    def test_its_tool_sends_the_owner_the_link_and_ends_the_turn(self, acme):
        result = run_tool(owner_of(acme))

        [message] = result.messages
        assert message["interactive"]["action"]["parameters"]["url"] == subscriptions_page(acme)
        assert result.output["success"] is True

    def test_its_tool_tells_anyone_else_to_ask_the_owner(self, acme):
        result = run_tool(team_member(acme, role=TenantUserRole.ADMIN))

        assert result.messages is None
        assert result.output == {"success": False, "error": ASK_THE_OWNER, "code": "permission_denied"}

    def test_the_instructions_say_to_send_the_link_and_never_quote_plans_or_prices(self, acme):
        instructions = prompts.instructions(turn_for(owner_of(acme)))

        assert "send_plans_link" in instructions
        assert "never describe plans or prices" in instructions
