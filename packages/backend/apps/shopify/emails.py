"""
Emails to the operator about Shopify webhooks (WhatsApp plan, user story WA.D7.OP.J2.A2), sent through upstream's
email system (common/emails.py) to settings.OPERATOR_EMAILS. The template is webapp-emails'
SHOPIFY_WEBHOOKS_UNHANDLED.
"""

from rest_framework import serializers

from common import emails


class UnhandledDeliverySerializer(serializers.Serializer):
    webhook_id = serializers.CharField()
    topic = serializers.CharField()
    shop_domain = serializers.CharField()
    received_at = serializers.DateTimeField()
    last_error = serializers.CharField(allow_blank=True)


class ShopifyWebhooksUnhandledEmailSerializer(serializers.Serializer):
    deliveries = UnhandledDeliverySerializer(many=True)


class ShopifyWebhooksUnhandledEmail(emails.Email):
    """The webhooks the sweep gave up on, each with its shop, topic, when it came and its last error."""

    name = "SHOPIFY_WEBHOOKS_UNHANDLED"
    serializer_class = ShopifyWebhooksUnhandledEmailSerializer
