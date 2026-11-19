"""
Tests for downloading an invoice's PDF, /api/invoicing/<invoice id>/pdf/ (WhatsApp plan phase 4, Step
4.4c, decisions 11, 12 and 19).

- a logged-in member with billing.view in the invoice's organization gets the PDF, as a file named after
  its number
- anyone else gets nothing: no login, no billing.view, or another organization's invoice ("not found",
  so nobody learns which invoices exist)
- an invoice whose organization was deleted is only the operator's, in the Django admin

Kind of test: integration (agents.md section 2.5). Why: requests go through the real route and Django REST
framework's authentication with its test client, against the test database, and the PDF is read from a
temporary folder through Django's file storage; nothing is faked.
"""

from decimal import Decimal

import pytest
from django.core.files.base import ContentFile
from rest_framework.test import APIClient

from apps.multitenancy.constants import TenantType, TenantUserRole
from apps.multitenancy.tests.factories import TenantFactory, TenantMembershipFactory
from apps.payfast.tests.factories import PayFastPaymentFactory
from apps.users.tests.factories import UserFactory

from .. import services

pytestmark = [pytest.mark.django_db, pytest.mark.story("WA.D6.OM.J2.A1")]

PDF = b"%PDF-1.3 an invoice"


@pytest.fixture(autouse=True)
def private_storage(settings, tmp_path):
    settings.STORAGES = {**settings.STORAGES, "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"}}
    settings.MEDIA_ROOT = str(tmp_path)


@pytest.fixture
def acme():
    return TenantFactory(type=TenantType.ORGANIZATION, name="Acme")


@pytest.fixture
def invoice(acme):
    payment = PayFastPaymentFactory(tenant=acme, item_name="Monthly plan", amount_gross=Decimal("199.00"))
    issued = services.issue_invoice(payment)
    issued.pdf.save(f"{issued.number}.pdf", ContentFile(PDF), save=True)
    return issued


def client_for(tenant, role):
    """A logged-in member of `tenant` with `role`."""
    user = UserFactory()
    TenantMembershipFactory(user=user, tenant=tenant, role=role)
    client = APIClient()
    client.force_authenticate(user)
    return client


def download(client, invoice):
    return client.get(f"/api/invoicing/{invoice.id}/pdf/")


@pytest.mark.parametrize("role", [TenantUserRole.OWNER, TenantUserRole.ADMIN])
def test_billing_view_downloads_the_pdf_named_after_its_number(acme, invoice, role):
    response = download(client_for(acme, role), invoice)

    assert response.status_code == 200
    assert response["Content-Type"] == "application/pdf"
    assert response["Content-Disposition"] == f'attachment; filename="{invoice.number}.pdf"'
    assert b"".join(response.streaming_content) == PDF


def test_without_a_login_nothing_is_sent(invoice):
    response = download(APIClient(), invoice)

    assert response.status_code in (401, 403)
    assert not hasattr(response, "streaming_content")


def test_a_member_without_billing_view_is_refused(acme, invoice):
    assert download(client_for(acme, TenantUserRole.MEMBER), invoice).status_code == 403


def test_another_organizations_invoice_is_not_found(invoice):
    globex = TenantFactory(type=TenantType.ORGANIZATION, name="Globex")

    assert download(client_for(globex, TenantUserRole.OWNER), invoice).status_code == 404


def test_an_invoice_id_that_isnt_one_is_not_found(acme):
    assert client_for(acme, TenantUserRole.OWNER).get("/api/invoicing/not-an-id/pdf/").status_code == 404


def test_a_deleted_organizations_invoice_is_not_found(acme, invoice):
    client = client_for(acme, TenantUserRole.OWNER)
    acme.delete()

    assert download(client, invoice).status_code == 404
