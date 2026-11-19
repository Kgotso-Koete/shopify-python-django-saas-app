# WhatsApp plan Step 4.7, user story WA.D5.SY.J1.A1: each order stage keeps its message, and counts as sent
# only once Meta accepts it, replacing when each stage was queued. Not released yet (Step 4.3c), so a stage
# queued before this, on a development database, simply has no message.

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ('whatsapp', '0023_whatsapptemplate_reported_at'),
        ('whatsapp_shop', '0005_storecheckout_order_link_token'),
    ]

    operations = [
        migrations.RemoveField(
            model_name='storecheckout',
            name='received_sent_at',
        ),
        migrations.RemoveField(
            model_name='storecheckout',
            name='paid_sent_at',
        ),
        migrations.AddField(
            model_name='storecheckout',
            name='received_message',
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='+',
                to='whatsapp.whatsappmessage',
            ),
        ),
        migrations.AddField(
            model_name='storecheckout',
            name='paid_message',
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='+',
                to='whatsapp.whatsappmessage',
            ),
        ),
    ]
