"""
Tests for apps.payfast's payment_completed signal (WhatsApp plan phase 4, Step 4.4b, decisions 15 and
18): sent once for each payment PayFast confirms, so apps.invoicing can invoice it without apps.payfast
knowing invoicing exists.

- sent when an ITN records a completed payment: a donation, a renewal
- not sent again for a re-sent ITN, nor for a cancellation
- sent when the daily catch-up records a renewal whose ITN never came, with its placeholder id, and
  again when that ITN turns up with PayFast's real id

Kind of test: integration (agents.md section 2.5). Why: process_itn and the daily maintenance write
payments in the test database; the PayFast API is the payfast_api mock, and the signal's receiver is a
mock connected for each test.
"""

import datetime
import uuid
from unittest import mock

import pytest

from .. import services
from ..models import PayFastPayment
from ..signals import payment_completed

pytestmark = [pytest.mark.django_db, pytest.mark.usefixtures("payfast_backend")]

RETURN_URL = "https://app.example.com/en/tenant-1/subscriptions/payfast-return"
CANCEL_URL = "https://app.example.com/en/tenant-1/subscriptions/current-subscription/edit"
NOW = "2026-10-01 10:00:00"
NOW_DT = datetime.datetime(2026, 10, 1, 10, 0, tzinfo=datetime.timezone.utc)


def itn_data(**fields):
    """An ITN's fields (already verified), as test_services.py builds them."""
    return {
        "pf_payment_id": str(uuid.uuid4().int)[:9],
        "payment_status": "COMPLETE",
        "item_name": "Monthly plan",
        "amount_gross": "199.00",
        "amount_fee": "-4.58",
        "amount_net": "194.42",
        "merchant_id": "10000100",
        **fields,
    }


@pytest.fixture(autouse=True)
def the_clock_at_now(freezer):
    freezer.move_to(NOW)


@pytest.fixture
def receiver():
    """A receiver connected for the test only, recording each payment it's sent."""
    received = mock.Mock()
    payment_completed.connect(received, dispatch_uid="test_payment_completed")
    yield received
    payment_completed.disconnect(dispatch_uid="test_payment_completed")


def sent_payments(receiver):
    return [call.kwargs["payment"] for call in receiver.call_args_list]


@pytest.fixture
def paid_subscription(pay_fast_subscription_factory):
    """An active monthly subscription whose current period ends on 2026-10-31."""
    return pay_fast_subscription_factory(
        monthly=True,
        current_period_start=NOW_DT - datetime.timedelta(days=5),
        current_period_end=datetime.datetime(2026, 10, 31, 10, 0, tzinfo=datetime.timezone.utc),
    )


def test_a_donations_itn_sends_it_once(receiver, tenant, user_factory):
    form = services.create_donation_checkout(
        tenant=tenant, user=user_factory(), amount="50", return_url=RETURN_URL, cancel_url=CANCEL_URL
    )

    services.process_itn(itn_data(m_payment_id=str(form.m_payment_id), amount_gross="50.00", pf_payment_id="999"))

    assert sent_payments(receiver) == [PayFastPayment.objects.get(pf_payment_id="999")]


def test_a_renewals_itn_sends_it(receiver, paid_subscription):
    services.process_itn(itn_data(token=paid_subscription.token, pf_payment_id="4242"))

    assert sent_payments(receiver) == [PayFastPayment.objects.get(pf_payment_id="4242")]


def test_a_resent_itn_sends_nothing_more(receiver, paid_subscription):
    data = itn_data(token=paid_subscription.token, pf_payment_id="4242")
    services.process_itn(data)

    services.process_itn(data)

    assert len(sent_payments(receiver)) == 1


def test_a_cancellation_sends_nothing(receiver, paid_subscription):
    # A cancellation with an id of its own is recorded as a CANCELLED payment (test_services.py), never invoiced.
    services.process_itn(itn_data(token=paid_subscription.token, pf_payment_id="3424911", payment_status="CANCELLED"))

    assert sent_payments(receiver) == []


def test_the_catch_up_sends_it_with_its_placeholder_then_the_late_itn_with_payfasts_id(
    receiver, freezer, paid_subscription, payfast_api
):
    freezer.move_to("2026-11-02 10:00:00")
    payfast_api.fetch.return_value = {"status_text": "ACTIVE", "run_date": "2026-11-30T00:00:00+02:00"}
    services.run_daily_maintenance()
    [caught_up] = sent_payments(receiver)
    assert caught_up.pf_payment_id.startswith(services.CAUGHT_UP_ID_PREFIX)

    services.process_itn(itn_data(token=paid_subscription.token, pf_payment_id="777"))

    [first, late] = sent_payments(receiver)
    assert late.pk == first.pk
    assert late.pf_payment_id == "777"
