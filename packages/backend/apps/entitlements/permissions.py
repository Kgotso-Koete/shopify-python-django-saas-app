"""
The GraphQL permission for a feature an organization's plan must include (WhatsApp plan Step 3.3,
phase 3 decision 5). It sits beside the role check in a field's permission_classes, as one of three
questions every action answers: is the feature deployed here (its *_ENABLED setting), has the
organization paid for it (this class), and may this person do it (requires(...)).

It's put only on fields that act, or that call Shopify or Meta. Reading what an organization keeps
while its plan has lapsed (its numbers, stores and links) stays allowed (decision 3).
"""

from typing import Type

from rest_framework.exceptions import PermissionDenied
from rest_framework.permissions import BasePermission

from . import services
from .constants import Feature

# What the browser reads when the plan is the reason, rather than the generic "permission_denied".
PLAN_REQUIRED_MESSAGE = "plan_required"


def requires_feature(feature: Feature) -> Type[BasePermission]:
    class FeaturePermission(BasePermission):
        def has_permission(self, request, view) -> bool:
            tenant = getattr(request, "tenant", None)
            # Like requires(...): with no organization in context, the field's other checks decide.
            if tenant is None:
                return True
            if not services.has_feature(tenant, feature):
                raise PermissionDenied(PLAN_REQUIRED_MESSAGE)
            return True

    FeaturePermission.__name__ = f"Requires{feature.label}Plan"
    return FeaturePermission
