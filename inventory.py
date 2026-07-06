"""Загрузка публичного инвентаря CS2 из Steam по SteamID / ссылке на профиль.

Возвращает словарь market_hash_name -> количество (только предметы CS2).
Дальше бот оценивает его по фид-площадкам (LisSkins, Skinport), где есть весь
прайс-лист, поэтому оценка всего инвентаря считается мгновенно.
"""
from __future__ import annotations

import re

import httpx

APPID = 730          # CS2 / CS:GO
CONTEXTID = 2        # обычный игровой инвентарь
STEAMID64_RE = re.compile(r"7656\d{13}")


class InventoryError(Exception):
    """Понятная пользователю ошибка (приватный профиль, не найден и т.п.)."""


async def resolve_steamid(client: httpx.AsyncClient, text: str) -> str | None:
    """Достаём steamID64 из числа, ссылки /profiles/<id> или /id/<vanity>."""
    text = text.strip()

    m = re.search(r"/profiles/(7656\d{13})", text)
    if m:
        return m.group(1)

    # голый steamID64
    if STEAMID64_RE.fullmatch(text):
        return text

    # vanity: ссылка /id/<name> или просто ник
    vanity = None
    m = re.search(r"steamcommunity\.com/id/([^/?#]+)", text)
    if m:
        vanity = m.group(1)
    elif re.fullmatch(r"[A-Za-z0-9_.-]{2,32}", text):
        vanity = text

    if vanity:
        # публичный XML профиля содержит <steamID64>
        resp = await client.get(f"https://steamcommunity.com/id/{vanity}",
                                params={"xml": 1}, timeout=15.0)
        resp.raise_for_status()
        mm = re.search(r"<steamID64>(\d+)</steamID64>", resp.text)
        if mm:
            return mm.group(1)

    # запасной вариант — любой steamID64 внутри строки
    m = STEAMID64_RE.search(text)
    return m.group(0) if m else None


async def fetch_inventory(client: httpx.AsyncClient, steamid64: str,
                          max_pages: int = 6) -> dict[str, int]:
    """Публичный инвентарь CS2 -> {market_hash_name: количество}.

    Пролистываем страницы (по 2000 предметов). Приватный/закрытый инвентарь
    даёт 403 -> InventoryError.
    """
    counts: dict[str, int] = {}
    url = f"https://steamcommunity.com/inventory/{steamid64}/{APPID}/{CONTEXTID}"
    start_assetid: str | None = None

    for _ in range(max_pages):
        params = {"l": "english", "count": 2000}
        if start_assetid:
            params["start_assetid"] = start_assetid
        resp = await client.get(url, params=params, timeout=30.0)
        if resp.status_code == 403:
            raise InventoryError("инвентарь скрыт (приватный профиль)")
        if resp.status_code == 429:
            raise InventoryError("Steam временно ограничил запросы, попробуй позже")
        resp.raise_for_status()
        data = resp.json()
        if not data or not data.get("descriptions"):
            break

        # classid(+instanceid) -> market_hash_name
        desc: dict[tuple, str] = {}
        for d in data["descriptions"]:
            name = d.get("market_hash_name")
            if name:
                desc[(d.get("classid"), d.get("instanceid"))] = name

        for a in data.get("assets", []):
            name = desc.get((a.get("classid"), a.get("instanceid")))
            if name:
                counts[name] = counts.get(name, 0) + 1

        if data.get("more_items") and data.get("last_assetid"):
            start_assetid = data["last_assetid"]
        else:
            break

    return counts
