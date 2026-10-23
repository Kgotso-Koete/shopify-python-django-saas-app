"""
Tests for reading a store's products from the Shopify Admin API (plan step 11, section 5.2).

The Admin API is never called: `admin_client_for` is replaced by a fake client whose `graphql()`
returns a canned response, as test_client.py does with `requests.post`.

Kind of test: integration (agents.md section 2.5). Why: products are read for a store row in the
test database, which is flagged when its token is rejected; the Shopify Admin API is faked.
"""

import pytest
from django.utils import timezone

from apps.shopify.client import ShopifyRefreshTokenRejected, ShopifyThrottledError
from apps.shopify.models import ShopifyShop

pytestmark = pytest.mark.django_db


def fetch_products(*args, **kwargs):
    # Imported here, not at the top, so a missing module fails each test instead of the whole file.
    from apps.shopify.products import fetch_products as real_fetch_products

    return real_fetch_products(*args, **kwargs)


def shopify_product(gid="gid://shopify/Product/1", title="Blue shirt", media=True, image_ready=True):
    """One product as the Admin API returns it (API version 2026-10, fields from section 5.2)."""
    featured_media = None
    if media:
        featured_media = {
            "preview": {
                "image": (
                    {"url": "https://cdn.shopify.com/blue-shirt.jpg", "altText": "A blue shirt"}
                    if image_ready
                    else None
                )
            }
        }
    return {
        "id": gid,
        "title": title,
        "handle": "blue-shirt",
        "status": "ACTIVE",
        "featuredMedia": featured_media,
        "priceRangeV2": {
            "minVariantPrice": {"amount": "19.99", "currencyCode": "ZAR"},
            "maxVariantPrice": {"amount": "24.50", "currencyCode": "ZAR"},
        },
    }


def products_response(nodes, has_next_page=False, has_previous_page=False):
    return {
        "products": {
            "nodes": nodes,
            "pageInfo": {
                "hasNextPage": has_next_page,
                "hasPreviousPage": has_previous_page,
                "startCursor": "cursor-start",
                "endCursor": "cursor-end",
            },
        }
    }


@pytest.fixture
def shop():
    return ShopifyShop.objects.create(shop_domain="products-demo.myshopify.com")


@pytest.fixture
def fake_client(mocker):
    client = mocker.Mock()
    client.graphql.return_value = products_response([shopify_product()])
    mocker.patch("apps.shopify.products.admin_client_for", return_value=client, create=True)
    return client


def sent_variables(fake_client):
    call = fake_client.graphql.call_args
    return call.kwargs.get("variables", call.args[1] if len(call.args) > 1 else None)


def sent_query(fake_client):
    call = fake_client.graphql.call_args
    return call.kwargs.get("query", call.args[0] if call.args else None)


def test_maps_a_page_of_products_to_plain_data(shop, fake_client):
    result = fetch_products(shop, first=12)

    assert result == {
        "products": [
            {
                "id": "gid://shopify/Product/1",
                "title": "Blue shirt",
                "handle": "blue-shirt",
                "status": "ACTIVE",
                "image_url": "https://cdn.shopify.com/blue-shirt.jpg",
                "image_alt": "A blue shirt",
                "price_min": "19.99",
                "price_max": "24.50",
                "currency_code": "ZAR",
            }
        ],
        "page_info": {
            "has_next_page": False,
            "has_previous_page": False,
            "start_cursor": "cursor-start",
            "end_cursor": "cursor-end",
        },
    }


def test_asks_shopify_for_current_fields_not_deprecated_ones(shop, fake_client):
    fetch_products(shop, first=12)

    query = sent_query(fake_client)
    assert "featuredMedia" in query
    assert "priceRangeV2" in query
    assert "featuredImage" not in query


@pytest.mark.parametrize(
    "featured_media",
    [
        pytest.param({"media": False}, id="no_media"),
        pytest.param({"image_ready": False}, id="image_not_processed_yet"),
    ],
)
def test_a_product_without_an_image_has_no_image_url(shop, fake_client, featured_media):
    fake_client.graphql.return_value = products_response([shopify_product(**featured_media)])

    product = fetch_products(shop, first=12)["products"][0]

    assert product["image_url"] is None
    assert product["image_alt"] is None


def test_first_page_sends_first_without_a_cursor(shop, fake_client):
    fetch_products(shop, first=12)

    assert sent_variables(fake_client) == {"first": 12}


def test_next_page_sends_first_with_after(shop, fake_client):
    fetch_products(shop, first=12, after="cursor-end")

    assert sent_variables(fake_client) == {"first": 12, "after": "cursor-end"}


def test_previous_page_sends_last_with_before(shop, fake_client):
    # Shopify pages backwards with last + before, not first + before (section 5.2).
    fetch_products(shop, first=12, before="cursor-start")

    assert sent_variables(fake_client) == {"last": 12, "before": "cursor-start"}


# Search, added for the WhatsApp menus (WhatsApp plan Step 1.12, asked for and approved on
# 2026-10-18). Free text in Shopify's `query` argument is "a case-insensitive search of multiple
# fields": https://shopify.dev/docs/api/admin-graphql/latest/queries/products


def test_a_search_sends_the_words_as_shopify_s_query(shop, fake_client):
    fetch_products(shop, first=7, query="blue shirt")

    assert sent_variables(fake_client) == {"first": 7, "query": "blue shirt"}
    assert "query: $query" in sent_query(fake_client)


def test_a_search_pages_like_any_list(shop, fake_client):
    fetch_products(shop, first=7, after="cursor-end", query="shirt")

    assert sent_variables(fake_client) == {"first": 7, "after": "cursor-end", "query": "shirt"}


@pytest.mark.parametrize("query", [None, "", "   "])
def test_no_search_words_means_no_query_as_before(shop, fake_client, query):
    # The website's products page passes none, so what it sends is unchanged.
    fetch_products(shop, first=12, query=query)

    assert sent_variables(fake_client) == {"first": 12}


# Newest first, added for the WhatsApp menus (WhatsApp plan Step 1.12b, chosen on 2026-10-20 for
# WhatsApp only). ProductSortKeys has CREATED_AT, and `reverse` reverses the order:
# https://shopify.dev/docs/api/admin-graphql/latest/queries/products


def test_newest_first_sorts_by_creation_date_reversed(shop, fake_client):
    fetch_products(shop, first=7, newest_first=True)

    assert sent_variables(fake_client) == {"first": 7, "sortKey": "CREATED_AT", "reverse": True}
    assert "sortKey: $sortKey" in sent_query(fake_client)
    assert "reverse: $reverse" in sent_query(fake_client)


def test_newest_first_pages_and_searches_like_any_list(shop, fake_client):
    fetch_products(shop, first=7, before="cursor-start", query="shirt", newest_first=True)

    assert sent_variables(fake_client) == {
        "last": 7,
        "before": "cursor-start",
        "query": "shirt",
        "sortKey": "CREATED_AT",
        "reverse": True,
    }


def test_without_newest_first_no_order_is_sent_as_before(shop, fake_client):
    # The website's products page doesn't ask for it, so its order is unchanged.
    fetch_products(shop, first=12, newest_first=False)

    assert sent_variables(fake_client) == {"first": 12}


def test_page_info_comes_back_unchanged(shop, fake_client):
    fake_client.graphql.return_value = products_response(
        [shopify_product()], has_next_page=True, has_previous_page=True
    )

    page_info = fetch_products(shop, first=12, after="cursor-end")["page_info"]

    assert page_info == {
        "has_next_page": True,
        "has_previous_page": True,
        "start_cursor": "cursor-start",
        "end_cursor": "cursor-end",
    }


def test_page_size_above_50_is_capped(shop, fake_client):
    fetch_products(shop, first=200)

    assert sent_variables(fake_client) == {"first": 50}


# ---------------------------------------------------------------------------
# A store that can't be used (section 5.2 cases 7 to 9)
# ---------------------------------------------------------------------------


def products_module():
    # Read from the module, so a missing error class fails the test that needs it, not the file.
    from apps.shopify import products

    return products


@pytest.mark.parametrize(
    "store_state",
    [
        pytest.param({"uninstalled_at": timezone.now()}, id="uninstalled"),
        pytest.param({"needs_reinstall": True}, id="needs_reinstall"),
    ],
)
def test_a_store_that_must_be_reconnected_makes_no_api_call(shop, mocker, store_state):
    get_client = mocker.patch("apps.shopify.products.admin_client_for")
    for field, value in store_state.items():
        setattr(shop, field, value)
    shop.save()

    with pytest.raises(products_module().ShopifyReconnectRequired):
        fetch_products(shop, first=12)

    get_client.assert_not_called()


def test_a_rejected_refresh_token_asks_to_reconnect_the_store(shop, mocker):
    mocker.patch(
        "apps.shopify.products.admin_client_for",
        side_effect=ShopifyRefreshTokenRejected("Refresh token rejected"),
    )

    with pytest.raises(products_module().ShopifyReconnectRequired):
        fetch_products(shop, first=12)


def test_a_throttled_call_asks_to_try_again_shortly(shop, fake_client):
    fake_client.graphql.side_effect = ShopifyThrottledError("GraphQL errors: [throttled]")

    with pytest.raises(products_module().ShopifyTryAgainLater):
        fetch_products(shop, first=12)


def test_the_error_messages_are_fixed_texts_without_shopify_details(shop, mocker, fake_client):
    # The messages reach the browser, so they say what to do and carry nothing from Shopify's reply.
    fake_client.graphql.side_effect = ShopifyThrottledError('GraphQL errors: [{"secret": "acc_token"}]')
    with pytest.raises(products_module().ShopifyTryAgainLater) as throttled:
        fetch_products(shop, first=12)

    mocker.patch(
        "apps.shopify.products.admin_client_for",
        side_effect=ShopifyRefreshTokenRejected("Refresh token rejected for ref_secret"),
    )
    with pytest.raises(products_module().ShopifyReconnectRequired) as reconnect:
        fetch_products(shop, first=12)

    for error in (throttled.value, reconnect.value):
        assert "acc_token" not in str(error)
        assert "ref_secret" not in str(error)
        assert "GraphQL" not in str(error)
