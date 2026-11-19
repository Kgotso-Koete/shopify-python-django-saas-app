# WhatsApp plan Step 4.7, user story WA.D7.OP.J2.A1: when the operator was emailed about a template's rejection.

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ('whatsapp', '0022_whatsapptemplate_status'),
    ]

    operations = [
        migrations.AddField(
            model_name='whatsapptemplate',
            name='reported_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
    ]
