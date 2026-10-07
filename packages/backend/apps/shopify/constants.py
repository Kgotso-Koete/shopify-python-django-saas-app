"""
Constants for the Shopify app.

Webhook topic names and the refresh margin (how far before expiry to refresh a token).
"""

# Webhook topics that the app subscribes to, matching the shopify.app.toml subscriptions.
TOPIC_APP_UNINSTALLED = "app/uninstalled"
TOPIC_SHOP_REDACT = "shop/redact"
TOPIC_CUSTOMERS_REDACT = "customers/redact"
TOPIC_CUSTOMERS_DATA_REQUEST = "customers/data_request"

# How many seconds before expiry to trigger a token refresh (section 2.6 of the plan).
# If the access token expires in fewer than this many seconds, admin_client_for() refreshes it.
REFRESH_MARGIN_SECONDS = 300  # 5 minutes
