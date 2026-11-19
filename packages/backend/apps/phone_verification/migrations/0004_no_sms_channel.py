# WhatsApp plan, user story WA.D1.OM.J1.A3 (maintainer's decision, 2026-11-09): no SMS channel; a member proves
# their number on WhatsApp. No code was ever issued by SMS (the channel was never built), so no row holds it.

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ('phone_verification', '0003_alter_phoneverificationcode_channel'),
    ]

    operations = [
        migrations.AlterField(
            model_name='phoneverificationcode',
            name='channel',
            field=models.CharField(
                choices=[
                    ('WHATSAPP_INBOUND', 'Sent from WhatsApp'),
                    ('WHATSAPP_TEMPLATE', 'Received on WhatsApp'),
                ],
                max_length=32,
            ),
        ),
    ]
