from django.db import models


class Channel(models.TextChoices):
    """
    How a code proves the number (plan decision D20). Each value is its member's name (WhatsApp plan
    Step 1.16, agents.md section 5.3b).
    """

    # The website shows the code and the person sends it from the number; Meta's signed webhook
    # proves the number. Needs no template and no provider (Step 1.7).
    WHATSAPP_INBOUND = "WHATSAPP_INBOUND", "Sent from WhatsApp"
    # We send the code in a WhatsApp authentication template and it's typed on the website (phase 6).
    WHATSAPP_TEMPLATE = "WHATSAPP_TEMPLATE", "Received on WhatsApp"
    # We send the code by SMS through an optional provider (phase 6).
    SMS = "SMS", "Received by SMS"
