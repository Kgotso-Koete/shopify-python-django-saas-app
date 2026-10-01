import uuid
from decimal import Decimal

import factory

from apps.finances import constants as finance_constants
from .. import constants, models


class PayFastSubscriptionFactory(factory.django.DjangoModelFactory):
    """
    A tenant's PayFast subscription. Defaults to the free plan, like a freshly created tenant.

    With PAYMENT_BACKEND=payfast, creating a tenant already creates its subscription
    (apps.finances.signals), and a tenant has at most one. So instead of inserting a second row, the
    factory updates the existing one with the requested values.
    """

    tenant = factory.SubFactory("apps.multitenancy.tests.factories.TenantFactory")
    plan = finance_constants.FREE_PLAN.name
    status = models.PayFastSubscription.Status.ACTIVE

    class Meta:
        model = models.PayFastSubscription

    @classmethod
    def _create(cls, model_class, *args, **kwargs):
        existing = model_class.objects.filter(tenant=kwargs["tenant"]).first()
        if existing is None:
            return super()._create(model_class, *args, **kwargs)
        for field_name, value in kwargs.items():
            setattr(existing, field_name, value)
        existing.save()
        return existing

    class Params:
        # PayFastSubscriptionFactory(monthly=True): an active, paid monthly subscription with a token.
        monthly = factory.Trait(
            plan=finance_constants.MONTHLY_PLAN.name,
            amount=Decimal("199.00"),
            frequency=constants.Frequency.MONTHLY,
            token=factory.LazyFunction(lambda: str(uuid.uuid4())),
            has_used_trial=True,
        )


class PayFastCheckoutFactory(factory.django.DjangoModelFactory):
    tenant = factory.SubFactory("apps.multitenancy.tests.factories.TenantFactory")
    kind = models.PayFastCheckout.Kind.SUBSCRIPTION
    plan = finance_constants.MONTHLY_PLAN.name
    amount = Decimal("199.00")
    recurring_amount = Decimal("199.00")

    class Meta:
        model = models.PayFastCheckout


class PayFastPaymentFactory(factory.django.DjangoModelFactory):
    tenant = factory.SubFactory("apps.multitenancy.tests.factories.TenantFactory")
    kind = models.PayFastPayment.Kind.DONATION
    pf_payment_id = factory.Sequence(lambda n: str(1000000 + n))
    m_payment_id = factory.LazyFunction(lambda: str(uuid.uuid4()))
    amount_gross = Decimal("50.00")
    amount_fee = Decimal("-1.15")
    amount_net = Decimal("48.85")
    payment_status = "COMPLETE"
    item_name = "Donation"
    raw = factory.LazyFunction(dict)

    class Meta:
        model = models.PayFastPayment
