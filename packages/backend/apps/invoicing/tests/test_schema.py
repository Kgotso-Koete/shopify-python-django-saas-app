"""
Tests for the organization's invoices in the GraphQL API (WhatsApp plan phase 4, Step 4.4c, decisions 11
and 12): the list the web's transaction history reads, to offer Download invoice beside each payment.

- invoices needs billing.view (the Owner and Admins by default), as payfastPayments does
- an organization sees only its own invoices, newest first, and only those whose PDF exists
- each says which PayFast payment it's for, by that payment's GraphQL id, so the web matches its row

Kind of test: integration (agents.md section 2.5). Why: queries go through the real GraphQL schema,
permissions and test database; nothing is faked.
"""

from datetime import datetime, timezone
from decimal import Decimal

import pytest
from django.core.files.base import ContentFile
from freezegun import freeze_time
from graphql_relay import to_global_id

from apps.multitenancy.constants import TenantType, TenantUserRole
from apps.multitenancy.tests.factories import TenantFactory, TenantMembershipFactory
from apps.payfast.tests.factories import PayFastPaymentFactory
from apps.users.tests.factories import UserFactory

from .. import services

pytestmark = [pytest.mark.django_db, pytest.mark.story("WA.D6.OM.J2.A1")]

INVOICES = """
query($tenantId: ID!) {
  invoices(tenantId: $tenantId) { id number issuedAt description amount currency paymentId }
}
"""


@pytest.fixture(autouse=True)
def private_storage(settings, tmp_path):
    settings.STORAGES = {**settings.STORAGES, "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"}}
    settings.MEDIA_ROOT = str(tmp_path)


@pytest.fixture
def acme():
    return TenantFactory(type=TenantType.ORGANIZATION, name="Acme")


def act_as(graphene_client, tenant, role):
    user = UserFactory()
    TenantMembershipFactory(user=user, tenant=tenant, role=role)
    graphene_client.force_authenticate(user)
    graphene_client.set_tenant_dependent_context(tenant, role)
    return user


def invoiced(tenant, **fields):
    """A completed payment of `tenant`'s, invoiced, with its PDF written."""
    payment = PayFastPaymentFactory(tenant=tenant, item_name="Monthly plan", amount_gross=Decimal("199.00"), **fields)
    invoice = services.issue_invoice(payment)
    invoice.pdf.save(f"{invoice.number}.pdf", ContentFile(b"%PDF-test"), save=True)
    return invoice


def query(graphene_client, tenant):
    return graphene_client.query(INVOICES, variable_values={"tenantId": to_global_id("TenantType", tenant.id)})


@pytest.mark.parametrize("role", [TenantUserRole.OWNER, TenantUserRole.ADMIN])
def test_billing_view_lists_the_organizations_invoices_newest_first(graphene_client, acme, role):
    act_as(graphene_client, acme, role)
    with freeze_time(datetime(2026, 11, 2, 9, 0, tzinfo=timezone.utc)):
        first = invoiced(acme)
        second = invoiced(acme)

    response = query(graphene_client, acme)

    assert "errors" not in response
    assert response["data"]["invoices"] == [
        {
            "id": str(invoice.id),
            "number": invoice.number,
            "issuedAt": "2026-11-02T09:00:00+00:00",
            "description": "Monthly plan",
            "amount": "199.00",
            "currency": "ZAR",
            "paymentId": to_global_id("PayFastPaymentType", invoice.payment.pk),
        }
        for invoice in (second, first)
    ]


def test_a_member_without_billing_view_is_refused(graphene_client, acme):
    act_as(graphene_client, acme, TenantUserRole.MEMBER)
    invoiced(acme)

    response = query(graphene_client, acme)

    assert "permission" in response["errors"][0]["message"].lower()


def test_another_organizations_invoices_never_show(graphene_client, acme):
    act_as(graphene_client, acme, TenantUserRole.OWNER)
    invoiced(TenantFactory(type=TenantType.ORGANIZATION, name="Globex"))

    assert query(graphene_client, acme)["data"]["invoices"] == []


def test_an_invoice_whose_pdf_isnt_written_yet_isnt_offered(graphene_client, acme):
    act_as(graphene_client, acme, TenantUserRole.OWNER)
    services.issue_invoice(PayFastPaymentFactory(tenant=acme))

    assert query(graphene_client, acme)["data"]["invoices"] == []
