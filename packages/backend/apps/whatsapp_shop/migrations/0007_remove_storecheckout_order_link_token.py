# WhatsApp plan Step 4.7, decision 30: the View order link (Step 4.3d, decision 23) is replaced by the order's
# details in the chat, so its token goes. Not released yet, so only development databases held tokens.

from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ('whatsapp_shop', '0006_storecheckout_stage_messages'),
    ]

    operations = [
        migrations.RemoveField(
            model_name='storecheckout',
            name='order_link_token',
        ),
    ]
