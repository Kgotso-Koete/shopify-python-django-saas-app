"""
Pytest fixtures for PayFast tests. Registered for the whole suite in packages/backend/conftest.py,
like every other app's fixtures, so nothing here may be autouse: it would change unrelated tests.
"""

from unittest import mock

import pytest
import pytest_factoryboy

from . import factories

pytest_factoryboy.register(factories.PayFastSubscriptionFactory)
pytest_factoryboy.register(factories.PayFastCheckoutFactory)
pytest_factoryboy.register(factories.PayFastPaymentFactory)

# Credentials and prices used by PayFast tests. The merchant id, key and passphrase are the public
# sandbox values from PayFast's own documentation (https://developers.payfast.co.za/docs#sandbox).
PAYFAST_TEST_SETTINGS = {
    "PAYMENT_BACKEND": "payfast",
    "PAYFAST_MERCHANT_ID": "10000100",
    "PAYFAST_MERCHANT_KEY": "46f0cd694581a",
    "PAYFAST_PASSPHRASE": "jt7NOE43FZPn",
    "PAYFAST_SANDBOX": True,
    "PAYFAST_NOTIFY_URL": "https://api.example.com/api/payfast/notify/",
    "PAYFAST_VERIFY_SOURCE_IP": True,
    "PAYFAST_MONTHLY_PRICE": "199.00",
    "PAYFAST_YEARLY_PRICE": "1990.00",
    "PAYFAST_DONATION_AMOUNTS": ["50", "100", "150"],
    "SUBSCRIPTION_TRIAL_PERIOD_DAYS": 7,
    "WEB_APP_URL": "https://app.example.com",
}


@pytest.fixture
def payfast_backend(settings):
    """Switch the app to PAYMENT_BACKEND=payfast with valid sandbox settings for one test."""
    for name, value in PAYFAST_TEST_SETTINGS.items():
        setattr(settings, name, value)
    return settings


@pytest.fixture
def payfast_api():
    """
    A mock PayFast API client, installed wherever services create one. Tests set return values or
    side effects on it and assert which API calls were made; no request ever leaves the test.
    """
    client = mock.Mock(name="PayFastApiClient()")
    with mock.patch("apps.payfast.services.PayFastApiClient", return_value=client):
        yield client
