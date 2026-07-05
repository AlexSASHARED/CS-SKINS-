"""Официальная локализация названий скинов CS2 (RU -> EN).

Берём открытый датасет ByMykel CSGO-API, где одни и те же предметы отдаются на
разных языках с языконезависимым `id`. Сопоставляя EN и RU по `id`, строим
карты:
  * ru_patterns: русское название финиша  -> английское ('красная линия'->'redline')
  * ru_weapons:  русское название оружия   -> английское ('керамбит'->'karambit')

Это даёт поиск по официальным внутриигровым названиям для всех скинов сразу,
без ручных словарей. Данные меняются редко — кэшируем на диск надолго.
Если датасет недоступен — тихо откатываемся к статическим словарям translit.py.

Docs датасета: https://github.com/ByMykel/CSGO-API  (/api/{lang}/skins.json)
"""
from __future__ import annotations

import logging
import os
import pickle
import time

import httpx

logger = logging.getLogger("cs2-price-bot.localization")

EN_URL = "https://bymykel.github.io/CSGO-API/api/en/skins.json"
RU_URL = "https://bymykel.github.io/CSGO-API/api/ru/skins.json"
TTL = 7 * 24 * 3600  # неделя
CACHE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                          ".localization_cache.pkl")


def _key(name: str) -> str:
    """Ключ для сопоставления: нижний регистр, без звёзд/™, схлопнутые пробелы."""
    name = name.lower().replace("★", " ").replace("™", " ")
    return " ".join(name.split())


class Localization:
    def __init__(self) -> None:
        self.ru_patterns: dict[str, str] = {}
        self.ru_weapons: dict[str, str] = {}
        self._fetched_at: float = 0.0
        self.loaded: bool = False

    async def ensure(self) -> None:
        """Гарантируем наличие карт (диск -> сеть). Блокирует только раз."""
        if self.loaded and (time.time() - self._fetched_at) < TTL:
            return
        if not self.loaded and self._load_disk():
            if (time.time() - self._fetched_at) < TTL:
                return
        try:
            await self._fetch_and_build()
        except Exception as exc:  # noqa: BLE001
            # не критично: остаётся транслитерация и статические словари
            logger.warning("Локализация недоступна (%s); работает транслит-фолбэк", exc)

    async def _fetch_and_build(self) -> None:
        headers = {"Accept": "application/json",
                   "User-Agent": "Mozilla/5.0 (compatible; CS2PriceBot/1.0)"}
        async with httpx.AsyncClient(timeout=60.0, headers=headers,
                                     follow_redirects=True) as client:
            en_resp = await client.get(EN_URL)
            en_resp.raise_for_status()
            ru_resp = await client.get(RU_URL)
            ru_resp.raise_for_status()
            en = en_resp.json()
            ru = ru_resp.json()
        self._build(en, ru)
        self._fetched_at = time.time()
        self.loaded = True
        self._save_disk()

    def _build(self, en, ru) -> None:
        if not isinstance(en, list) or not isinstance(ru, list):
            return
        en_by_id = {d.get("id"): d for d in en if isinstance(d, dict)}
        patterns: dict[str, str] = {}
        weapons: dict[str, str] = {}
        for r in ru:
            if not isinstance(r, dict):
                continue
            e = en_by_id.get(r.get("id"))
            if not e:
                continue
            rp = (r.get("pattern") or {}).get("name")
            ep = (e.get("pattern") or {}).get("name")
            if rp and ep:
                patterns[_key(str(rp))] = str(ep).lower()
            rw = (r.get("weapon") or {}).get("name")
            ew = (e.get("weapon") or {}).get("name")
            if rw and ew and _key(str(rw)) != _key(str(ew)):
                weapons[_key(str(rw))] = str(ew).lower()

        # игнорируем вырожденные ключи (пустые/из одной буквы)
        self.ru_patterns = {k: v for k, v in patterns.items() if len(k) > 1}
        self.ru_weapons = {k: v for k, v in weapons.items() if len(k) > 1}

    # ------- дисковый кэш -------
    def _save_disk(self) -> None:
        try:
            with open(CACHE_FILE, "wb") as f:
                pickle.dump({"p": self.ru_patterns, "w": self.ru_weapons,
                             "at": self._fetched_at}, f)
        except Exception as exc:  # noqa: BLE001
            logger.debug("Не удалось сохранить кэш локализации: %s", exc)

    def _load_disk(self) -> bool:
        try:
            with open(CACHE_FILE, "rb") as f:
                d = pickle.load(f)
            self.ru_patterns = d["p"]
            self.ru_weapons = d["w"]
            self._fetched_at = d["at"]
            self.loaded = True
            return True
        except Exception:  # noqa: BLE001
            return False


LOCALIZATION = Localization()
