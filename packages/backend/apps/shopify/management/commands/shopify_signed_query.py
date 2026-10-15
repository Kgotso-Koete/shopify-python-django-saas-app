import hashlib
import hmac
import urllib.parse
from django.core.management.base import BaseCommand
from django.conf import settings


def _sign_query(params: dict, secret: str) -> str:
    """
    Sign a query the way Shopify does, so verification.verify_query_hmac accepts it: the parameters sorted
    by key, with Shopify's escaping, joined with &, then HMAC-SHA256 in hex. A copy of the tests' helper
    (apps/shopify/tests/test_views.py); verification.py only verifies, it has no signing function.
    """
    sorted_parts = []
    for k in sorted(params.keys()):
        v = params[k]
        encoded_k = str(k).replace("%", "%25").replace("&", "%26").replace("=", "%3D")
        encoded_v = str(v).replace("%", "%25").replace("&", "%26")
        sorted_parts.append(f"{encoded_k}={encoded_v}")
    query_string = "&".join(sorted_parts)
    return hmac.new(secret.encode("utf-8"), query_string.encode("utf-8"), hashlib.sha256).hexdigest()


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
