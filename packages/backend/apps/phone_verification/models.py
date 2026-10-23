from django.conf import settings
from django.db import models

from common.models import TimestampedMixin

from .constants import Channel


class PhoneVerificationCode(TimestampedMixin, models.Model):
    """
    One code issued to a user for one phone number and one channel (plan decision D20). Only a keyed
    hash of the code is kept; the code itself is shown once. Issuing a new code voids the user's
    older unused ones (services.issue_code).
    """

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="phone_codes")
    # International digits, no "+", e.g. "27831234567" (plan D19).
    phone_number = models.CharField(max_length=15)
    channel = models.CharField(max_length=32, choices=Channel.choices)
    # HMAC-SHA256 hex of the code, keyed with the Django secret key and bound to the number and channel.
    code_hash = models.CharField(max_length=64)
    expires_at = models.DateTimeField()
    # Set when the code was used, or voided by a newer code or by too many wrong guesses.
    consumed_at = models.DateTimeField(null=True, blank=True)
    # Wrong guesses so far; at services.MAX_ATTEMPTS the code is voided.
    attempts = models.PositiveSmallIntegerField(default=0)

    class Meta:
        indexes = [models.Index(fields=["phone_number", "channel"])]

    def __str__(self) -> str:
        return f"{self.get_channel_display()} code for {self.phone_number}"
