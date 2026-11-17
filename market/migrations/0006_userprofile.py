from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [("market", "0005_paystackdedicatedaccount"), migrations.swappable_dependency(settings.AUTH_USER_MODEL)]
    operations = [
        migrations.CreateModel(
            name="UserProfile",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("phone_number", models.CharField(blank=True, max_length=30)),
                ("gender", models.CharField(blank=True, choices=[("male", "Male"), ("female", "Female"), ("other", "Other"), ("prefer_not_to_say", "Prefer not to say")], max_length=20)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("user", models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name="profile", to=settings.AUTH_USER_MODEL)),
            ],
        ),
    ]
