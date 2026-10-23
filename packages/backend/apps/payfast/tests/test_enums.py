"""
Every PayFast enum is stored with exactly its member names (PayFast plan section 14, agents.md section
5.3b): "active" becomes "ACTIVE", "subscription" becomes "SUBSCRIPTION", and the frequency is "MONTHLY"
or "ANNUAL" rather than PayFast's codes 3 and 6, which are looked up only where the checkout form is
built for PayFast.

Kind of test: unit (agents.md section 2.5). Why: the enum classes and the code lookup on their own; no
database is used and nothing is faked.
"""

import pytest
from django.db import models

from .. import constants
from ..models import PayFastCheckout, PayFastPayment, PayFastSubscription

pytestmark = pytest.mark.django_db

# Listed by hand: the model enums are nested in their models, so they can't be found by scanning a module.
ENUMS = {
    "PayFastSubscription.Status": PayFastSubscription.Status,
    "PayFastCheckout.Kind": PayFastCheckout.Kind,
    "PayFastCheckout.Status": PayFastCheckout.Status,
    "PayFastPayment.Kind": PayFastPayment.Kind,
    "Frequency": constants.Frequency,
}


@pytest.mark.parametrize("enum", ENUMS.values(), ids=ENUMS.keys())
def test_every_member_is_stored_as_its_name(enum):
    assert {member.name: member.value for member in enum} == {member.name: member.name for member in enum}


def test_every_enum_in_the_app_is_listed():
    # A guard on the test itself: every choices class in the models and constants is in ENUMS.
    from .. import models as payfast_models

    found = {
        f"{model.__name__}.{name}"
        for model in vars(payfast_models).values()
        if isinstance(model, type) and issubclass(model, models.Model) and model.__module__ == payfast_models.__name__
        for name, value in vars(model).items()
        if isinstance(value, type) and issubclass(value, models.Choices)
    }
    found |= {
        name
        for name, value in vars(constants).items()
        if isinstance(value, type) and issubclass(value, models.Choices) and value.__module__ == constants.__name__
    }
    assert found == set(ENUMS)


def test_payfasts_own_frequency_codes_are_looked_up_from_the_names():
    # https://developers.payfast.co.za/docs#subscriptions : 3 - Monthly, 6 - Annual
    assert constants.payfast_frequency_code(constants.Frequency.MONTHLY) == 3
    assert constants.payfast_frequency_code(constants.Frequency.ANNUAL) == 6
