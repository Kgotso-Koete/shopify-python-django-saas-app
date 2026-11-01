"""
What the web app reads to show a feature's page working or read-only (WhatsApp plan Step 3.4, phase 3
decision 8, user story 28).

`organizationFeatures` lists only the names of the features the organization has unlocked, such as
["SHOPIFY", "WHATSAPP"], or [] on the free plan. It says nothing about the plan's name, price, trial
or payments, which stay behind billing.view, so any member may read it, a Member included. It's for
display only: every action is checked again by the backend (permissions.py).
"""

import graphene

from common.acl.policies import IsTenantMemberAccess
from common.graphql.acl import permission_classes

from . import services
from .constants import Feature


class Query(graphene.ObjectType):
    organization_features = graphene.List(
        graphene.NonNull(graphene.String), tenant_id=graphene.ID(required=True), required=True
    )

    @staticmethod
    @permission_classes(IsTenantMemberAccess)
    def resolve_organization_features(root, info, tenant_id):
        # The organization the tenant middleware checked the user belongs to.
        tenant = getattr(info.context, "tenant", None)
        if tenant is None:
            return []
        unlocked = services.features_for(tenant)
        # In the enum's order, so the answer reads the same every time.
        return [feature.value for feature in Feature if feature.value in unlocked]
