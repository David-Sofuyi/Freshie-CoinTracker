from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import SimpleTestCase, TestCase

from api import poller
from api.portfolio import valuate
from api.price_client import PriceClient
from market.models import PriceAlert, PriceSnapshot

User = get_user_model()


def price(coin, value, vs="usd"):
    return {"coin_id": coin, "vs_currency": vs, "price": value, "change_24h": 1.234567, "market_cap": 1e9}


class PortfolioTests(SimpleTestCase):
    def test_profit_and_loss(self):
        holdings = [
            SimpleNamespace(coin_id="bitcoin", amount=Decimal("2"), avg_buy_price=Decimal("100")),
            SimpleNamespace(coin_id="ethereum", amount=Decimal("10"), avg_buy_price=Decimal("5")),
        ]
        result = valuate(holdings, {"bitcoin": price("bitcoin", 150)}, "usd")
        btc, eth = result["holdings"]
        self.assertEqual(btc["value"], Decimal("300"))
        self.assertEqual(btc["pnl"], Decimal("100"))
        self.assertEqual(btc["pnl_pct"], Decimal("50.00"))
        self.assertIsNone(eth["value"])  # no live price -> excluded from totals
        self.assertEqual(result["total_value"], Decimal("300"))
        self.assertEqual(result["total_cost"], Decimal("200"))


class PollerTests(TestCase):
    async def test_alert_above_triggers(self):
        user = await User.objects.acreate(username="alice")
        alert = await PriceAlert.objects.acreate(
            user=user, coin_id="bitcoin", direction="above", target_price=Decimal("100")
        )
        await poller.check_alerts({"bitcoin": price("bitcoin", 101.5)})
        await alert.arefresh_from_db()
        self.assertTrue(alert.triggered)
        self.assertIsNotNone(alert.triggered_at)

    async def test_alert_not_triggered_below_target(self):
        user = await User.objects.acreate(username="bob")
        alert = await PriceAlert.objects.acreate(
            user=user, coin_id="bitcoin", direction="above", target_price=Decimal("100")
        )
        await poller.check_alerts({"bitcoin": price("bitcoin", 99)})
        await alert.arefresh_from_db()
        self.assertFalse(alert.triggered)

    async def test_snapshots_are_stored(self):
        await poller.store_snapshots({"bitcoin": price("bitcoin", 65000.5)})
        snap = await PriceSnapshot.objects.aget(coin_id="bitcoin")
        self.assertEqual(snap.price, Decimal("65000.5"))
        self.assertEqual(snap.change_24h, Decimal("1.2346"))


class FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        pass

    def json(self):
        return self._payload


class FakeAsyncClient:
    payload = {}

    def __init__(self, *a, **kw):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def get(self, path, params=None):
        return FakeResponse(self.payload)


class PriceClientTests(SimpleTestCase):
    async def test_parses_coingecko_response(self):
        FakeAsyncClient.payload = {
            "bitcoin": {"usd": 65000, "usd_24h_change": 2.5, "usd_market_cap": 1.2e12, "last_updated_at": 1700000000}
        }
        with patch("api.price_client.httpx.AsyncClient", FakeAsyncClient):
            data = await PriceClient().get_prices(["Bitcoin"], "usd")
        self.assertEqual(data["bitcoin"]["price"], 65000)
        self.assertEqual(data["bitcoin"]["change_24h"], 2.5)

    async def test_unknown_coin_is_omitted(self):
        FakeAsyncClient.payload = {}
        with patch("api.price_client.httpx.AsyncClient", FakeAsyncClient):
            data = await PriceClient().get_prices(["notacoin"], "usd")
        self.assertEqual(data, {})
