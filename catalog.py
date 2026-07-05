"""Каталог скинов на основе публичного фида LisSkins.

Стратегия «stale-while-revalidate»: пользователь НИКОГДА не ждёт загрузку фида.
  * данные отдаются из памяти сразу;
  * если кэш устарел — обновление запускается в фоне, а запрос обслуживается
    старыми данными;
  * между перезапусками кэш лежит на диске (pickle) — старт мгновенный.

Один каталог используется и провайдером LisSkins (цены), и ботом (кнопки).
"""
from __future__ import annotations

import asyncio
import logging
import os
import pickle
import time

import httpx

from skinutils import normalize, split_base_wear, tokens

logger = logging.getLogger("cs2-price-bot.catalog")

FEED_URL = "https://lis-skins.com/market_export_json/api_csgo_full.json"
TTL = 900          # сколько секунд данные считаются свежими (15 мин)
DOWNLOAD_TIMEOUT = 120  # фид большой — качаем с запасом (в фоне, никого не блокирует)
CACHE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".catalog_cache.pkl")


class Catalog:
    def __init__(self) -> None:
        self.prices: dict[str, dict] = {}
        self.bases: dict[str, dict] = {}
        self._fetched_at: float = 0.0
        self._lock = asyncio.Lock()
        self._refreshing = False
        self.loaded: bool = False

    def _is_fresh(self) -> bool:
        return self.loaded and (time.time() - self._fetched_at) < TTL

    async def ensure(self, client: httpx.AsyncClient | None = None) -> None:
        """Гарантируем наличие данных. Блокирует только при самой первой загрузке."""
        if self._is_fresh():
            return

        if not self.loaded:
            # пробуем поднять с диска — это мгновенно
            if self._load_disk():
                logger.info("Каталог поднят из дискового кэша (%d скинов)", len(self.bases))
            else:
                # совсем нет данных — придётся один раз подождать загрузку
                async with self._lock:
                    if not self.loaded:
                        await self._fetch_and_build()
                        return

        # данные есть, но устарели — обновим в фоне, отдаём как есть
        self._schedule_refresh()

    def _schedule_refresh(self) -> None:
        if self._refreshing or self._is_fresh():
            return
        self._refreshing = True

        async def _bg() -> None:
            try:
                await self._fetch_and_build()
                logger.info("Каталог обновлён в фоне (%d скинов)", len(self.bases))
            except Exception as exc:  # noqa: BLE001
                logger.warning("Фоновое обновление каталога не удалось: %s", exc)
            finally:
                self._refreshing = False

        try:
            asyncio.get_running_loop().create_task(_bg())
        except RuntimeError:
            self._refreshing = False

    async def _fetch_and_build(self) -> None:
        headers = {"User-Agent": "Mozilla/5.0 (compatible; CS2PriceBot/1.0)"}
        async with httpx.AsyncClient(timeout=DOWNLOAD_TIMEOUT, headers=headers,
                                     follow_redirects=True) as client:
            resp = await client.get(FEED_URL)
            resp.raise_for_status()
            data = resp.json()
        self._build(data)
        self._fetched_at = time.time()
        self.loaded = True
        self._save_disk()

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

                nf = normalize(raw)
                slot = prices.get(nf)
                if slot is None:
                    prices[nf] = {"name": raw, "price": price, "count": count}
                else:
                    slot["count"] += count
                    if price < slot["price"]:
                        slot["price"] = price

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

    # ------- дисковый кэш -------
    def _save_disk(self) -> None:
        try:
            with open(CACHE_FILE, "wb") as f:
                pickle.dump(
                    {"prices": self.prices, "bases": self.bases, "at": self._fetched_at},
                    f, protocol=pickle.HIGHEST_PROTOCOL,
                )
        except Exception as exc:  # noqa: BLE001
            logger.debug("Не удалось сохранить дисковый кэш: %s", exc)

    def _load_disk(self) -> bool:
        try:
            with open(CACHE_FILE, "rb") as f:
                d = pickle.load(f)
            self.prices = d["prices"]
            self.bases = d["bases"]
            self._fetched_at = d["at"]
            self.loaded = True
            return True
        except Exception:  # noqa: BLE001
            return False

    # ------- запросы -------
    def price_of(self, full_name: str) -> dict | None:
        return self.prices.get(normalize(full_name))

    def search_bases(self, query: str, limit: int = 8) -> tuple[list[tuple[str, dict]], int]:
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


CATALOG = Catalog()
