"""
Test factories for the WhatsApp models.

Every phone number, id and token here is obviously fake: South African numbers in the unused
27 000 range, and Meta-shaped ids that no real account has.
"""

import factory

from apps.multitenancy.constants import TenantType
from apps.multitenancy.tests.factories import TenantFactory, TenantMembershipFactory
from apps.users.tests.factories import UserFactory

from .. import constants, models


class MetaAppFactory(factory.django.DjangoModelFactory):
    """An organization's own Meta app (plan Step 2.9)."""

    tenant = factory.SubFactory(TenantFactory, type=TenantType.ORGANIZATION)
    app_id = factory.Sequence(lambda n: f"{300000000000000 + n}")
    # Set through the model's properties, so they're stored encrypted like real code does.
    app_secret = factory.Sequence(lambda n: f"test-app-secret-{n}")
    verify_token = factory.LazyFunction(models.new_verify_token)

    class Meta:
        model = models.MetaApp


class InternalAccountFactory(factory.django.DjangoModelFactory):
    """An organization's internal communications number, the one its own team texts (plan Step 1.17)."""

    purpose = constants.AccountPurpose.INTERNAL_COMMUNICATIONS
    tenant = factory.SubFactory(TenantFactory, type=TenantType.ORGANIZATION)
    display_phone_number = factory.Sequence(lambda n: f"27000000{n:03d}")
    # Meta's ids are long digit strings; these start well away from any real range.
    phone_number_id = factory.Sequence(lambda n: f"{100000000000000 + n}")
    waba_id = factory.Sequence(lambda n: f"{200000000000000 + n}")
    # Set through the model's property, so the factory stores it encrypted like real code does.
    access_token = "test-access-token"

    class Meta:
        model = models.WhatsAppAccount


class ExternalAccountFactory(InternalAccountFactory):
    """An organization's external communications number, the one its store customers text."""

    purpose = constants.AccountPurpose.EXTERNAL_COMMUNICATIONS


class ContactFactory(factory.django.DjangoModelFactory):
    """Someone who texted a number: a team member on an internal number, or a store customer."""

    account = factory.SubFactory(InternalAccountFactory)
    # Meta's business-scoped user id has the shape "<country>.<digits>", e.g. "US.13491208655302741918".
    bsuid = factory.Sequence(lambda n: f"ZA.{1000000000000000000 + n}")
    wa_id = factory.Sequence(lambda n: f"27000001{n:03d}")
    profile_name = factory.Faker("first_name")

    class Meta:
        model = models.WhatsAppContact


def link_member(contact, user=None, **membership):
    """
    Make `user` (a new one by default) a member of the contact's organization, with its phone linked
    on the contact's internal number (plan Step 1.17), and return the link.
    """
    user = user or UserFactory()
    TenantMembershipFactory(user=user, tenant=contact.account.tenant, **membership)
    return models.WhatsAppIdentity.objects.create(user=user, contact=contact, account=contact.account)


class MessageFactory(factory.django.DjangoModelFactory):
    """A message a contact sent us (the default), or one we sent them (direction=OUTBOUND)."""

    contact = factory.SubFactory(ContactFactory)
    direction = constants.MessageDirection.INBOUND
    # Meta's ids look like "wamid.HBgL..."; these are obviously fake.
    wamid = factory.Sequence(lambda n: f"wamid.TEST{n:06d}")
    kind = constants.MessageKind.TEXT
    payload = factory.LazyFunction(lambda: {"text": "Hi"})
    status = constants.MessageStatus.RECEIVED

    class Meta:
        model = models.WhatsAppMessage
