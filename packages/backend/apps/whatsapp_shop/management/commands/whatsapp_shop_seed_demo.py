"""
Demo links between an organization's external WhatsApp numbers and its Shopify store, for the human
checks (plan Step 2.1b, user story WA.D3.OM.J1.A3). Run after whatsapp_seed_demo and shopify_seed_demo, which
create the demo numbers and the demo store:

- the demo numbers ...802 and ...803 sell from linked-demo.myshopify.com
- ...801 has no store chosen, so the page shows both cases
- three demo store customers on ...803, for the order updates' human checks (Step 4.6, user story WA.D5.SC.J1.A2),
  with checkouts whose codes the checks put on signed orders/create and orders/paid webhooks:
  - one whose 24-hour window is open, with a card checkout and an EFT checkout, the EFT one's cart
    still their open cart
  - one whose window closed 25 hours ago, with an order already told "received"
  - one with a paid order, for the check that forgets them (customers/redact)

Development data only: the command refuses to run in production. Safe to run again: each demo store
customer is brought back to its demo state, its checkouts with no order yet (or the order above), and
the updates earlier checks sent it deleted, so the checks can be run again from the start.

    docker compose run --rm backend python manage.py whatsapp_shop_seed_demo --email <owner email>
"""

from datetime import timedelta

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from apps.multitenancy.constants import TenantUserRole
from apps.multitenancy.models import Tenant
from apps.shopify.models import ShopifyShop
from apps.users.models import User
from apps.whatsapp.constants import MessageDirection, MessageKind, MessageStatus
from apps.whatsapp.management.commands.whatsapp_seed_demo import CREDENTIALS_ONLY, MESSAGE_RECEIVED, SUBSCRIBED
from apps.whatsapp.models import WhatsAppAccount, WhatsAppContact, WhatsAppMessage

from ...models import StoreCheckout, StoreCustomer, StorefrontChannel
from ...services import StoreChannelError, choose_store

# The store shopify_seed_demo links to the organization, with the scopes SHOPIFY_SCOPES lists.
DEMO_STORE = "linked-demo.myshopify.com"

# The demo store customers (Step 4.6), on made-up phones in the unused 27 000 range, all on the number
# MESSAGE_RECEIVED, which sells from DEMO_STORE. Each is (business-scoped user id, phone, name).
WINDOW_OPEN = ("ZA.1000000000000000811", "27000000811", "Demo shopper: window open")
WINDOW_CLOSED = ("ZA.1000000000000000812", "27000000812", "Demo shopper: window closed")
FORGOTTEN = ("ZA.1000000000000000813", "27000000813", "Demo shopper: to be forgotten")

# The checkouts' codes, which the human checks put in an order's note_attributes as `_whatsapp_checkout`
# (apps/whatsapp_shop/checkouts.py makes real ones: `wachk_` and 22 random characters).
CARD_CODE = "wachk_demo_card_order"
EFT_CODE = "wachk_demo_eft_order"
LATE_CODE = "wachk_demo_late_order"
FORGOTTEN_CODE = "wachk_demo_forgotten_order"
# Shopify's ids for the two orders that already exist when the seed runs. The card and EFT orders get theirs
# from the checks' webhooks.
LATE_ORDER_ID = 9100000003
FORGOTTEN_ORDER_ID = 9100000004


class Command(BaseCommand):
    help = "Link an organization's demo WhatsApp numbers to its demo Shopify store (development only)."

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
            raise CommandError("Cannot run whatsapp_shop_seed_demo in production!")

        email = options["email"]
        user = User.objects.filter(email=email).first()
        if user is None:
            raise CommandError(f"User with email '{email}' does not exist.")
        # TenantMembership's link back to Tenant is named user_memberships (apps/multitenancy/models.py).
        owned = Tenant.objects.filter(user_memberships__user=user, user_memberships__role=TenantUserRole.OWNER)
        tenant = owned.filter(name=options["organization"]).first() if options["organization"] else owned.first()
        if tenant is None:
            raise CommandError(f"User '{email}' does not own that organization (or any). Create one first.")

        numbers = {
            account.phone_number_id: account
            for account in WhatsAppAccount.objects.filter(
                tenant=tenant, phone_number_id__in=[CREDENTIALS_ONLY, SUBSCRIBED, MESSAGE_RECEIVED]
            )
        }
        if len(numbers) < 3:
            raise CommandError(
                "The demo WhatsApp numbers aren't there: run whatsapp_seed_demo first, with the same options."
            )

        # The two numbers that sell from the demo store; choose_store applies the page's own rules.
        for phone_number_id in (SUBSCRIBED, MESSAGE_RECEIVED):
            try:
                choose_store(tenant=tenant, account_id=str(numbers[phone_number_id].pk), shop_domain=DEMO_STORE)
            except StoreChannelError as error:
                raise CommandError(
                    f"{error} Run shopify_seed_demo first, with the same options and SHOPIFY_SCOPES holding the "
                    "storefront scopes."
                ) from error
            self.stdout.write(f"WhatsApp number {phone_number_id} sells from {DEMO_STORE}")

        # The third shows "no store chosen".
        StorefrontChannel.objects.filter(account=numbers[CREDENTIALS_ONLY]).delete()
        self.stdout.write(f"WhatsApp number {CREDENTIALS_ONLY} has no store chosen")

        self._store_customers(tenant, numbers[MESSAGE_RECEIVED], ShopifyShop.objects.get(shop_domain=DEMO_STORE))

    def _store_customers(self, tenant, account, shop):
        """The demo store customers and their checkouts, for the order updates' human checks (Step 4.6)."""
        now = timezone.now()

        # Open window: their last message was just now, so updates go out as normal messages. The EFT
        # checkout's cart is still their open cart, so its order shows the chat forgetting it.
        shopper = self._store_customer(tenant, account, WINDOW_OPEN, last_message_at=now)
        shopper.cart_id, shopper.cart_shop = "gid://shopify/Cart/demo-eft", shop
        shopper.save(update_fields=["cart_id", "cart_shop", "updated_at"])
        self._checkout(shopper, shop, CARD_CODE, cart_id="gid://shopify/Cart/demo-card")
        self._checkout(shopper, shop, EFT_CODE, cart_id="gid://shopify/Cart/demo-eft")

        # Closed window: their last message was 25 hours ago, so a late "paid" must go out as the
        # template. Their order was told "received" back when the window was open.
        late = self._store_customer(tenant, account, WINDOW_CLOSED, last_message_at=now - timedelta(hours=25))
        self._checkout(
            late,
            shop,
            LATE_CODE,
            cart_id="gid://shopify/Cart/demo-late",
            order_id=LATE_ORDER_ID,
            received_message=self._update_sent(late.contact, "received", now - timedelta(hours=25)),
        )

        # To be forgotten: a paid order, until customers/redact deletes them.
        forgotten = self._store_customer(tenant, account, FORGOTTEN, last_message_at=now - timedelta(hours=1))
        self._checkout(
            forgotten,
            shop,
            FORGOTTEN_CODE,
            cart_id="gid://shopify/Cart/demo-forgotten",
            order_id=FORGOTTEN_ORDER_ID,
            received_message=self._update_sent(forgotten.contact, "received", now - timedelta(hours=1)),
            paid_message=self._update_sent(forgotten.contact, "paid", now - timedelta(hours=1)),
        )

        self.stdout.write(f"Store customer {WINDOW_OPEN[1]} (window open): checkouts {CARD_CODE} and {EFT_CODE}")
        self.stdout.write(f"Store customer {WINDOW_CLOSED[1]} (window closed): order {LATE_ORDER_ID}, received")
        self.stdout.write(f"Store customer {FORGOTTEN[1]} (to be forgotten): order {FORGOTTEN_ORDER_ID}, paid")

    @staticmethod
    def _store_customer(tenant, account, who, *, last_message_at):
        """
        One demo store customer on `account`: their contact, their one inbound message, sent at
        `last_message_at` (the 24-hour window counts from it, apps/whatsapp/services/window.py), and no
        updates sent to them yet.
        """
        bsuid, wa_id, name = who
        contact, _ = WhatsAppContact.objects.update_or_create(
            account=account, bsuid=bsuid, defaults={"wa_id": wa_id, "profile_name": name}
        )
        WhatsAppMessage.objects.update_or_create(
            wamid=f"wamid.DEMO{wa_id[-3:]}",
            defaults={
                "contact": contact,
                "direction": MessageDirection.INBOUND,
                "kind": MessageKind.TEXT,
                "payload": {"text": "Hi", "action_id": "", "flow_response": {}},
                "status": MessageStatus.RECEIVED,
                "sent_at": last_message_at,
            },
        )
        # The updates earlier runs of the checks queued, so each run starts with none.
        WhatsAppMessage.objects.filter(contact=contact, direction=MessageDirection.OUTBOUND).delete()
        store_customer, _ = StoreCustomer.objects.update_or_create(
            contact=contact, defaults={"tenant": tenant, "cart_id": "", "cart_shop": None}
        )
        return store_customer

    @staticmethod
    def _update_sent(contact, stage, when):
        """
        An order update Meta already sent the contact at `when`, as the stage's message (Step 4.7: a stage
        counts as sent once Meta accepts its message). _store_customer deletes it on the next run.
        """
        return WhatsAppMessage.objects.create(
            contact=contact,
            direction=MessageDirection.OUTBOUND,
            kind=MessageKind.TEXT,
            payload={"type": "text", "text": {"body": f"Demo order update: {stage}.", "preview_url": False}},
            status=MessageStatus.SENT,
            sent_at=when,
        )

    @staticmethod
    def _checkout(store_customer, shop, code, *, cart_id, **order):
        """
        A checkout with `code`, brought back to its demo state: no order yet, or the order in `order`
        (its id and each stage's message).
        """
        StoreCheckout.objects.update_or_create(
            code=code,
            defaults={
                "store_customer": store_customer,
                "shop": shop,
                "cart_id": cart_id,
                "order_id": None,
                "received_message": None,
                "paid_message": None,
                **order,
            },
        )
