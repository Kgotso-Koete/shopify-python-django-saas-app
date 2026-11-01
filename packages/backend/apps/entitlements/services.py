"""
Which features an organization may use (WhatsApp plan Step 3.2, phase 3 decisions 1 and 7): the plan
that applies to it now, then what that plan includes in the catalog.

Every check asks about one feature (`has_feature`), never about a plan's name. The answer is the
same under PayFast and Stripe, since apps.finances.billing reads either provider. It's worked out on
every call, never stored, so a trial or a period that ends counts at once.
"""

from django.conf import settings

from apps.finances import billing

from .constants import Feature
from .models import PlanFeature


def features_for(tenant) -> set[str]:
    """
    The features `tenant` may use: every one while PLAN_ENTITLEMENTS_ENABLED is off (decision 7),
    else those its current plan includes.
    """
    if not settings.PLAN_ENTITLEMENTS_ENABLED:
        return set(Feature.values)
    plan = billing.effective_plan(tenant)
    return set(PlanFeature.objects.filter(plan=plan).values_list("feature", flat=True))


def has_feature(tenant, feature: Feature) -> bool:
    return feature in features_for(tenant)
