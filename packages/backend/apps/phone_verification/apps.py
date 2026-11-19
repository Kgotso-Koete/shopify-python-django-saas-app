from django.apps import AppConfig


class PhoneVerificationConfig(AppConfig):
    """
    One-time codes that prove a person controls a phone number (plan decision D20).

    Channel-neutral: it knows nothing about WhatsApp. Each channel plugs in by issuing and checking
    codes with its own Channel value, so deleting one channel leaves the others working. Both channels
    are WhatsApp's; there's no SMS (maintainer's decision, 2026-11-09).
    See docs/superpowers/plans/2026-10-06-whatsapp-first-channel-plan.md.
    """

    name = "apps.phone_verification"
    verbose_name = "Phone verification"
