"""Провайдер Steam Community Market (опорная цена).

Steam отдаёт стабильный публичный эндпоинт priceoverview. Он требует точное
market_hash_name, поэтому нечёткие запросы могут не находиться — зато цена
всегда актуальна и служит ориентиром относительно сторонних площадок.
"""
from __future__ import annotations

from urllib.parse import quote

import httpx

from .base import BaseProvider, PriceResult

# appid 730 = CS2/CS:GO; currency=1 -> USD
API_URL = "https://steamcommunity.com/market/priceoverview/"


def _parse_price(text: str) -> float | None:
    if not text:
        return None
    cleaned = (
        text.replace("$", "").replace("€", "").replace("руб.", "")
        .replace("USD", "").replace(",", ".").strip()
    )
    # оставляем только число
    num = "".join(ch for ch in cleaned if ch.isdigit() or ch == ".")
    try:
        return float(num) if num else None
    except ValueError:
        return None


class SteamProvider(BaseProvider):
    name = "Steam Market"

    async def search(self, client: httpx.AsyncClient, query: str) -> PriceResult:
        params = {
            "appid": 730,
            "currency": 1,
            "market_hash_name": query,
        }
        headers = {"User-Agent": "Mozilla/5.0 (compatible; CS2PriceBot/1.0)"}
        try:
            resp = await client.get(API_URL, params=params, headers=headers, timeout=25.0)
            resp.raise_for_status()
            data = resp.json()
        except Exception as exc:  # noqa: BLE001
            return self._error(query, f"API недоступен ({exc.__class__.__name__})")

        if not data.get("success"):
            return PriceResult(market=self.name, query=query, error="не найдено")

        price = _parse_price(data.get("lowest_price") or data.get("median_price") or "")
        if price is None:
            return PriceResult(market=self.name, query=query, error="нет цены")

        return PriceResult(
            market=self.name,
            query=query,
            matched_name=query,
            price=price,
            currency="USD",
            url="https://steamcommunity.com/market/listings/730/" + quote(query),
        )
