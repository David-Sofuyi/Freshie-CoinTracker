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


class PasswordResetCode(models.Model):
    """Hashed, expiring, single-use email password reset code."""
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="password_reset_codes")
    code_hash = models.CharField(max_length=256)
    expires_at = models.DateTimeField(db_index=True)
    used_at = models.DateTimeField(null=True, blank=True)
    attempts = models.PositiveSmallIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]



class WalletAccount(models.Model):
    """Fiat wallet balance maintained exclusively through ledger postings."""
    NGN = "NGN"
    USD = "USD"
    CURRENCIES = [(NGN, "Nigerian Naira"), (USD, "US Dollar")]
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="wallet_accounts")
    currency = models.CharField(max_length=3, choices=CURRENCIES)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["user", "currency"], name="uniq_user_wallet_currency")]


class WalletTransaction(models.Model):
    DEPOSIT = "deposit"
    WITHDRAWAL = "withdrawal"
    TRANSFER = "transfer"
    TRADE = "trade"
    TYPES = [(DEPOSIT, "Deposit"), (WITHDRAWAL, "Withdrawal"), (TRANSFER, "Transfer"), (TRADE, "Trade")]
    PENDING = "pending"
    SUCCESS = "success"
    FAILED = "failed"
    STATUSES = [(PENDING, "Pending"), (SUCCESS, "Success"), (FAILED, "Failed")]
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="wallet_transactions")
    transaction_type = models.CharField(max_length=12, choices=TYPES)
    currency = models.CharField(max_length=3, choices=WalletAccount.CURRENCIES)
    amount = models.DecimalField(max_digits=24, decimal_places=8)
    reference = models.CharField(max_length=100, unique=True)
    status = models.CharField(max_length=10, choices=STATUSES, default=PENDING)
    description = models.CharField(max_length=255, blank=True)
    provider = models.CharField(max_length=30, blank=True)
    provider_reference = models.CharField(max_length=120, blank=True, db_index=True)
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]


class WalletLedgerEntry(models.Model):
    """Immutable debit/credit posting. Sum of entries per currency must balance."""
    transaction = models.ForeignKey(WalletTransaction, on_delete=models.PROTECT, related_name="entries")
    account = models.ForeignKey(WalletAccount, on_delete=models.PROTECT, related_name="entries", null=True, blank=True)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="wallet_ledger_entries", null=True, blank=True)
    currency = models.CharField(max_length=3, choices=WalletAccount.CURRENCIES)
    amount = models.DecimalField(max_digits=24, decimal_places=8)  # positive credit, negative debit
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at", "id"]


class PaystackDedicatedAccount(models.Model):
    """Customer's NGN virtual account. No BVN or identity document is stored here."""
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="paystack_dedicated_account")
    customer_code = models.CharField(max_length=80, unique=True)
    account_name = models.CharField(max_length=160, blank=True)
    account_number = models.CharField(max_length=20, blank=True)
    bank_name = models.CharField(max_length=100, blank=True)
    bank_slug = models.CharField(max_length=80, blank=True)
    currency = models.CharField(max_length=3, default="NGN")
    status = models.CharField(max_length=20, default="pending")
    consented_at = models.DateTimeField(null=True, blank=True)
    provider_metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.user_id}: {self.bank_name} {self.account_number}"
