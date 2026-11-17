from django.contrib import admin

from .models import ApiToken, Holding, PriceAlert, PriceSnapshot, WatchlistItem, PaystackDedicatedAccount


@admin.register(ApiToken)
class ApiTokenAdmin(admin.ModelAdmin):
    list_display = ("user", "created_at")
    readonly_fields = ("key",)


@admin.register(WatchlistItem)
class WatchlistItemAdmin(admin.ModelAdmin):
    list_display = ("user", "coin_id", "created_at")
    list_filter = ("coin_id",)


@admin.register(PriceSnapshot)
class PriceSnapshotAdmin(admin.ModelAdmin):
    list_display = ("coin_id", "vs_currency", "price", "change_24h", "captured_at")
    list_filter = ("coin_id", "vs_currency")
    date_hierarchy = "captured_at"


@admin.register(PriceAlert)
class PriceAlertAdmin(admin.ModelAdmin):
    list_display = ("user", "coin_id", "direction", "target_price", "triggered", "triggered_at")
    list_filter = ("triggered", "direction", "coin_id")


@admin.register(Holding)
class HoldingAdmin(admin.ModelAdmin):
    list_display = ("user", "coin_id", "amount", "avg_buy_price", "updated_at")
    list_filter = ("coin_id",)


@admin.register(PaystackDedicatedAccount)
class PaystackDedicatedAccountAdmin(admin.ModelAdmin):
    list_display = ("user", "bank_name", "account_number", "currency", "status", "created_at")
    search_fields = ("user__username", "user__email", "account_number", "customer_code")
    readonly_fields = ("customer_code", "account_name", "account_number", "bank_name", "bank_slug", "currency", "status", "consented_at", "provider_metadata", "created_at", "updated_at")
