"""Провайдер LisSkins.

Берёт цены из общего каталога (catalog.CATALOG), который скачивает и кэширует
публичный JSON-фид прайса LisSkins. Точное имя ищется напрямую; для нечётких
запросов берём самый дешёвый подходящий скин.
"""
from __future__ import annotations

from urllib.parse import quote_plus

import httpx

from catalog import CATALOG
from skinutils import normalize, tokens

from .base import BaseProvider, PriceResult


class LisSkinsProvider(BaseProvider):
    name = "LisSkins"

    async def search(self, client: httpx.AsyncClient, query: str) -> PriceResult:
        try:
            await CATALOG.ensure(client)
        except Exception as exc:  # noqa: BLE001
            return self._error(query, f"фид недоступен ({exc.__class__.__name__})")

        slot = CATALOG.price_of(query) or self._fuzzy(query)
        if slot is None:
            return PriceResult(market=self.name, query=query, error="не найдено")

        return PriceResult(
            market=self.name,
            query=query,
            matched_name=slot["name"],
            price=slot["price"],
            currency="USD",
            count=slot["count"],
            url="https://lis-skins.com/market/csgo/?query=" + quote_plus(slot["name"]),
        )

    @staticmethod
    def _fuzzy(query: str):
        """Самый дешёвый лот, чьё имя содержит все токены запроса."""
        qt = tokens(query)
        if not qt:
            return None
        best = None
        for nf, slot in CATALOG.prices.items():
            if all(t in nf for t in qt):
                if best is None or slot["price"] < best["price"]:
                    best = slot
        return best
