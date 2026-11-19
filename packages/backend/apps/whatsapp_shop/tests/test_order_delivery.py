"""
Tests for delivering every order update that can be delivered (WhatsApp plan Step 4.7, user story
WA.D5.SY.J1.A1, decided 2026-11-08).

- each stage keeps the message queued for it, and counts as sent only once Meta accepts that message; a
  message still queued, or failed, isn't sent
- a stage whose message is queued or sent isn't queued again, however often Shopify sends the webhook; one
  whose message failed is left for the business's list and Send again (user story WA.D3.OM.J2.A3)
- without a Celery worker, Shopify's order webhooks run the send sweep too, once their work is committed,
  so a passing failure is retried even when no customer writes (apps/whatsapp/tests/test_retries.py)

Kind of test: integration (agents.md section 2.5). Why: the store, number, customer, their cart's code and
the messages queued for them are rows in the test database, and apps.shopify's signals are sent as its
webhook handlers send them; the send task's `delay` is patched, and sending goes through a fake backend.
"""

import pytest

from apps.multitenancy.constants import TenantType
from apps.multitenancy.tests.factories import TenantFactory
from apps.shopify import signals
from apps.shopify.models import ShopifyShop
from apps.whatsapp.constants import MessageDirection, MessageStatus
from apps.whatsapp.models import WhatsAppMessage
from apps.whatsapp.services import outbox
from apps.whatsapp.tests.factories import MessageFactory
from apps.whatsapp.tests.fakes import FakeBackend

from ..models import StoreCheckout, StoreCustomer
from .chat import customer_of, selling_number, store

pytestmark = [pytest.mark.django_db, pytest.mark.story("WA.D5.SY.J1.A1")]

CODE = "wachk_CCCCCCCCCCCCCCCCCCCCCC"
CART = "gid://shopify/Cart/def"


@pytest.fixture(autouse=True)
def setup(mocker):
    mocker.patch("apps.whatsapp.tasks.send_queued_messages.delay")


@pytest.fixture
def shop():
    return store(TenantFactory(type=TenantType.ORGANIZATION, name="Acme"))


@pytest.fixture
def customer(shop):
    contact = customer_of(selling_number(shop.tenant, shop))
    MessageFactory(contact=contact)
    return contact


@pytest.fixture
def checkout(customer, shop):
    store_customer = StoreCustomer.objects.create(contact=customer, tenant=shop.tenant, cart_id=CART, cart_shop=shop)
    return StoreCheckout.objects.create(code=CODE, store_customer=store_customer, shop=shop, cart_id=CART)


def order(**fields):
    return {
        "id": 6001,
        "name": "#2001",
        "total_price": "99.00",
        "currency": "ZAR",
        "financial_status": "pending",
        "note_attributes": [{"name": "_whatsapp_checkout", "value": CODE}],
        **fields,
    }


def created(shop):
    signals.order_created.send(sender=ShopifyShop, shop=shop, order=order())


def paid(shop):
    signals.order_paid.send(sender=ShopifyShop, shop=shop, order=order(financial_status="paid"))


def outbound(customer):
    return WhatsAppMessage.objects.filter(contact=customer, direction=MessageDirection.OUTBOUND).order_by("pk")


class TestAStageCountsAsSentOnceMetaAcceptsIt:
    def test_the_stage_keeps_its_queued_message_which_isnt_sent_yet(self, shop, customer, checkout):
        created(shop)

        checkout.refresh_from_db()
        assert checkout.received_message == outbound(customer).get()
        assert checkout.received_message.status == MessageStatus.QUEUED
        assert not checkout.stage_sent(paid=False)

    def test_once_meta_accepts_it_the_stage_is_sent(self, shop, customer, checkout):
        created(shop)

        outbox.drain(customer.pk, backend=FakeBackend())

        checkout.refresh_from_db()
        assert checkout.received_message.status == MessageStatus.ACCEPTED
        assert checkout.stage_sent(paid=False)
        assert not checkout.stage_sent(paid=True)

    def test_a_failed_message_isnt_sent(self, shop, customer, checkout):
        created(shop)
        outbound(customer).update(status=MessageStatus.FAILED, error_code=132001)

        checkout.refresh_from_db()
        assert not checkout.stage_sent(paid=False)

    def test_paid_keeps_its_own_message(self, shop, customer, checkout):
        created(shop)
        paid(shop)

        checkout.refresh_from_db()
        received, paid_message = outbound(customer)
        assert checkout.received_message == received
        assert checkout.paid_message == paid_message


class TestOncePerStage:
    def test_a_retried_webhook_while_the_message_is_queued_queues_nothing_more(self, shop, customer, checkout):
        created(shop)
        created(shop)

        assert outbound(customer).count() == 1

    def test_a_failed_stage_isnt_queued_again_by_a_retried_webhook(self, shop, customer, checkout):
        # Send again on the WhatsApp page sends it, once its cause is fixed (user story WA.D3.OM.J2.A3).
        created(shop)
        outbound(customer).update(status=MessageStatus.FAILED, error_code=132001)

        created(shop)

        assert outbound(customer).count() == 1


class TestWithoutAWorker:
    def test_an_order_webhook_runs_the_send_sweep_once_committed(
        self, shop, customer, checkout, mocker, django_capture_on_commit_callbacks
    ):
        sweep = mocker.patch("apps.whatsapp.services.outbox.sweep_if_due")

        with django_capture_on_commit_callbacks(execute=True):
            paid(shop)
            sweep.assert_not_called()

        sweep.assert_called_once_with()
