# WhatsApp plan Step 4.7, user story WA.D3.OM.J2.A2: each template's review status, asked of Meta. Templates
# stored before it start in review with no check yet, so the next check (the daily one, or the WhatsApp page
# opening) asks Meta about them.

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ('whatsapp', '0021_alter_whatsappmessage_kind_whatsapptemplate'),
    ]

    operations = [
        migrations.AddField(
            model_name='whatsapptemplate',
            name='status',
            field=models.CharField(
                choices=[
                    ('IN_REVIEW', 'In review'),
                    ('APPROVED', 'Approved'),
                    ('REJECTED', 'Rejected'),
                    ('PAUSED', 'Paused'),
                    ('DISABLED', 'Disabled'),
                ],
                default='IN_REVIEW',
                max_length=32,
            ),
        ),
        migrations.AddField(
            model_name='whatsapptemplate',
            name='rejected_reason',
            field=models.CharField(blank=True, default='', max_length=64),
        ),
        migrations.AddField(
            model_name='whatsapptemplate',
            name='status_checked_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
    ]
