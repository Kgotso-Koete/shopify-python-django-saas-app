"""
The organization's invoices in the GraphQL API (WhatsApp plan phase 4, Step 4.4c, decisions 11 and 12).

invoices lists them for billing.view, the permission payfastPayments uses, so the web's transaction
history can offer Download invoice beside each payment. The organization is the one the tenant
middleware checked the user belongs to, never one taken from the input. The PDF itself is downloaded
through views.py, never through GraphQL (decision 19).
"""

import graphene
from graphql_relay import to_global_id

from common.acl.policies import IsTenantMemberAccess
from common.graphql.acl import permission_classes, requires

from .models import Invoice


class InvoiceType(graphene.ObjectType):
    """One of the organization's invoices whose PDF is ready to download."""

    id = graphene.ID(required=True)
    number = graphene.String(required=True)
    issued_at = graphene.DateTime(required=True)
    description = graphene.String(required=True)
    # A string, so cents are never rounded on the way, e.g. "199.00".
    amount = graphene.String(required=True)
    currency = graphene.String(required=True)
    # The PayFast payment's GraphQL id (PayFastPaymentType), matching the transaction history's rows.
    payment_id = graphene.ID()

    @staticmethod
    def resolve_id(invoice, info):
        return str(invoice.id)

    @staticmethod
    def resolve_amount(invoice, info):
        return f"{invoice.amount:.2f}"

    @staticmethod
    def resolve_payment_id(invoice, info):
        return to_global_id("PayFastPaymentType", invoice.payment_id) if invoice.payment_id else None


class Query(graphene.ObjectType):
    invoices = graphene.List(graphene.NonNull(InvoiceType), tenant_id=graphene.ID(required=True), required=True)

    @staticmethod
    @permission_classes(IsTenantMemberAccess, requires("billing.view"))
    def resolve_invoices(root, info, tenant_id):
        tenant = getattr(info.context, "tenant", None)
        if tenant is None:
            return []
        # Only those whose PDF exists: Download invoice must always work.
        return Invoice.objects.filter(tenant=tenant).exclude(pdf="").order_by("-sequence")
