"""Провайдер LisSkins.

Использует публичный JSON-фид прайса площадки. Фид большой (весь рынок),
поэтому кэшируем его в памяти на CACHE_TTL секунд и строим по нему индекс
name -> (минимальная цена, количество лотов).

Эндпоинт публичного фида:
    https://lis-skins.com/market_export_json/api_csgo_full.json

Если LisSkins изменит формат/адрес фида — достаточно поправить FEED_URL и
метод _parse_feed(); остальной код бота трогать не нужно.
"""
from __future__ import annotations

import time
from typing import Optional
from urllib.parse import quote_plus

import httpx

from .base import BaseProvider, PriceResult, normalize, tokens

FEED_URL = "https://lis-skins.com/market_export_json/api_csgo_full.json"
CACHE_TTL = 300  # секунд


class LisSkinsProvider(BaseProvider):
    name = "LisSkins"

    def __init__(self) -> None:
        # индекс: normalized_name -> {"price", "count", "name"}
        self._index: dict[str, dict] = {}
        self._fetched_at: float = 0.0

    async def _refresh(self, client: httpx.AsyncClient) -> None:
        if self._index and (time.time() - self._fetched_at) < CACHE_TTL:
            return
        resp = await client.get(FEED_URL, timeout=60.0)
        resp.raise_for_status()
        data = resp.json()
        self._index = self._parse_feed(data)
        self._fetched_at = time.time()

    @staticmethod
    def _parse_feed(data) -> dict[str, dict]:
        """Строим индекс из фида, устойчиво к вариантам структуры.

        Поддерживаем:
          - список позиций: [{"name":..., "price":..., ...}, ...]
          - объект с ключом items/data: {"items": [...]}
        Для каждого имени берём минимальную цену и суммарное количество лотов.
        """
        items = data
        if isinstance(data, dict):
            for key in ("items", "data", "result", "skins"):
                if isinstance(data.get(key), list):
                    items = data[key]
                    break
        if not isinstance(items, list):
            return {}

        index: dict[str, dict] = {}
        for it in items:
            if not isinstance(it, dict):
                continue
            raw_name = it.get("name") or it.get("market_hash_name")
            price = it.get("price")
            if raw_name is None or price is None:
                continue
            try:
                price = float(price)
            except (TypeError, ValueError):
                continue
            count = it.get("count") or it.get("amount") or 1
            try:
                count = int(count)
            except (TypeError, ValueError):
                count = 1

            key = normalize(str(raw_name))
            slot = index.get(key)
            if slot is None:
                index[key] = {"price": price, "count": count, "name": str(raw_name)}
            else:
                slot["count"] += count
                if price < slot["price"]:
                    slot["price"] = price

        return index

    def _find(self, query: str) -> Optional[dict]:
        """Ищем лучшее совпадение по индексу."""
        key = normalize(query)
        if key in self._index:
            return self._index[key]

        qtokens = tokens(query)
        if not qtokens:
            return None

        candidates = []
        for name_key, slot in self._index.items():
            if all(tok in name_key for tok in qtokens):
                candidates.append(slot)
        if not candidates:
            return None
        # самый дешёвый среди подходящих
        return min(candidates, key=lambda s: s["price"])

    async def search(self, client: httpx.AsyncClient, query: str) -> PriceResult:
        try:
            await self._refresh(client)
        except Exception as exc:  # noqa: BLE001 - изолируем сбой площадки
            return self._error(query, f"фид недоступен ({exc.__class__.__name__})")

        slot = self._find(query)
        if slot is None:
            return PriceResult(market=self.name, query=query,
                               error="не найдено")

        search_url = "https://lis-skins.com/market/csgo/?query=" + quote_plus(slot["name"])
        return PriceResult(
            market=self.name,
            query=query,
            matched_name=slot["name"],
            price=slot["price"],
            currency="USD",
            count=slot["count"],
            url=search_url,
        )
