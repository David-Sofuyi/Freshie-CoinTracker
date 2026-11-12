"""Async client for the CoinGecko live price API (with a small in-memory cache)."""
import time

import httpx
from django.conf import settings


class PriceUnavailable(Exception):
    """Raised when live prices can't be fetched and no cached data exists."""


class PriceClient:
    def __init__(self):
        self._cache: dict[tuple, tuple[float, dict]] = {}

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
        try:
            async with httpx.AsyncClient(
                base_url=settings.COINGECKO_BASE_URL, headers=headers, timeout=10
            ) as client:
                resp = await client.get("/simple/price", params=params)
                resp.raise_for_status()
                raw = resp.json()
        except (httpx.HTTPError, ValueError) as exc:
            if cached:  # serve stale data rather than failing
                return cached[1]
            raise PriceUnavailable(str(exc)) from exc

        data = {}
        for coin_id, v in raw.items():
            if v.get(vs) is None:
                continue
            data[coin_id] = {
                "coin_id": coin_id,
                "vs_currency": vs,
                "price": v.get(vs),
                "change_24h": v.get(f"{vs}_24h_change"),
                "market_cap": v.get(f"{vs}_market_cap"),
                "last_updated_at": v.get("last_updated_at"),
            }
        self._cache[key] = (time.monotonic(), data)
        return data



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
