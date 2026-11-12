import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models

import market.models


class Migration(migrations.Migration):
    initial = True

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="PriceSnapshot",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("coin_id", models.CharField(db_index=True, max_length=64)),
                ("vs_currency", models.CharField(default="usd", max_length=10)),
                ("price", models.DecimalField(decimal_places=12, max_digits=30)),
                ("change_24h", models.DecimalField(blank=True, decimal_places=4, max_digits=12, null=True)),
                ("market_cap", models.DecimalField(blank=True, decimal_places=2, max_digits=40, null=True)),
                ("captured_at", models.DateTimeField(auto_now_add=True, db_index=True)),
            ],
            options={"ordering": ["-captured_at"]},
        ),
        migrations.AddIndex(
            model_name="pricesnapshot",
            index=models.Index(fields=["coin_id", "vs_currency", "-captured_at"], name="snap_coin_vs_time_idx"),
        ),
        migrations.CreateModel(
            name="ApiToken",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("key", models.CharField(default=market.models.generate_token, max_length=64, unique=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("user", models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name="api_token", to=settings.AUTH_USER_MODEL)),
            ],
        ),
        migrations.CreateModel(
            name="WatchlistItem",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("coin_id", models.CharField(max_length=64)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("user", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="watchlist", to=settings.AUTH_USER_MODEL)),
            ],
            options={"ordering": ["coin_id"], "unique_together": {("user", "coin_id")}},
        ),
        migrations.CreateModel(
            name="PriceAlert",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("coin_id", models.CharField(max_length=64)),
                ("vs_currency", models.CharField(default="usd", max_length=10)),
                ("direction", models.CharField(choices=[("above", "Above"), ("below", "Below")], max_length=5)),
                ("target_price", models.DecimalField(decimal_places=12, max_digits=30)),
                ("triggered", models.BooleanField(default=False)),
                ("triggered_at", models.DateTimeField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("user", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="alerts", to=settings.AUTH_USER_MODEL)),
            ],
            options={"ordering": ["-created_at"]},
        ),
        migrations.CreateModel(
            name="Holding",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("coin_id", models.CharField(max_length=64)),
                ("amount", models.DecimalField(decimal_places=12, max_digits=30)),
                ("avg_buy_price", models.DecimalField(decimal_places=12, default=0, max_digits=30)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("user", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="holdings", to=settings.AUTH_USER_MODEL)),
            ],
            options={"ordering": ["coin_id"], "unique_together": {("user", "coin_id")}},
        ),
    ]
