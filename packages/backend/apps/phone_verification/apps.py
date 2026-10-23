from django.apps import AppConfig


class PhoneVerificationConfig(AppConfig):
    """
    One-time codes that prove a person controls a phone number (plan decision D20).

    Channel-neutral: it knows nothing about WhatsApp or SMS. Each channel plugs in by issuing and
    checking codes with its own Channel value, so deleting one channel leaves the others working.
    See docs/superpowers/plans/2026-10-06-whatsapp-first-channel-plan.md.
    """

    name = "apps.phone_verification"
    verbose_name = "Phone verification"
