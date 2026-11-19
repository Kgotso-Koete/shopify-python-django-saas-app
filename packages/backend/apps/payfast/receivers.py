"""
What deleting an organization does to its PayFast payments (WhatsApp plan phase 4, decision 17),
connected in apps.py.

The payments stay, as the operator's record: for disputes, and for SARS, which says to keep
supporting documents for five years
(https://www.sars.gov.za/faq/faq-for-how-long-am-i-expected-to-keep-the-supporting-documents/). Their
link to the organization becomes empty (SET_NULL on PayFastPayment.tenant), so each keeps a copy of the
organization's name first. The buyer's name, email and phone, which PayFast's ITN carries
(https://developers.payfast.co.za/docs#step_4_confirm_payment), are removed from the stored ITN:
POPIA section 14(4) asks for personal details to be de-identified once they're no longer needed
(https://popia.co.za/section-14-retention-and-restriction-of-records/). What stays matches PayFast's
own records: its transaction id, our reference, the amounts, status, plan and dates.
"""

from .models import PayFastPayment

# The ITN fields that identify the buyer (signature.py lists PayFast's field order).
BUYERS_DETAILS = ("name_first", "name_last", "email_address", "cell_number")


def keep_payments_without_the_buyers_details(sender, instance, **kwargs):
    """pre_delete of a Tenant: runs before its payments' link is emptied."""
    for payment in PayFastPayment.objects.filter(tenant=instance):
        payment.tenant_name = instance.name
        payment.raw = {key: value for key, value in payment.raw.items() if key not in BUYERS_DETAILS}
        payment.save(update_fields=["tenant_name", "raw", "updated_at"])
