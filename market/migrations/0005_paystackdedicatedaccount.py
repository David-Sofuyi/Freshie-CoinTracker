from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [("market", "0004_wallet_ledger"), migrations.swappable_dependency(settings.AUTH_USER_MODEL)]
    operations = [
        migrations.CreateModel(
            name="PaystackDedicatedAccount",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("customer_code", models.CharField(max_length=80, unique=True)),
                ("account_name", models.CharField(blank=True, max_length=160)),
                ("account_number", models.CharField(blank=True, max_length=20)),
                ("bank_name", models.CharField(blank=True, max_length=100)),
                ("bank_slug", models.CharField(blank=True, max_length=80)),
                ("currency", models.CharField(default="NGN", max_length=3)),
                ("status", models.CharField(default="pending", max_length=20)),
                ("consented_at", models.DateTimeField(blank=True, null=True)),
                ("provider_metadata", models.JSONField(blank=True, default=dict)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("user", models.OneToOneField(on_delete=django.db.models.deletion.PROTECT, related_name="paystack_dedicated_account", to=settings.AUTH_USER_MODEL)),
            ],
        ),
    ]
