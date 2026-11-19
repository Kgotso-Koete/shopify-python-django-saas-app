# WhatsApp plan phase 7, user story WA.D1.OM.J1.A3: a phone proved with a typed code, linked when it first writes.

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ('whatsapp', '0023_whatsapptemplate_reported_at'),
    ]

    operations = [
        migrations.CreateModel(
            name='WhatsAppWaitingLink',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('phone_number', models.CharField(max_length=32)),
                (
                    'account',
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name='waiting_links',
                        to='whatsapp.whatsappaccount',
                    ),
                ),
                (
                    'user',
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name='+',
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                'constraints': [
                    models.UniqueConstraint(
                        fields=('user', 'account'), name='whatsapp_waiting_link_unique_user_per_account'
                    ),
                    models.UniqueConstraint(
                        fields=('account', 'phone_number'), name='whatsapp_waiting_link_unique_phone_per_account'
                    ),
                ],
            },
        ),
    ]
