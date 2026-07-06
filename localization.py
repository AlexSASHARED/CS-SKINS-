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

from skinutils import clean_phrase as _key

logger = logging.getLogger("cs2-price-bot.localization")

BASE_URL = "https://bymykel.github.io/CSGO-API/api/{lang}/{file}"
EN_URL = BASE_URL.format(lang="en", file="skins.json")
RU_URL = BASE_URL.format(lang="ru", file="skins.json")

# Дополнительные типы предметов, у которых нет разбивки на оружие/финиш —
# для них строим карту полных названий RU -> EN (кейсы, коллекции, агенты и т.д.).
EXTRA_FILES = [
    "crates.json",       # кейсы, капсулы, сувенирные наборы
    "collections.json",  # коллекции
    "agents.json",       # агенты
    "keychains.json",    # брелоки
    "graffiti.json",     # граффити
    "music_kits.json",   # музкиты
    "collectibles.json",  # значки/пины
]
TTL = 7 * 24 * 3600  # неделя
CACHE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                          ".localization_cache.pkl")


class Localization:
    def __init__(self) -> None:
        self.ru_patterns: dict[str, str] = {}
        self.ru_weapons: dict[str, str] = {}
        self.ru_names: dict[str, str] = {}   # полные названия прочих предметов
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
            en = await self._get_json(client, EN_URL)
            ru = await self._get_json(client, RU_URL)
            self._build(en, ru)

            # Прочие типы предметов — полные названия RU -> EN
            names: dict[str, str] = {}
            for file in EXTRA_FILES:
                try:
                    e = await self._get_json(client, BASE_URL.format(lang="en", file=file))
                    r = await self._get_json(client, BASE_URL.format(lang="ru", file=file))
                    self._merge_names(names, e, r)
                except Exception as exc:  # noqa: BLE001
                    logger.debug("Пропускаю %s: %s", file, exc)
            self.ru_names = names

        self._fetched_at = time.time()
        self.loaded = True
        self._save_disk()

    @staticmethod
    async def _get_json(client: httpx.AsyncClient, url: str):
        resp = await client.get(url)
        resp.raise_for_status()
        return resp.json()

    @staticmethod
    def _merge_names(dst: dict[str, str], en, ru) -> None:
        if not isinstance(en, list) or not isinstance(ru, list):
            return
        en_by_id = {d.get("id"): d for d in en if isinstance(d, dict)}
        for r in ru:
            if not isinstance(r, dict):
                continue
            e = en_by_id.get(r.get("id"))
            if not e:
                continue
            rn, en_name = r.get("name"), e.get("name")
            if rn and en_name:
                k = _key(str(rn))
                if len(k) > 1 and k != _key(str(en_name)):
                    dst[k] = str(en_name).lower()

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
                             "n": self.ru_names, "at": self._fetched_at}, f)
        except Exception as exc:  # noqa: BLE001
            logger.debug("Не удалось сохранить кэш локализации: %s", exc)

    def _load_disk(self) -> bool:
        try:
            with open(CACHE_FILE, "rb") as f:
                d = pickle.load(f)
            self.ru_patterns = d["p"]
            self.ru_weapons = d["w"]
            self.ru_names = d.get("n", {})
            self._fetched_at = d["at"]
            self.loaded = True
            return True
        except Exception:  # noqa: BLE001
            return False


LOCALIZATION = Localization()
