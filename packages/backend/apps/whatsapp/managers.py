"""
Model managers for the WhatsApp app.
"""

from django.db import models

from .constants import TEAM_PURPOSES


class WhatsAppAccountManager(models.Manager):
    def internal_for(self, tenant):
        """
        The organization's number its team texts (plan Step 1.17): internal, or serving both (Step 2.7),
        or None before it connects one. A database constraint keeps at most one active.
        """
        return self.filter(tenant=tenant, purpose__in=TEAM_PURPOSES, is_active=True).first()
