"""Провайдер AIM Market (aim.market).

У AIM Market нет широко задокументированного публичного API, поэтому провайдер
обращается к их внутреннему market-эндпоинту поиска. Структуру ответа парсим
максимально терпимо. Если площадка сменит адрес/формат — правьте API_URL и
_parse(); на остальной бот это не влияет, сбой изолируется.
"""
from __future__ import annotations

from urllib.parse import quote_plus

import httpx

from .base import BaseProvider, PriceResult, normalize, tokens

API_URL = "https://api.aim.market/v1/market/items"


class AimMarketProvider(BaseProvider):
    name = "AIM Market"

    async def search(self, client: httpx.AsyncClient, query: str) -> PriceResult:
        params = {
            "search": query,
            "limit": 60,
            "offset": 0,
            "sort": "price",
            "order": "asc",
            "game": "csgo",
        }
        headers = {
            "Accept": "application/json",
            "User-Agent": "Mozilla/5.0 (compatible; CS2PriceBot/1.0)",
        }
        try:
            resp = await client.get(API_URL, params=params, headers=headers, timeout=10.0)
            resp.raise_for_status()
            data = resp.json()
        except httpx.HTTPStatusError as exc:
            return self._error(query, f"HTTP {exc.response.status_code}")
        except httpx.TimeoutException:
            return self._error(query, "таймаут")
        except Exception as exc:  # noqa: BLE001
            return self._error(query, exc.__class__.__name__)

        best = self._parse(data, query)
        if best is None:
            return PriceResult(market=self.name, query=query, error="не найдено")

        name, price, count = best
        return PriceResult(
            market=self.name,
            query=query,
            matched_name=name,
            price=price,
            currency="USD",
            count=count,
            url="https://aim.market/market?search=" + quote_plus(query),
        )

    @staticmethod
    def _parse(data, query):
        items = data
        if isinstance(data, dict):
            for key in ("items", "data", "result", "items_list"):
                if isinstance(data.get(key), list):
                    items = data[key]
                    break
        if not isinstance(items, list) or not items:
            return None

        qtokens = tokens(query)
        best = None
        for it in items:
            if not isinstance(it, dict):
                continue
            name = it.get("name") or it.get("market_hash_name") or it.get("fullName")
            price = it.get("price") or it.get("min_price") or it.get("suggested_price")
            if name is None or price is None:
                continue
            try:
                price = float(price)
            except (TypeError, ValueError):
                continue
            if qtokens and not all(tok in normalize(str(name)) for tok in qtokens):
                continue
            count = it.get("count") or it.get("amount")
            if best is None or price < best[1]:
                best = (str(name), price, count)

        return best
