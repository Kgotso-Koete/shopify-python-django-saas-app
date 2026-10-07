import urllib.parse
from django.core.management.base import BaseCommand
from django.conf import settings

from apps.shopify.verification import _sign_query


class Command(BaseCommand):
    help = "Generate a signed Shopify callback or install query for testing."

    def add_arguments(self, parser):
        parser.add_argument("--shop", required=True, type=str, help="Shop domain (e.g., test.myshopify.com)")
        parser.add_argument("--code", type=str, help="OAuth code (for callback)")
        parser.add_argument("--state", type=str, help="State nonce (for callback)")
        parser.add_argument("--timestamp", type=str, default="1234567890", help="Timestamp")

    def handle(self, *args, **options):
        params = {
            "shop": options["shop"],
            "timestamp": options["timestamp"],
        }
        if options["code"]:
            params["code"] = options["code"]
        if options["state"]:
            params["state"] = options["state"]

        hmac_val = _sign_query(params, settings.SHOPIFY_API_SECRET)
        params["hmac"] = hmac_val

        qs = urllib.parse.urlencode(params)

        self.stdout.write(self.style.SUCCESS("Signed Query:"))
        self.stdout.write(qs)

        if options["code"]:
            self.stdout.write("\nFor callback_view:")
            self.stdout.write(f"/api/shopify/auth/callback/?{qs}")
        else:
            self.stdout.write("\nFor install_view:")
            self.stdout.write(f"/api/shopify/install/?{qs}")
