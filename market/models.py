import secrets

from django.conf import settings
from django.db import models


def generate_token() -> str:
    return secrets.token_hex(32)


class ApiToken(models.Model):
    """Bearer token used by API clients (FastAPI side) to authenticate a Django user."""

    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="api_token")
    key = models.CharField(max_length=64, unique=True, default=generate_token)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Token for {self.user}"


class WatchlistItem(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="watchlist")
    coin_id = models.CharField(max_length=64)  # CoinGecko id, e.g. "bitcoin"
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ("user", "coin_id")
        ordering = ["coin_id"]

    def __str__(self):
        return f"{self.user}: {self.coin_id}"


class PriceSnapshot(models.Model):
    coin_id = models.CharField(max_length=64, db_index=True)
    vs_currency = models.CharField(max_length=10, default="usd")
    price = models.DecimalField(max_digits=30, decimal_places=12)
    change_24h = models.DecimalField(max_digits=12, decimal_places=4, null=True, blank=True)
    market_cap = models.DecimalField(max_digits=40, decimal_places=2, null=True, blank=True)
    captured_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["-captured_at"]
        indexes = [models.Index(fields=["coin_id", "vs_currency", "-captured_at"], name="snap_coin_vs_time_idx")]

    def __str__(self):
        return f"{self.coin_id} {self.price} {self.vs_currency}"


class PriceAlert(models.Model):
    ABOVE = "above"
    BELOW = "below"
    DIRECTIONS = [(ABOVE, "Above"), (BELOW, "Below")]

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="alerts")
    coin_id = models.CharField(max_length=64)
    vs_currency = models.CharField(max_length=10, default="usd")
    direction = models.CharField(max_length=5, choices=DIRECTIONS)
    target_price = models.DecimalField(max_digits=30, decimal_places=12)
    triggered = models.BooleanField(default=False)
    triggered_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.coin_id} {self.direction} {self.target_price}"


class Holding(models.Model):
    """A user's position in a coin, used to compute live portfolio value and profit/loss."""

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="holdings")
    coin_id = models.CharField(max_length=64)
    amount = models.DecimalField(max_digits=30, decimal_places=12)
    avg_buy_price = models.DecimalField(max_digits=30, decimal_places=12, default=0)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ("user", "coin_id")
        ordering = ["coin_id"]

    def __str__(self):
        return f"{self.user}: {self.amount} {self.coin_id}"


class AccountRecovery(models.Model):
    """Stores only a password hash of the user's one-time 12-word recovery phrase."""
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="account_recovery")
    phrase_hash = models.CharField(max_length=256)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Recovery credentials for {self.user}"
