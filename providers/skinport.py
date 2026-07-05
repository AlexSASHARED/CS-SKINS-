"""Провайдер Skinport.

Публичный открытый API без ключа: один запрос отдаёт весь прайс-лист CS2
(`market_hash_name`, `min_price`, `quantity`). Фид кэшируем в памяти на TTL
секунд — у Skinport лимит ~8 запросов за 5 минут, кэш его с запасом соблюдает.

Docs: https://docs.skinport.com/  (endpoint /v1/items)
"""
from __future__ import annotations

import asyncio
import time
from urllib.parse import quote_plus

import httpx

from skinutils import normalize, tokens

from .base import BaseProvider, PriceResult

API_URL = "https://api.skinport.com/v1/items"
TTL = 600  # секунд


class SkinportProvider(BaseProvider):
    name = "Skinport"

    def __init__(self) -> None:
        self._index: dict[str, dict] = {}
        self._fetched_at: float = 0.0
        self._lock = asyncio.Lock()

    async def _refresh(self, client: httpx.AsyncClient) -> None:
        if self._index and (time.time() - self._fetched_at) < TTL:
            return
        async with self._lock:
            if self._index and (time.time() - self._fetched_at) < TTL:
                return
            resp = await client.get(
                API_URL,
                params={"app_id": 730, "currency": "USD", "tradable": 0},
                headers={"Accept": "application/json", "Accept-Encoding": "gzip"},
                timeout=30.0,
            )
            resp.raise_for_status()
            data = resp.json()

            index: dict[str, dict] = {}
            if isinstance(data, list):
                for it in data:
                    if not isinstance(it, dict):
                        continue
                    name = it.get("market_hash_name")
                    price = it.get("min_price")
                    if not name or price is None:
                        continue
                    try:
                        price = float(price)
                    except (TypeError, ValueError):
                        continue
                    index[normalize(str(name))] = {
                        "name": str(name),
                        "price": price,
                        "count": it.get("quantity"),
                        "url": it.get("market_page") or it.get("item_page"),
                    }
            self._index = index
            self._fetched_at = time.time()

    async def search(self, client: httpx.AsyncClient, query: str) -> PriceResult:
        try:
            await self._refresh(client)
        except httpx.HTTPStatusError as exc:
            return self._error(query, f"HTTP {exc.response.status_code}")
        except httpx.TimeoutException:
            return self._error(query, "таймаут")
        except Exception as exc:  # noqa: BLE001
            return self._error(query, exc.__class__.__name__)

        slot = self._index.get(normalize(query)) or self._fuzzy(query)
        if slot is None:
            return PriceResult(market=self.name, query=query, error="не найдено")

        return PriceResult(
            market=self.name,
            query=query,
            matched_name=slot["name"],
            price=slot["price"],
            currency="USD",
            count=slot["count"],
            url=slot["url"] or ("https://skinport.com/market?search=" + quote_plus(slot["name"])),
        )

    def _fuzzy(self, query: str):
        qt = tokens(query)
        if not qt:
            return None
        best = None
        for nf, slot in self._index.items():
            if all(t in nf for t in qt):
                if best is None or slot["price"] < best["price"]:
                    best = slot
        return best
