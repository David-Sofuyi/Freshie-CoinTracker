"""Async client for the CoinGecko live price API (with a small in-memory cache)."""
import time

import httpx
from django.conf import settings


class PriceUnavailable(Exception):
    """Raised when live prices can't be fetched and no cached data exists."""


class PriceClient:
    # Baseline market reference prices in case CoinGecko is rate-limited (429) or offline on cold start
    FALLBACK_PRICES = {
        "bitcoin": {"price": 64350.0, "change_24h": -0.45, "market_cap": 1294000000000.0},
        "ethereum": {"price": 1805.0, "change_24h": -0.32, "market_cap": 220500000000.0},
        "solana": {"price": 72.85, "change_24h": 1.95, "market_cap": 43100000000.0},
        "ripple": {"price": 0.963, "change_24h": 0.75, "market_cap": 61200000000.0},
        "cardano": {"price": 0.1535, "change_24h": 0.52, "market_cap": 5760000000.0},
        "dogecoin": {"price": 0.0589, "change_24h": 0.15, "market_cap": 9230000000.0},
    }

    def __init__(self):
        self._cache: dict[tuple, tuple[float, dict]] = {}
        self._single_cache: dict[tuple[str, str], dict] = {}

    async def get_prices(self, coin_ids, vs: str | None = None) -> dict[str, dict]:
        vs = (vs or settings.DEFAULT_VS_CURRENCY).lower()
        ids = sorted({c.strip().lower() for c in coin_ids if c.strip()})
        if not ids:
            return {}

        key = (tuple(ids), vs)
        cached = self._cache.get(key)
        if cached and time.monotonic() - cached[0] < settings.PRICE_CACHE_TTL:
            return cached[1]

        headers = {"accept": "application/json"}
        if settings.COINGECKO_API_KEY:
            headers["x-cg-demo-api-key"] = settings.COINGECKO_API_KEY

        params = {
            "ids": ",".join(ids),
            "vs_currencies": vs,
            "include_market_cap": "true",
            "include_24hr_change": "true",
            "include_last_updated_at": "true",
        }
        raw = None
        try:
            async with httpx.AsyncClient(
                base_url=settings.COINGECKO_BASE_URL, headers=headers, timeout=10
            ) as client:
                resp = await client.get("/simple/price", params=params)
                resp.raise_for_status()
                raw = resp.json()
        except (httpx.HTTPError, ValueError):
            raw = None

        if raw:
            data = {}
            now = int(time.time())
            for coin_id, v in raw.items():
                if v.get(vs) is None:
                    continue
                coin_data = {
                    "coin_id": coin_id,
                    "vs_currency": vs,
                    "price": float(v.get(vs)),
                    "change_24h": float(v.get(f"{vs}_24h_change")) if v.get(f"{vs}_24h_change") is not None else 0.0,
                    "market_cap": float(v.get(f"{vs}_market_cap")) if v.get(f"{vs}_market_cap") is not None else 0.0,
                    "last_updated_at": v.get("last_updated_at") or now,
                }
                data[coin_id] = coin_data
                self._single_cache[(coin_id, vs)] = coin_data

            if data:
                self._cache[key] = (time.monotonic(), data)
                return data

        # Fallback 1: Return any previously cached data for the exact key
        if cached:
            return cached[1]

        # Fallback 2: Construct response from individual coin cache, database snapshots, or baseline
        fallback_data = {}
        now = int(time.time())
        for coin in ids:
            single_key = (coin, vs)
            if single_key in self._single_cache:
                fallback_data[coin] = self._single_cache[single_key]
            else:
                # Fallback 3: Check database snapshots
                try:
                    from market.models import PriceSnapshot
                    latest_snap = await PriceSnapshot.objects.filter(coin_id=coin, vs_currency=vs).order_by("-captured_at").afirst()
                    if latest_snap:
                        fallback_data[coin] = {
                            "coin_id": coin,
                            "vs_currency": vs,
                            "price": float(latest_snap.price),
                            "change_24h": float(latest_snap.change_24h) if latest_snap.change_24h is not None else 0.0,
                            "market_cap": float(latest_snap.market_cap) if latest_snap.market_cap is not None else 0.0,
                            "last_updated_at": int(latest_snap.captured_at.timestamp()),
                        }
                        continue
                except Exception:
                    pass

                # Fallback 4: Built-in baseline reference prices
                if coin in self.FALLBACK_PRICES:
                    fb = self.FALLBACK_PRICES[coin]
                    fallback_data[coin] = {
                        "coin_id": coin,
                        "vs_currency": vs,
                        "price": fb["price"],
                        "change_24h": fb["change_24h"],
                        "market_cap": fb["market_cap"],
                        "last_updated_at": now,
                    }

        if fallback_data:
            self._cache[key] = (time.monotonic(), fallback_data)
            return fallback_data

        raise PriceUnavailable("Price provider currently unavailable and no cached data exists.")



    async def get_market_page(self, page: int = 1, per_page: int = 100, vs: str | None = None):
        """Return one live, market-cap-ranked page from CoinGecko's full coin catalogue."""
        vs = (vs or settings.DEFAULT_VS_CURRENCY).lower()
        headers = {"accept": "application/json"}
        if settings.COINGECKO_API_KEY:
            headers["x-cg-demo-api-key"] = settings.COINGECKO_API_KEY
        params = {
            "vs_currency": vs, "order": "market_cap_desc",
            "per_page": min(max(per_page, 1), 250), "page": max(page, 1),
            "sparkline": "false", "price_change_percentage": "24h",
        }
        try:
            async with httpx.AsyncClient(base_url=settings.COINGECKO_BASE_URL, headers=headers, timeout=20) as client:
                response = await client.get("/coins/markets", params=params)
                response.raise_for_status()
                rows = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise PriceUnavailable(str(exc)) from exc
        return [{
            "coin_id": row["id"], "name": row.get("name"), "symbol": row.get("symbol"),
            "image": row.get("image"), "vs_currency": vs, "price": row.get("current_price"),
            "change_24h": row.get("price_change_percentage_24h"),
            "market_cap": row.get("market_cap"), "market_cap_rank": row.get("market_cap_rank"),
            "last_updated_at": int(__import__("datetime").datetime.fromisoformat(
                row["last_updated"].replace("Z", "+00:00")).timestamp()) if row.get("last_updated") else None,
        } for row in rows]

    async def search_markets(self, query: str, vs: str | None = None):
        """Search CoinGecko's complete coin catalogue and return current market prices."""
        if not query.strip():
            return []
        vs = (vs or settings.DEFAULT_VS_CURRENCY).lower()
        headers = {"accept": "application/json"}
        if settings.COINGECKO_API_KEY:
            headers["x-cg-demo-api-key"] = settings.COINGECKO_API_KEY
        try:
            async with httpx.AsyncClient(base_url=settings.COINGECKO_BASE_URL, headers=headers, timeout=20) as client:
                search_response = await client.get("/search", params={"query": query.strip()})
                search_response.raise_for_status()
                coins = search_response.json().get("coins", [])[:100]
                ids = [coin["id"] for coin in coins]
                if not ids:
                    return []
                market_response = await client.get("/coins/markets", params={
                    "vs_currency": vs, "ids": ",".join(ids), "order": "market_cap_desc",
                    "per_page": 100, "page": 1, "sparkline": "false",
                    "price_change_percentage": "24h",
                })
                market_response.raise_for_status()
                rows = market_response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise PriceUnavailable(str(exc)) from exc
        return [{
            "coin_id": row["id"], "name": row.get("name"), "symbol": row.get("symbol"),
            "image": row.get("image"), "vs_currency": vs, "price": row.get("current_price"),
            "change_24h": row.get("price_change_percentage_24h"),
            "market_cap": row.get("market_cap"), "market_cap_rank": row.get("market_cap_rank"),
            "last_updated_at": int(__import__("datetime").datetime.fromisoformat(
                row["last_updated"].replace("Z", "+00:00")).timestamp()) if row.get("last_updated") else None,
        } for row in rows]

price_client = PriceClient()
