"""
Tests for apps/shopify/storefront.py: a store's products and carts through Shopify's Storefront API,
for its WhatsApp customers (WhatsApp plan Step 2.2, phase 2 decisions 1 and 3).

- the store's Admin token is sent as a private Storefront token (WhatsApp plan Step 2.1b, decision 1)
- browsing lists products for sale only, newest first; searching hides those not for sale
- a product's variants are those for sale
- carts: created with the customer's phone when known, lines added, read back, or gone
- a store that must be reconnected, Shopify being busy, and Shopify refusing a cart change each raise
  their own error

Shopify is never called: requests.post is replaced by a fake that returns canned Storefront replies.

Kind of test: integration (agents.md section 2.5). Why: products and carts are read for a store row
in the test database, which is flagged when its token is rejected; Shopify's HTTP API is faked.
"""

import pytest
from django.utils import timezone

from apps.shopify.client import ShopifyAPIError, ShopifyRefreshTokenRejected
from apps.shopify.models import ShopifyShop
from apps.shopify.products import ShopifyReconnectRequired, ShopifyTryAgainLater

pytestmark = pytest.mark.django_db


def storefront():
    # Imported here, not at the top, so a missing module fails each test instead of the whole file.
    from apps.shopify import storefront as module

    return module


def product_node(gid="gid://shopify/Product/1", title="Blue shirt", image=True, variants=None):
    """One product as the Storefront API returns it (API version 2026-10)."""
    return {
        "__typename": "Product",
        "id": gid,
        "title": title,
        "description": "A soft cotton shirt.",
        "availableForSale": True,
        "featuredImage": {"url": "https://cdn.shopify.com/blue-shirt.jpg", "altText": "A blue shirt"}
        if image
        else None,
        "priceRange": {
            "minVariantPrice": {"amount": "19.99", "currencyCode": "USD"},
            "maxVariantPrice": {"amount": "24.5", "currencyCode": "USD"},
        },
        "variants": {"nodes": variants if variants is not None else [variant_node()]},
    }


def variant_node(gid="gid://shopify/ProductVariant/11", title="Default Title", available=True, amount="19.99"):
    return {
        "id": gid,
        "title": title,
        "availableForSale": available,
        "price": {"amount": amount, "currencyCode": "USD"},
    }


def page_info(has_next_page=False, has_previous_page=False):
    return {
        "hasNextPage": has_next_page,
        "hasPreviousPage": has_previous_page,
        "startCursor": "cursor-start",
        "endCursor": "cursor-end",
    }


def cart_node(lines=None):
    return {
        "id": "gid://shopify/Cart/abc",
        "checkoutUrl": "https://demo.myshopify.com/cart/c/abc?key=secret",
        "totalQuantity": sum(line["quantity"] for line in (lines or [])),
        "cost": {"totalAmount": {"amount": "39.98", "currencyCode": "USD"}},
        "lines": {"nodes": lines or []},
    }


def cart_line(quantity=2, product="Blue shirt", variant="Large"):
    return {
        "id": "gid://shopify/CartLine/1",
        "quantity": quantity,
        "cost": {"totalAmount": {"amount": "39.98", "currencyCode": "USD"}},
        "merchandise": {"id": "gid://shopify/ProductVariant/11", "title": variant, "product": {"title": product}},
    }


@pytest.fixture
def shop():
    shop = ShopifyShop(shop_domain="demo.myshopify.com", scopes="read_products")
    shop.access_token = "admin-token"
    shop.save()
    return shop


@pytest.fixture
def shopify(mocker):
    """The fake Storefront endpoint: set .reply to the `data` it answers with."""
    post = mocker.patch("apps.shopify.storefront.requests.post")

    def answer(data=None, *, errors=None, status=200):
        response = mocker.Mock(ok=status < 400, status_code=status, text="{}")
        body = {"data": data} if errors is None else {"errors": errors}
        response.json.return_value = body
        post.return_value = response

    post.reply = answer
    return post


def sent(shopify):
    """What our code sent: the URL, the headers and the GraphQL variables."""
    call = shopify.call_args
    return call.args[0], call.kwargs["headers"], call.kwargs["json"].get("variables", {})


class TestTheRequest:
    def test_the_admin_token_goes_as_a_private_storefront_token(self, shop, shopify, settings):
        settings.SHOPIFY_API_VERSION = "2026-10"
        shopify.reply({"products": {"nodes": [], "pageInfo": page_info()}})

        storefront().list_products(shop, first=7)

        url, headers, _ = sent(shopify)
        assert url == "https://demo.myshopify.com/api/2026-10/graphql.json"
        assert headers["Shopify-Storefront-Private-Token"] == "admin-token"
        assert "X-Shopify-Access-Token" not in headers

    def test_a_store_that_must_be_reconnected_isnt_asked(self, shop, shopify):
        shop.uninstalled_at = timezone.now()
        shop.save()

        with pytest.raises(ShopifyReconnectRequired):
            storefront().list_products(shop, first=7)
        shopify.assert_not_called()

    def test_a_rejected_refresh_token_means_reconnect(self, shop, shopify, mocker):
        mocker.patch("apps.shopify.storefront.admin_client_for", side_effect=ShopifyRefreshTokenRejected("no"))

        with pytest.raises(ShopifyReconnectRequired):
            storefront().list_products(shop, first=7)

    def test_a_throttled_request_means_try_again_later(self, shop, shopify):
        shopify.reply(errors=[{"message": "Throttled", "extensions": {"code": "THROTTLED"}}])

        with pytest.raises(ShopifyTryAgainLater):
            storefront().list_products(shop, first=7)

    def test_other_errors_are_api_errors(self, shop, shopify):
        shopify.reply(status=500)

        with pytest.raises(ShopifyAPIError):
            storefront().list_products(shop, first=7)


class TestBrowsing:
    def test_products_for_sale_newest_first_as_plain_dicts(self, shop, shopify):
        shopify.reply({"products": {"nodes": [product_node()], "pageInfo": page_info(has_next_page=True)}})

        page = storefront().list_products(shop, first=7)

        _, _, variables = sent(shopify)
        assert variables == {"first": 7, "query": "available_for_sale:true", "sortKey": "CREATED_AT", "reverse": True}
        assert page["products"] == [
            {
                "id": "gid://shopify/Product/1",
                "title": "Blue shirt",
                "description": "A soft cotton shirt.",
                "image_url": "https://cdn.shopify.com/blue-shirt.jpg",
                "price_min": "19.99",
                "price_max": "24.5",
                "currency_code": "USD",
            }
        ]
        assert page["page_info"] == {
            "has_next_page": True,
            "has_previous_page": False,
            "start_cursor": "cursor-start",
            "end_cursor": "cursor-end",
        }

    def test_paging_back_asks_for_the_last_ones_before_the_cursor(self, shop, shopify):
        shopify.reply({"products": {"nodes": [], "pageInfo": page_info()}})

        storefront().list_products(shop, first=7, before="cursor-start")

        _, _, variables = sent(shopify)
        assert variables["last"] == 7
        assert variables["before"] == "cursor-start"
        assert "first" not in variables

    def test_a_product_without_a_picture_has_none(self, shop, shopify):
        shopify.reply({"products": {"nodes": [product_node(image=False)], "pageInfo": page_info()}})

        [product] = storefront().list_products(shop, first=7)["products"]

        assert product["image_url"] is None


class TestSearching:
    def test_the_words_search_products_for_sale_only(self, shop, shopify):
        shopify.reply(
            {
                "search": {
                    # Search can return pages and articles too; only products are kept.
                    "nodes": [product_node(), {"__typename": "Page"}],
                    "pageInfo": page_info(),
                }
            }
        )

        page = storefront().search_products(shop, "blue shirt", first=7, after="cursor-end")

        _, _, variables = sent(shopify)
        assert variables == {"query": "blue shirt", "first": 7, "after": "cursor-end"}
        assert [product["title"] for product in page["products"]] == ["Blue shirt"]
        query = shopify.call_args.kwargs["json"]["query"]
        assert "types: [PRODUCT]" in query
        assert "productFilters: [{available: true}]" in query
        assert "unavailableProducts: HIDE" in query


class TestAProduct:
    def test_its_variants_for_sale(self, shop, shopify):
        variants = [
            variant_node("gid://shopify/ProductVariant/11", "Small"),
            variant_node("gid://shopify/ProductVariant/12", "Large", available=False),
            variant_node("gid://shopify/ProductVariant/13", "XL", amount="24.5"),
        ]
        shopify.reply({"product": product_node(variants=variants)})

        product = storefront().get_product(shop, "gid://shopify/Product/1")

        _, _, variables = sent(shopify)
        assert variables == {"id": "gid://shopify/Product/1"}
        assert product["title"] == "Blue shirt"
        assert product["variants"] == [
            {"id": "gid://shopify/ProductVariant/11", "title": "Small", "price": "19.99", "currency_code": "USD"},
            {"id": "gid://shopify/ProductVariant/13", "title": "XL", "price": "24.5", "currency_code": "USD"},
        ]

    def test_one_shopify_no_longer_has_is_none(self, shop, shopify):
        shopify.reply({"product": None})

        assert storefront().get_product(shop, "gid://shopify/Product/1") is None


class TestCarts:
    def test_a_new_cart_carries_the_customers_phone(self, shop, shopify):
        shopify.reply({"cartCreate": {"cart": cart_node([cart_line(quantity=1)]), "userErrors": [], "warnings": []}})

        cart = storefront().create_cart(shop, "gid://shopify/ProductVariant/11", phone="+27000001001")

        _, _, variables = sent(shopify)
        # No country: the store's own default applies (Step 2.1b, decision 2).
        assert variables == {
            "input": {
                "lines": [{"merchandiseId": "gid://shopify/ProductVariant/11", "quantity": 1}],
                "buyerIdentity": {"phone": "+27000001001"},
            }
        }
        assert cart["id"] == "gid://shopify/Cart/abc"
        assert cart["checkout_url"] == "https://demo.myshopify.com/cart/c/abc?key=secret"

    def test_without_a_phone_the_cart_has_no_buyer(self, shop, shopify):
        shopify.reply({"cartCreate": {"cart": cart_node(), "userErrors": [], "warnings": []}})

        storefront().create_cart(shop, "gid://shopify/ProductVariant/11", phone=None)

        _, _, variables = sent(shopify)
        assert "buyerIdentity" not in variables["input"]

    def test_a_line_is_added_to_a_cart(self, shop, shopify):
        shopify.reply({"cartLinesAdd": {"cart": cart_node([cart_line()]), "userErrors": [], "warnings": []}})

        cart = storefront().add_to_cart(shop, "gid://shopify/Cart/abc", "gid://shopify/ProductVariant/11")

        _, _, variables = sent(shopify)
        assert variables == {
            "cartId": "gid://shopify/Cart/abc",
            "lines": [{"merchandiseId": "gid://shopify/ProductVariant/11", "quantity": 1}],
        }
        assert cart["total_quantity"] == 2

    def test_a_cart_is_read_back_as_plain_dicts(self, shop, shopify):
        shopify.reply({"cart": cart_node([cart_line()])})

        cart = storefront().get_cart(shop, "gid://shopify/Cart/abc")

        assert cart == {
            "id": "gid://shopify/Cart/abc",
            "checkout_url": "https://demo.myshopify.com/cart/c/abc?key=secret",
            "total_quantity": 2,
            "total_amount": "39.98",
            "currency_code": "USD",
            "lines": [{"title": "Blue shirt", "variant": "Large", "quantity": 2, "amount": "39.98"}],
        }

    def test_a_cart_shopify_no_longer_has_is_none(self, shop, shopify):
        # Carts expire within 30 days, and are deleted once their checkout is completed.
        shopify.reply({"cart": None})

        assert storefront().get_cart(shop, "gid://shopify/Cart/abc") is None

    def test_shopify_refusing_a_change_says_why(self, shop, shopify):
        errors = [{"field": ["lines"], "message": "The merchandise is sold out.", "code": "INVALID"}]
        shopify.reply({"cartLinesAdd": {"cart": None, "userErrors": errors, "warnings": []}})

        with pytest.raises(storefront().ShopifyCartError, match="sold out"):
            storefront().add_to_cart(shop, "gid://shopify/Cart/abc", "gid://shopify/ProductVariant/11")

    def test_a_dropped_line_says_why(self, shop, shopify):
        # Shopify sets an unavailable line to 0 and says so only in a warning (Step 2.1a, result 6).
        warnings = [{"code": "MERCHANDISE_OUT_OF_STOCK", "message": "The product is already sold out.", "target": "x"}]
        shopify.reply({"cartCreate": {"cart": cart_node(), "userErrors": [], "warnings": warnings}})

        with pytest.raises(storefront().ShopifyCartError, match="already sold out"):
            storefront().create_cart(shop, "gid://shopify/ProductVariant/11", phone=None)
