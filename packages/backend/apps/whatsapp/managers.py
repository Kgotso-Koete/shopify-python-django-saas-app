"""
Model managers for the WhatsApp app.
"""

from django.db import models

from .constants import AccountPurpose


class WhatsAppAccountManager(models.Manager):
    def internal_for(self, tenant):
        """
        The organization's internal communications number, the one its team texts (plan Step 1.17),
        or None before it connects one. A database constraint keeps at most one active.
        """
        return self.filter(tenant=tenant, purpose=AccountPurpose.INTERNAL_COMMUNICATIONS, is_active=True).first()
