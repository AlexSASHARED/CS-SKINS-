"""Каталог скинов на основе публичного фида LisSkins.

Один раз скачивает весь прайс-лист (кэш на TTL секунд) и строит две структуры:
  * prices: нормализованное_имя -> {name, price, count}  (мин. цена и кол-во)
  * bases:  нормализованное_базовое_имя -> {name, wears, count}
    где wears: {износ -> точное полное имя для поиска цены}

Используется и провайдером LisSkins (для цен), и ботом (для кнопок выбора).
"""
from __future__ import annotations

import asyncio
import time

import httpx

from skinutils import normalize, split_base_wear, tokens

FEED_URL = "https://lis-skins.com/market_export_json/api_csgo_full.json"
TTL = 300  # секунд


class Catalog:
    def __init__(self) -> None:
        self.prices: dict[str, dict] = {}
        self.bases: dict[str, dict] = {}
        self._fetched_at: float = 0.0
        self._lock = asyncio.Lock()
        self.loaded: bool = False

    async def ensure(self, client: httpx.AsyncClient) -> None:
        """Обновляем каталог, если кэш устарел. Потокобезопасно."""
        if self.loaded and (time.time() - self._fetched_at) < TTL:
            return
        async with self._lock:
            if self.loaded and (time.time() - self._fetched_at) < TTL:
                return
            resp = await client.get(FEED_URL, timeout=90.0)
            resp.raise_for_status()
            self._build(resp.json())
            self._fetched_at = time.time()
            self.loaded = True

    def _build(self, data) -> None:
        items = data
        if isinstance(data, dict):
            for key in ("items", "data", "result", "skins"):
                if isinstance(data.get(key), list):
                    items = data[key]
                    break

        prices: dict[str, dict] = {}
        bases: dict[str, dict] = {}
        if isinstance(items, list):
            for it in items:
                if not isinstance(it, dict):
                    continue
                raw = it.get("name") or it.get("market_hash_name")
                price = it.get("price")
                if raw is None or price is None:
                    continue
                try:
                    price = float(price)
                except (TypeError, ValueError):
                    continue
                try:
                    count = int(it.get("count") or it.get("amount") or 1)
                except (TypeError, ValueError):
                    count = 1
                raw = str(raw)

                # индекс цен по полному имени
                nf = normalize(raw)
                slot = prices.get(nf)
                if slot is None:
                    prices[nf] = {"name": raw, "price": price, "count": count}
                else:
                    slot["count"] += count
                    if price < slot["price"]:
                        slot["price"] = price

                # индекс базовых скинов и доступных износов
                base_name, wear = split_base_wear(raw)
                nb = normalize(base_name)
                b = bases.get(nb)
                if b is None:
                    b = {"name": base_name, "wears": {}, "count": 0}
                    bases[nb] = b
                b["count"] += count
                b["wears"].setdefault(wear or "", raw)

        self.prices = prices
        self.bases = bases

    def price_of(self, full_name: str) -> dict | None:
        return self.prices.get(normalize(full_name))

    def search_bases(self, query: str, limit: int = 8) -> tuple[list[tuple[str, dict]], int]:
        """Находим базовые скины, где все токены запроса есть в имени.

        Возвращаем (список_до_limit, всего_найдено). Сортировка: точное
        совпадение имени первым, затем по популярности (кол-во лотов).
        """
        qt = tokens(query)
        if not qt:
            return [], 0
        exact_key = normalize(query)
        matches: list[tuple[str, dict]] = []
        for nb, b in self.bases.items():
            if all(t in nb for t in qt):
                matches.append((nb, b))
        matches.sort(key=lambda x: (x[0] != exact_key, -x[1]["count"], x[1]["name"]))
        return matches[:limit], len(matches)


# Единый экземпляр на процесс
CATALOG = Catalog()
