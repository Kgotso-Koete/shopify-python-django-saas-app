"""
Demo WhatsApp numbers for an organization, for the human checks (plan Steps 1.5 and 1.17, user story
11). Modelled on apps/shopify/management/commands/shopify_seed_demo.py. Development data only: it
refuses to run in production, and every id, token and secret is fake.

- external communications numbers, one in each state the WhatsApp tab shows
- the organization's internal communications number: a fake one if it has none. One it already has,
  such as a real one connected on the tab, is kept, since an organization has one.
- a linked user, an Admin, linked on that number; a second organization, with its own fake internal
  number, where they're a Member; and an unlinked user with an expired code

    docker compose run --rm backend python manage.py whatsapp_seed_demo --email <your email>

Safe to run any number of times: each number is created or brought back to its demo state.
"""

from datetime import timedelta

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from apps.phone_verification.constants import Channel
from apps.phone_verification.models import PhoneVerificationCode
from apps.phone_verification.services import issue_code

from apps.demo.models import CrudDemoItem
from apps.multitenancy.constants import SystemRoleType, TenantType, TenantUserRole
from apps.multitenancy.permissions import create_system_roles_for_tenant
from apps.multitenancy.models import (
    OrganizationRole,
    Tenant,
    TenantMembership,
    TenantMembershipRole,
    invalidate_user_permissions_cache,
)
from apps.users.models import User
from apps.whatsapp.constants import AccountPurpose, ConnectionMethod, MessageDirection, MessageKind, MessageStatus
from apps.whatsapp.models import WhatsAppAccount, WhatsAppContact, WhatsAppIdentity, WhatsAppMessage

# A made-up Member of the seeded organization, for the human check that a member (whatsapp.view only)
# can see the numbers but not connect, test or disconnect one.
MEMBER_EMAIL = "whatsapp-member@example.com"
MEMBER_PASSWORD = "WhatsAppMember123!"

# The demo numbers, in an unused id range, one in each state the WhatsApp tab shows.
CREDENTIALS_ONLY = "100000000000801"
SUBSCRIBED = "100000000000802"
MESSAGE_RECEIVED = "100000000000803"
DISCONNECTED = "100000000000804"
# Step 1.17: the internal communications numbers, for the organization if it has none, and for the second.
INTERNAL = "100000000000805"
SECOND_INTERNAL = "100000000000806"

# Step 1.7: a linked user, on fake numbers in the unused 27 000 range, and an unlinked one.
LINKED_EMAIL = "whatsapp-linked@example.com"
LINKED_PASSWORD = "WhatsAppLinked123!"
LINKED_NUMBER = "27000000001"
LINKED_BSUID = "ZA.1000000000000000101"
UNLINKED_EMAIL = "whatsapp-unlinked@example.com"
UNLINKED_PASSWORD = "WhatsAppUnlinked123!"
UNLINKED_NUMBER = "27000000002"
SECOND_ORGANIZATION = "WhatsApp demo: second organization"


class Command(BaseCommand):
    help = "Seed demo WhatsApp numbers for an organization the given user owns (development only)."

    def add_arguments(self, parser):
        parser.add_argument("--email", required=True, type=str, help="Email of the user who owns the organization.")
        parser.add_argument(
            "--organization",
            type=str,
            default=None,
            help="Exact name of an organization the user owns. Default: the first one they own.",
        )

    def handle(self, *args, **options):
        if settings.ENVIRONMENT_NAME == "production":
            raise CommandError("Cannot run whatsapp_seed_demo in production!")

        email = options["email"]
        user = User.objects.filter(email=email).first()
        if user is None:
            raise CommandError(f"User with email '{email}' does not exist.")
        # TenantMembership's link back to Tenant is named user_memberships (apps/multitenancy/models.py).
        owned = Tenant.objects.filter(user_memberships__user=user, user_memberships__role=TenantUserRole.OWNER)
        tenant = owned.filter(name=options["organization"]).first() if options["organization"] else owned.first()
        if tenant is None:
            raise CommandError(f"User '{email}' does not own that organization (or any). Create one first.")

        now = timezone.now()
        credentials_only = self._number(tenant, CREDENTIALS_ONLY, "Demo: credentials verified", now)
        credentials_only.subscribed_at = None
        credentials_only.save()

        subscribed = self._number(tenant, SUBSCRIBED, "Demo: app subscribed", now)
        message_received = self._number(tenant, MESSAGE_RECEIVED, "Demo: message received", now)
        contact, _ = WhatsAppContact.objects.update_or_create(
            account=message_received,
            bsuid="ZA.1000000000000000803",
            defaults={"wa_id": "27000000803", "profile_name": "Demo customer"},
        )
        WhatsAppMessage.objects.update_or_create(
            wamid="wamid.DEMO803",
            defaults={
                "contact": contact,
                "direction": MessageDirection.INBOUND,
                "kind": MessageKind.TEXT,
                "payload": {"text": "Hi", "action_id": "", "flow_response": {}},
                "status": MessageStatus.RECEIVED,
                "sent_at": now,
            },
        )

        disconnected = self._number(tenant, DISCONNECTED, "Demo: disconnected", now)
        disconnected.access_token_encrypted = ""
        disconnected.subscribed_at = None
        disconnected.is_active = False
        disconnected.save()

        for account in (credentials_only, subscribed, message_received, disconnected):
            self.stdout.write(self.style.SUCCESS(f"Demo number {account.phone_number_id}: {account.verified_name}"))

        member = self._member(tenant)
        self.stdout.write(self.style.SUCCESS(f"Member: {member.email} / {MEMBER_PASSWORD} (Member of {tenant.name})"))

        self._identities(tenant)

    def _identities(self, tenant):
        """
        Steps 1.7 and 1.17: a user linked from the fake phone 27000000001 on the organization's internal
        number (an Admin of it), and on a second organization's (a Member), and an unlinked user
        holding an expired link code for 27000000002.
        """
        now = timezone.now()
        internal = WhatsAppAccount.objects.internal_for(tenant) or self._number(
            tenant, INTERNAL, "Demo: internal communications", now, purpose=AccountPurpose.INTERNAL_COMMUNICATIONS
        )

        linked_user = self._user(LINKED_EMAIL, LINKED_PASSWORD)
        self._join(linked_user, tenant, TenantUserRole.ADMIN, SystemRoleType.ADMIN)
        # Step 1.10: a second organization where the linked user is only a Member (no Edit or Delete
        # on items), and 20 items in the first, so the menus show three pages.
        second, _ = Tenant.objects.get_or_create(
            name=SECOND_ORGANIZATION, creator=linked_user, defaults={"type": TenantType.ORGANIZATION}
        )
        if not OrganizationRole.objects.filter(tenant=second).exists():
            create_system_roles_for_tenant(second)
        self._join(linked_user, second, TenantUserRole.MEMBER, SystemRoleType.MEMBER)
        second_internal = WhatsAppAccount.objects.internal_for(second) or self._number(
            second, SECOND_INTERNAL, "Demo: second internal", now, purpose=AccountPurpose.INTERNAL_COMMUNICATIONS
        )
        CrudDemoItem.objects.get_or_create(tenant=second, name="Demo item in the second organization")
        for number in range(1, 21):
            CrudDemoItem.objects.get_or_create(tenant=tenant, name=f"Demo item {number:02d}")
        for account in (internal, second_internal):
            self._link(linked_user, account)
        self.stdout.write(
            self.style.SUCCESS(
                f"Linked user: {LINKED_EMAIL} / {LINKED_PASSWORD} (Admin of {tenant.name}, Member of {second.name}), "
                f"WhatsApp {LINKED_NUMBER}, business-scoped user id {LINKED_BSUID}"
            )
        )
        self.stdout.write(f"  Internal number of {tenant.name}: {internal.phone_number_id}")

        unlinked_user = self._user(UNLINKED_EMAIL, UNLINKED_PASSWORD)
        WhatsAppIdentity.objects.filter(user=unlinked_user).delete()
        issue_code(user=unlinked_user, phone_number=UNLINKED_NUMBER, channel=Channel.WHATSAPP_INBOUND, ttl_seconds=600)
        PhoneVerificationCode.objects.filter(user=unlinked_user, consumed_at__isnull=True).update(
            expires_at=timezone.now() - timedelta(minutes=1)
        )
        self.stdout.write(
            self.style.SUCCESS(
                f"Unlinked user: {UNLINKED_EMAIL} / {UNLINKED_PASSWORD}, with an expired code for {UNLINKED_NUMBER}"
            )
        )

    @staticmethod
    def _link(user, account):
        """`user`'s demo phone, linked on the internal number `account`."""
        contact, _ = WhatsAppContact.objects.update_or_create(
            account=account,
            bsuid=LINKED_BSUID,
            defaults={"wa_id": LINKED_NUMBER, "profile_name": "Demo linked user"},
        )
        WhatsAppIdentity.objects.filter(user=user, account=account).exclude(contact=contact).delete()
        WhatsAppIdentity.objects.update_or_create(
            user=user, contact=contact, defaults={"account": account, "conversation_mode": ""}
        )

    @staticmethod
    def _user(email, password):
        user = User.objects.filter(email=email).first()
        if user is None:
            user = User.objects.create_user(email=email, password=password)
        user.is_confirmed = True
        user.save(update_fields=["is_confirmed"])
        return user

    @staticmethod
    def _join(user, tenant, legacy_role, system_role_type):
        """Make `user` an accepted member of `tenant`, with the RBAC role that grants the permissions."""
        membership, _ = TenantMembership.objects.get_or_create(
            user=user, tenant=tenant, defaults={"role": legacy_role, "is_accepted": True}
        )
        role = OrganizationRole.objects.get(tenant=tenant, system_role_type=system_role_type)
        TenantMembershipRole.objects.get_or_create(membership=membership, role=role)
        invalidate_user_permissions_cache(user.id, tenant.id)

    @staticmethod
    def _number(tenant, phone_number_id, verified_name, now, purpose=AccountPurpose.EXTERNAL_COMMUNICATIONS):
        """
        One demo number for `tenant`, connected with the form: a fake token Meta accepted now, and our
        app subscribed to its WhatsApp Business account now.
        """
        account, _ = WhatsAppAccount.objects.update_or_create(
            phone_number_id=phone_number_id,
            defaults={
                "purpose": purpose,
                "tenant": tenant,
                "waba_id": "200000000000800",
                "display_phone_number": f"+27 00 000 0{phone_number_id[-3:]}",
                "verified_name": verified_name,
                "connection_method": ConnectionMethod.MANUAL,
                "credentials_verified_at": now,
                "subscribed_at": now,
                "is_active": True,
            },
        )
        account.access_token = f"EAAGfake-demo-token-{phone_number_id[-3:]}"
        account.save()
        return account

    @staticmethod
    def _member(tenant):
        """A Member of `tenant`. Permissions come from the RBAC role assignment, so both are set."""
        member = User.objects.filter(email=MEMBER_EMAIL).first()
        if member is None:
            member = User.objects.create_user(email=MEMBER_EMAIL, password=MEMBER_PASSWORD)
        member.is_confirmed = True
        member.save(update_fields=["is_confirmed"])
        membership, _ = TenantMembership.objects.get_or_create(
            user=member, tenant=tenant, defaults={"role": TenantUserRole.MEMBER, "is_accepted": True}
        )
        member_role = OrganizationRole.objects.get(tenant=tenant, system_role_type=SystemRoleType.MEMBER)
        TenantMembershipRole.objects.get_or_create(membership=membership, role=member_role)
        invalidate_user_permissions_cache(member.id, tenant.id)
        return member
