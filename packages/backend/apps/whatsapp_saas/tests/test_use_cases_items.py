"""
Tests for the CRUD item operations in apps/whatsapp_saas/use_cases.py (plan Step 1.9, decision D10,
user stories 6 and 9).

Each checks exactly what its GraphQL twin checks (the audit in plan Step 1.9): membership plus
features.crud.view to read, features.crud.manage to write, always within the selected organization,
and through CrudDemoItemSerializer for its validation. Lists come in pages of 7 (D17).

Kind of test: integration (agents.md section 2.5). Why: items, organizations and permissions are
rows in the test database; nothing is faked.
"""

import pytest

from apps.demo.models import CrudDemoItem
from apps.demo.tests.factories import CrudDemoItemFactory
from apps.multitenancy.constants import TenantType, TenantUserRole
from apps.multitenancy.models import OrganizationRolePermission
from apps.multitenancy.tests.factories import TenantFactory, TenantMembershipFactory
from apps.users.tests.factories import UserFactory

from .. import use_cases
from ..use_cases import PAGE_SIZE, UseCaseError

pytestmark = pytest.mark.django_db


@pytest.fixture
def user():
    return UserFactory()


@pytest.fixture
def organization(user):
    tenant = TenantFactory(type=TenantType.ORGANIZATION)
    TenantMembershipFactory(user=user, tenant=tenant, role=TenantUserRole.ADMIN)
    return tenant


@pytest.fixture
def member_organization(user):
    tenant = TenantFactory(type=TenantType.ORGANIZATION)
    TenantMembershipFactory(user=user, tenant=tenant, role=TenantUserRole.MEMBER)
    return tenant


def items_in(tenant, count):
    return [CrudDemoItemFactory(tenant=tenant, name=f"Item {n:02d}") for n in range(count)]


class TestListing:
    def test_pages_hold_seven_items(self, user, organization):
        items_in(organization, 16)

        first = use_cases.list_items(user, organization, page=1)
        third = use_cases.list_items(user, organization, page=3)

        assert PAGE_SIZE == 7
        assert len(first.items) == 7
        assert (first.page, first.total_pages, first.has_previous, first.has_next) == (1, 3, False, True)
        assert len(third.items) == 2
        assert (third.has_previous, third.has_next) == (True, False)

    def test_items_are_listed_by_name_and_only_the_organizations_own(self, user, organization):
        CrudDemoItemFactory(tenant=organization, name="Beta")
        CrudDemoItemFactory(tenant=organization, name="Alpha")
        CrudDemoItemFactory(tenant=TenantFactory(type=TenantType.ORGANIZATION), name="Not ours")

        assert [item.name for item in use_cases.list_items(user, organization, page=1).items] == ["Alpha", "Beta"]

    def test_a_page_past_the_end_shows_the_last_page(self, user, organization):
        items_in(organization, 3)

        assert use_cases.list_items(user, organization, page=9).page == 1

    def test_reading_needs_features_crud_view(self, user, member_organization):
        OrganizationRolePermission.objects.filter(
            role__tenant=member_organization, permission__code="features.crud.view"
        ).delete()

        with pytest.raises(UseCaseError) as raised:
            use_cases.list_items(user, member_organization, page=1)

        assert raised.value.code == "permission_denied"


class TestViewing:
    def test_an_item_is_shown(self, user, organization):
        [item] = items_in(organization, 1)

        assert use_cases.get_item(user, organization, item.pk) == item

    def test_another_organizations_item_is_not_found(self, user, organization):
        theirs = CrudDemoItemFactory(tenant=TenantFactory(type=TenantType.ORGANIZATION))

        with pytest.raises(UseCaseError) as raised:
            use_cases.get_item(user, organization, theirs.pk)

        assert raised.value.code == "not_found"


class TestWriting:
    def test_an_item_is_created_through_the_websites_serializer(self, user, organization):
        item = use_cases.create_item(user, organization, "Monthly report")

        assert item.name == "Monthly report"
        assert item.tenant == organization
        assert item.created_by == user

    def test_an_item_is_renamed(self, user, organization):
        [item] = items_in(organization, 1)

        use_cases.update_item(user, organization, item.pk, "Renamed")

        assert CrudDemoItem.objects.get(pk=item.pk).name == "Renamed"

    def test_an_item_is_deleted(self, user, organization):
        [item] = items_in(organization, 1)

        use_cases.delete_item(user, organization, item.pk)

        assert not CrudDemoItem.objects.filter(pk=item.pk).exists()

    def test_validation_errors_come_back_as_a_message(self, user, organization):
        with pytest.raises(UseCaseError) as raised:
            use_cases.create_item(user, organization, "")

        assert raised.value.code == "invalid"
        assert "name" in str(raised.value).lower()

    @pytest.mark.parametrize(
        "write",
        [
            lambda user, tenant, item: use_cases.create_item(user, tenant, "New"),
            lambda user, tenant, item: use_cases.update_item(user, tenant, item.pk, "New"),
            lambda user, tenant, item: use_cases.delete_item(user, tenant, item.pk),
        ],
        ids=["create", "update", "delete"],
    )
    def test_writing_needs_features_crud_manage(self, user, member_organization, write):
        # Members have features.crud.view by default but not manage, as on the website.
        [item] = items_in(member_organization, 1)
        OrganizationRolePermission.objects.filter(
            role__tenant=member_organization, permission__code="features.crud.manage"
        ).delete()

        with pytest.raises(UseCaseError) as raised:
            write(user, member_organization, item)

        assert raised.value.code == "permission_denied"
        assert CrudDemoItem.objects.get(pk=item.pk).name == item.name

    def test_another_organizations_item_cant_be_changed(self, user, organization):
        theirs = CrudDemoItemFactory(tenant=TenantFactory(type=TenantType.ORGANIZATION), name="Theirs")

        with pytest.raises(UseCaseError) as raised:
            use_cases.update_item(user, organization, theirs.pk, "Mine now")

        assert raised.value.code == "not_found"
        assert CrudDemoItem.objects.get(pk=theirs.pk).name == "Theirs"

    def test_an_organization_the_user_isnt_in_is_not_found(self, user):
        stranger = TenantFactory(type=TenantType.ORGANIZATION)

        with pytest.raises(UseCaseError) as raised:
            use_cases.create_item(user, stranger, "Sneaky")

        assert raised.value.code == "not_found"
