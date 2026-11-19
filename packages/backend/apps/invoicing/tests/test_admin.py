"""
Tests for the invoices' Django admin (WhatsApp plan phase 4, decision 11): the operator sees every
invoice, whichever organization it's for, a deleted one's included, and can't add, change or delete
one, since an issued invoice is a record.

Kind of test: integration (agents.md section 2.5). Why: requests go through the Django admin pages with
Django's test client, against the test database; nothing is faked.
"""

import pytest
from django.urls import reverse

from apps.multitenancy.constants import TenantType
from apps.multitenancy.tests.factories import TenantFactory
from apps.payfast.tests.factories import PayFastPaymentFactory

from .. import services

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def plain_static_files(settings):
    # Admin pages render {% static %}; plain storage serves files straight from the apps, as in
    # apps/payfast/tests/test_admin.py.
    settings.STORAGES = {
        **settings.STORAGES,
        "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
    }


@pytest.fixture
def operator_client(client, user_factory):
    # In this codebase User.is_staff is is_superuser, so only superusers can use the Django admin.
    client.force_login(user_factory(is_superuser=True))
    return client


def test_the_operator_sees_every_organizations_invoices_a_deleted_ones_included(operator_client):
    acme = TenantFactory(type=TenantType.ORGANIZATION, name="Acme")
    globex = TenantFactory(type=TenantType.ORGANIZATION, name="Globex")
    first = services.issue_invoice(PayFastPaymentFactory(tenant=acme))
    second = services.issue_invoice(PayFastPaymentFactory(tenant=globex))
    acme.delete()

    page = operator_client.get(reverse("admin:invoicing_invoice_changelist")).content.decode()

    assert first.number in page and "Acme" in page
    assert second.number in page and "Globex" in page


def test_an_invoice_can_be_looked_at_but_never_added_changed_or_deleted(operator_client):
    invoice = services.issue_invoice(PayFastPaymentFactory(tenant=TenantFactory(type=TenantType.ORGANIZATION)))

    assert operator_client.get(reverse("admin:invoicing_invoice_change", args=[invoice.pk])).status_code == 200
    assert operator_client.get(reverse("admin:invoicing_invoice_add")).status_code == 403
    assert operator_client.get(reverse("admin:invoicing_invoice_delete", args=[invoice.pk])).status_code == 403
    response = operator_client.post(
        reverse("admin:invoicing_invoice_change", args=[invoice.pk]), {"tenant_name": "Changed"}
    )
    invoice.refresh_from_db()
    assert response.status_code == 403
    assert invoice.tenant_name != "Changed"
