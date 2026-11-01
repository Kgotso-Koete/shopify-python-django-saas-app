from django.db import models


class Feature(models.TextChoices):
    """
    A part of the app a plan can include (WhatsApp plan phase 3, decision 1). Stored with exactly its
    member names (agents.md section 5.3b). Checks always ask about one feature, never about a plan's
    name, so a later plan can include some features and not others without changing a check.
    """

    SHOPIFY = "SHOPIFY", "Shopify"
    WHATSAPP = "WHATSAPP", "WhatsApp"
