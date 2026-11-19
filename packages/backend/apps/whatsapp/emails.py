"""
Emails to the operator about message templates a business can't use (WhatsApp plan Step 4.7, user story
WA.D7.OP.J2.A1), sent through upstream's email system (common/emails.py) to settings.OPERATOR_EMAILS. The
template is webapp-emails' WHATSAPP_TEMPLATES_REFUSED.
"""

from rest_framework import serializers

from common import emails


class TemplateProblemSerializer(serializers.Serializer):
    # The business's organization, the number, the template's name, and what Meta said.
    organization = serializers.CharField()
    number = serializers.CharField()
    template = serializers.CharField()
    reason = serializers.CharField()


class WhatsAppTemplatesRefusedEmailSerializer(serializers.Serializer):
    problems = TemplateProblemSerializer(many=True)


class WhatsAppTemplatesRefusedEmail(emails.Email):
    """Templates Meta rejected, or submissions it refused, each with its business, number and Meta's reason."""

    name = "WHATSAPP_TEMPLATES_REFUSED"
    serializer_class = WhatsAppTemplatesRefusedEmailSerializer
