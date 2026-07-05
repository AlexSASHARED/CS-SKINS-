"""Провайдер CSFloat (опциональный, нужен API-ключ).

Листинги CSFloat отдаются только с заголовком Authorization: <api-key>.
Ключ бесплатно берётся в профиле на csfloat.com (раздел разработчика) и
задаётся в переменной окружения CSFLOAT_API_KEY. Без ключа провайдер честно
сообщит об этом; включать его в ENABLED_PROVIDERS есть смысл только с ключом.

Docs: https://docs.csfloat.com/  (GET /api/v1/listings)
Цены CSFloat приходят в центах (целое число) -> делим на 100.
"""
from __future__ import annotations

import os
from urllib.parse import quote_plus

import httpx

from skinutils import normalize, tokens

from .base import BaseProvider, PriceResult

API_URL = "https://csfloat.com/api/v1/listings"


def _dig(obj, path):
    cur = obj
    for key in path:
        if isinstance(cur, dict) and key in cur:
            cur = cur[key]
        else:
            return None
    return cur


class CSFloatProvider(BaseProvider):
    name = "CSFloat"

    def __init__(self) -> None:
        self.api_key = os.environ.get("CSFLOAT_API_KEY", "").strip()

    async def search(self, client: httpx.AsyncClient, query: str) -> PriceResult:
        headers = {
            "Accept": "application/json",
            "User-Agent": "Mozilla/5.0 (compatible; CS2PriceBot/1.0)",
        }
        if self.api_key:
            headers["Authorization"] = self.api_key
        params = {
            "market_hash_name": query,
            "sort_by": "lowest_price",
            "type": "buy_now",
            "limit": 20,
        }
        try:
            resp = await client.get(API_URL, params=params, headers=headers, timeout=10.0)
            resp.raise_for_status()
            data = resp.json()
        except httpx.HTTPStatusError as exc:
            code = exc.response.status_code
            if code in (401, 403) and not self.api_key:
                return self._error(query, "нужен CSFLOAT_API_KEY")
            return self._error(query, f"HTTP {code}")
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
            url="https://csfloat.com/search?market_hash_name=" + quote_plus(query),
        )

    @staticmethod
    def _parse(data, query):
        items = data
        if isinstance(data, dict):
            for key in ("data", "listings", "results"):
                if isinstance(data.get(key), list):
                    items = data[key]
                    break
        if not isinstance(items, list) or not items:
            return None

        qt = tokens(query)
        best = None
        for it in items:
            if not isinstance(it, dict):
                continue
            name = _dig(it, ["item", "market_hash_name"]) or it.get("market_hash_name")
            price = it.get("price")  # в центах
            if name is None or price is None:
                continue
            try:
                price = float(price) / 100.0
            except (TypeError, ValueError):
                continue
            if qt and not all(t in normalize(str(name)) for t in qt):
                continue
            if best is None or price < best[1]:
                best = (str(name), price)

        return (best[0], best[1], None) if best else None
