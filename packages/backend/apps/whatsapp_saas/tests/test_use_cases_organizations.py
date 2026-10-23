"""
Tests for the organization operations in apps/whatsapp_saas/use_cases.py (plan Step 1.9, decision
D10, user stories 4, 5 and 9).

Menus, Flows and the assistant all call these, so each checks exactly what its GraphQL twin checks
(the audit in plan Step 1.9), and reuses the website's serializer for its validation:
- list: the user's accepted memberships only
- select: only an organization the user is an accepted member of; anything else is "not found"
- create: any user, through TenantSerializer, which makes the creator the owner
- rename: admin access and org.settings.edit, as updateTenant; the same action-log entry

Kind of test: integration (agents.md section 2.5). Why: organizations, memberships, roles and action
logs are rows in the test database; nothing is faked.
"""

import pytest

from apps.multitenancy.constants import TenantType, TenantUserRole
from apps.multitenancy.models import ActionLog, OrganizationRolePermission, Tenant, TenantMembership
from apps.multitenancy.tests.factories import TenantFactory, TenantMembershipFactory
from apps.users.tests.factories import UserFactory

from .. import use_cases
from ..use_cases import UseCaseError

pytestmark = pytest.mark.django_db


@pytest.fixture
def user():
    return UserFactory()


def organization_with(user, role, name="Acme"):
    tenant = TenantFactory(type=TenantType.ORGANIZATION, name=name)
    TenantMembershipFactory(user=user, tenant=tenant, role=role)
    return tenant


class TestListing:
    def test_only_accepted_memberships_are_listed_by_name(self, user):
        beta = organization_with(user, TenantUserRole.MEMBER, name="Beta")
        alpha = organization_with(user, TenantUserRole.OWNER, name="Alpha")
        invited = TenantFactory(type=TenantType.ORGANIZATION, name="Invited")
        TenantMembershipFactory(user=user, tenant=invited, role=TenantUserRole.MEMBER, is_accepted=False)
        TenantFactory(type=TenantType.ORGANIZATION, name="Someone else's")
        # Every user gets a personal organization at sign-up; the website lists it too.
        personal = Tenant.objects.get(creator=user, type=TenantType.DEFAULT)

        assert use_cases.list_organizations(user) == sorted([alpha, beta, personal], key=lambda tenant: tenant.name)


class TestSelecting:
    def test_an_organization_the_user_belongs_to_is_selected(self, user):
        tenant = organization_with(user, TenantUserRole.MEMBER)

        assert use_cases.select_organization(user, tenant.pk) == tenant

    @pytest.mark.parametrize("whose", ["someone_else", "invitation_only"])
    def test_any_other_organization_is_not_found(self, user, whose):
        tenant = TenantFactory(type=TenantType.ORGANIZATION)
        if whose == "invitation_only":
            TenantMembershipFactory(user=user, tenant=tenant, role=TenantUserRole.MEMBER, is_accepted=False)

        with pytest.raises(UseCaseError) as raised:
            use_cases.select_organization(user, tenant.pk)

        assert raised.value.code == "not_found"


class TestCreating:
    def test_the_creator_becomes_the_owner_as_on_the_website(self, user):
        tenant = use_cases.create_organization(user, "Monthly Club")

        assert tenant.name == "Monthly Club"
        assert tenant.type == TenantType.ORGANIZATION
        membership = TenantMembership.objects.get(user=user, tenant=tenant)
        assert membership.role == TenantUserRole.OWNER

    def test_the_websites_validation_applies(self, user):
        # TenantSerializer refuses an empty name, so this does too: one set of rules (D10).
        with pytest.raises(UseCaseError) as raised:
            use_cases.create_organization(user, "")

        assert raised.value.code == "invalid"
        assert "name" in str(raised.value).lower()
        # Only the personal organization every user gets at sign-up.
        assert not Tenant.objects.filter(creator=user, type=TenantType.ORGANIZATION).exists()


class TestRenaming:
    @pytest.mark.parametrize("role", [TenantUserRole.OWNER, TenantUserRole.ADMIN])
    def test_an_owner_or_admin_renames_it_and_the_action_is_logged(self, user, role):
        tenant = organization_with(user, role, name="Old name")
        # Action logging is each organization's choice, off by default, as on the website.
        Tenant.objects.filter(pk=tenant.pk).update(action_logging_enabled=True)

        renamed = use_cases.rename_organization(user, tenant, "New name")

        assert renamed.name == "New name"
        assert Tenant.objects.get(pk=tenant.pk).name == "New name"
        # The same entry updateTenant's @action_logged writes.
        entry = ActionLog.objects.filter(tenant=tenant, entity_type="tenant", action_type="UPDATE").get()
        assert entry.actor_user == user

    def test_with_action_logging_off_nothing_is_logged_as_on_the_website(self, user):
        tenant = organization_with(user, TenantUserRole.OWNER, name="Old name")

        use_cases.rename_organization(user, tenant, "New name")

        assert not ActionLog.objects.filter(tenant=tenant).exists()

    def test_a_member_cant_rename_it(self, user):
        tenant = organization_with(user, TenantUserRole.MEMBER, name="Old name")

        with pytest.raises(UseCaseError) as raised:
            use_cases.rename_organization(user, tenant, "New name")

        assert raised.value.code == "permission_denied"
        assert Tenant.objects.get(pk=tenant.pk).name == "Old name"

    def test_an_admin_without_org_settings_edit_cant_rename_it(self, user):
        tenant = organization_with(user, TenantUserRole.ADMIN, name="Old name")
        OrganizationRolePermission.objects.filter(role__tenant=tenant, permission__code="org.settings.edit").delete()

        with pytest.raises(UseCaseError) as raised:
            use_cases.rename_organization(user, tenant, "New name")

        assert raised.value.code == "permission_denied"

    def test_someone_who_left_cant_rename_it(self, user):
        # The membership is rechecked every time, so a stale selection grants nothing.
        tenant = organization_with(user, TenantUserRole.OWNER, name="Old name")
        TenantMembership.objects.filter(user=user, tenant=tenant).delete()

        with pytest.raises(UseCaseError) as raised:
            use_cases.rename_organization(user, tenant, "New name")

        assert raised.value.code == "not_found"
