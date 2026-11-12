"""Background task: poll live prices, store snapshots, fire alerts, broadcast to WebSockets."""
import asyncio
import logging
from decimal import Decimal

from django.conf import settings
from django.utils import timezone

from market.models import PriceAlert, PriceSnapshot, WatchlistItem

from .price_client import PriceUnavailable, price_client

log = logging.getLogger("poller")


class Hub:
    """Keeps the latest prices and the set of connected WebSocket clients."""

    def __init__(self):
        self.latest: dict[str, dict] = {}
        self.clients: set = set()

    async def broadcast(self, message: dict):
        dead = []
        for ws in list(self.clients):
            try:
                await ws.send_json(message)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.clients.discard(ws)


hub = Hub()


async def tracked_coin_ids() -> list[str]:
    coins = set(settings.DEFAULT_COINS)
    async for coin_id in WatchlistItem.objects.values_list("coin_id", flat=True).distinct():
        coins.add(coin_id)
    async for coin_id in PriceAlert.objects.filter(triggered=False).values_list("coin_id", flat=True).distinct():
        coins.add(coin_id)
    return sorted(coins)


def _dec(value):
    return None if value is None else Decimal(str(value))


def _round(value, places):
    return None if value is None else round(Decimal(str(value)), places)


async def store_snapshots(prices: dict[str, dict]):
    rows = [
        PriceSnapshot(
            coin_id=p["coin_id"],
            vs_currency=p["vs_currency"],
            price=_dec(p["price"]),
            change_24h=_round(p.get("change_24h"), 4),
            market_cap=_round(p.get("market_cap"), 2),
        )
        for p in prices.values()
    ]
    if rows:
        await PriceSnapshot.objects.abulk_create(rows)


async def check_alerts(prices: dict[str, dict]):
    async for alert in PriceAlert.objects.filter(triggered=False, coin_id__in=list(prices)):
        p = prices.get(alert.coin_id)
        if not p or p["vs_currency"] != alert.vs_currency:
            continue
        price = _dec(p["price"])
        hit = (alert.direction == PriceAlert.ABOVE and price >= alert.target_price) or (
            alert.direction == PriceAlert.BELOW and price <= alert.target_price
        )
        if hit:
            alert.triggered = True
            alert.triggered_at = timezone.now()
            await alert.asave(update_fields=["triggered", "triggered_at"])
            log.info("Alert %s triggered at %s", alert.pk, price)
            await hub.broadcast({"type": "alert", "alert_id": alert.pk, "coin_id": alert.coin_id,
                                 "direction": alert.direction, "target_price": str(alert.target_price),
                                 "price": str(price)})


async def poll_forever():
    while True:
        try:
            coins = await tracked_coin_ids()
            prices = await price_client.get_prices(coins, settings.DEFAULT_VS_CURRENCY)
            if prices:
                hub.latest = prices
                await store_snapshots(prices)
                await check_alerts(prices)
                await hub.broadcast({"type": "prices", "data": list(prices.values())})
        except PriceUnavailable as exc:
            log.warning("Price fetch failed: %s", exc)
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("Poller error")
        await asyncio.sleep(settings.POLL_INTERVAL)
