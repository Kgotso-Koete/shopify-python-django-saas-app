import hmac
import hashlib
import base64
import re
from typing import Dict, Any, Optional

# Shop domain validation regex (anchored to prevent prefix/suffix attacks)
# e.g. "my-store.myshopify.com"
SHOP_DOMAIN_REGEX = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9\-]*\.myshopify\.com$")


def is_valid_shop_domain(shop: Optional[str]) -> bool:
    """
    Check if the shop domain looks like a valid Shopify domain.
    Shopify domain should be just the hostname, e.g. "my-store.myshopify.com",
    no protocol, no trailing slash.
    """
    if not shop:
        return False
    return bool(SHOP_DOMAIN_REGEX.match(shop.lower()))


def verify_query_hmac(query_dict: Dict[str, Any], secret: str) -> bool:
    """
    Verify the HMAC provided in a Shopify callback/install query string.
    The secret is usually SHOPIFY_API_SECRET.
    query_dict is the dict representation of the query parameters.
    """
    if "hmac" not in query_dict:
        return False

    # Make a copy since we need to remove hmac (and signature if it exists)
    params = query_dict.copy()
    provided_hmac = params.pop("hmac")
    # Some older flows might include signature, but modern OAuth just uses hmac
    params.pop("signature", None)

    # Sort parameters by key
    sorted_params = []
    for k in sorted(params.keys()):
        v = params[k]
        # In Django request.GET, values might be lists if there are multiple keys
        if isinstance(v, list):
            v = v[0]

        # Shopify's specific encoding rules for HMAC validation:
        # Keys: replace % with %25, & with %26, = with %3D
        encoded_k = str(k).replace("%", "%25").replace("&", "%26").replace("=", "%3D")
        # Values: replace % with %25, & with %26
        encoded_v = str(v).replace("%", "%25").replace("&", "%26")

        sorted_params.append(f"{encoded_k}={encoded_v}")

    query_string = "&".join(sorted_params)

    calculated_hmac = hmac.new(secret.encode("utf-8"), query_string.encode("utf-8"), hashlib.sha256).hexdigest()

    return hmac.compare_digest(calculated_hmac, provided_hmac)


def verify_webhook_hmac(raw_body: bytes, provided_hmac: Optional[str], secret: str) -> bool:
    """
    Verify the HMAC of an incoming Shopify webhook.
    Shopify signs the raw body of the request.
    The secret is usually SHOPIFY_API_SECRET.
    provided_hmac is the value of the X-Shopify-Hmac-Sha256 header.
    """
    if not provided_hmac:
        return False

    calculated_hmac = base64.b64encode(hmac.new(secret.encode("utf-8"), raw_body, hashlib.sha256).digest()).decode(
        "utf-8"
    )

    return hmac.compare_digest(calculated_hmac, provided_hmac)
