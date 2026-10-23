"""
Issuing and checking one-time phone codes (plan decision D20, Step 1.7a).

A 6-digit code is too short to carry its own signature, unlike the email confirmation token in
apps/users/tokens.py, so it's stored, as a keyed hash: HMAC-SHA256 with the Django secret key, over
the number, the channel and the code. A leaked database row then reveals nothing, and a code is only
ever valid for the number and channel it was issued for.
"""

import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta

from django.db import transaction
from django.db.models import F
from django.utils import timezone
from django.utils.crypto import constant_time_compare, salted_hmac

from .models import PhoneVerificationCode

# Wrong guesses allowed per code before it's voided; with 10^6 possible codes, a guesser has a 5 in
# a million chance.
MAX_ATTEMPTS = 5
CODE_DIGITS = 6
HASH_SALT = "apps.phone_verification.code"


class CodeCheckError(Exception):
    """A code that didn't prove anything. `code` is "no_code" (none open for this number) or "wrong_code"."""

    def __init__(self, message: str, code: str):
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class IssuedCode:
    """A new code: shown to the user once, never stored as it is."""

    code: str
    expires_at: datetime


@transaction.atomic
def issue_code(*, user, phone_number: str, channel: str, ttl_seconds: int) -> IssuedCode:
    """Issue a new code for `user`, voiding their older unused ones."""
    now = timezone.now()
    PhoneVerificationCode.objects.filter(user=user, consumed_at__isnull=True).update(consumed_at=now)

    code = f"{secrets.randbelow(10**CODE_DIGITS):0{CODE_DIGITS}d}"
    expires_at = now + timedelta(seconds=ttl_seconds)
    PhoneVerificationCode.objects.create(
        user=user,
        phone_number=phone_number,
        channel=channel,
        code_hash=_hash(phone_number, channel, code),
        expires_at=expires_at,
    )
    return IssuedCode(code=code, expires_at=expires_at)


def check_code(*, phone_number: str, channel: str, code: str):
    """
    Use `code`, sent or typed for `phone_number` on `channel`, and return the user it was issued to.
    Raises CodeCheckError if no open code matches. A wrong guess counts against every open code for
    the number and channel, and a code is voided at MAX_ATTEMPTS.
    """
    # The error is raised only after the transaction: raised inside it, it would roll back the
    # wrong-guess count, and guesses would never add up.
    user, error = _use_code(phone_number, channel, code.strip())
    if error is not None:
        raise error
    return user


@transaction.atomic
def _use_code(phone_number: str, channel: str, code: str):
    now = timezone.now()
    open_codes = list(
        PhoneVerificationCode.objects.select_for_update()
        .filter(phone_number=phone_number, channel=channel, consumed_at__isnull=True, expires_at__gt=now)
        .select_related("user")
    )
    if not open_codes:
        return None, CodeCheckError("There's no open code for this number. Ask for a new one.", "no_code")

    expected = _hash(phone_number, channel, code)
    for candidate in open_codes:
        if constant_time_compare(candidate.code_hash, expected):
            candidate.consumed_at = now
            candidate.save(update_fields=["consumed_at", "updated_at"])
            return candidate.user, None

    ids = [candidate.pk for candidate in open_codes]
    PhoneVerificationCode.objects.filter(pk__in=ids).update(attempts=F("attempts") + 1)
    PhoneVerificationCode.objects.filter(pk__in=ids, attempts__gte=MAX_ATTEMPTS).update(consumed_at=now)
    return None, CodeCheckError("That code isn't right.", "wrong_code")


def _hash(phone_number: str, channel: str, code: str) -> str:
    return salted_hmac(HASH_SALT, f"{phone_number}:{channel}:{code}", algorithm="sha256").hexdigest()
