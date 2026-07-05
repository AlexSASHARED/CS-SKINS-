"""Провайдер CS.Money.

Работает через публичный market-эндпоинт, который отдаёт лоты продажи,
отсортированные по цене. Запрос идёт по названию, поэтому фид кэшировать
не нужно — просто берём самый дешёвый подходящий лот.

Эндпоинт может меняться (CS.Money периодически его правит). Если провайдер
начал возвращать ошибку — проверьте API_URL и метод _parse().
"""
from __future__ import annotations

from urllib.parse import quote_plus

import httpx

from .base import BaseProvider, PriceResult, normalize, tokens

API_URL = "https://cs.money/1.0/market/sell-orders"


class CSMoneyProvider(BaseProvider):
    name = "CS.Money"

    async def search(self, client: httpx.AsyncClient, query: str) -> PriceResult:
        params = {
            "limit": 60,
            "offset": 0,
            "sort": "price",
            "order": "asc",
            "name": query,
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
            url="https://cs.money/csgo/store/?search=" + quote_plus(query),
        )

    @staticmethod
    def _parse(data, query):
        """Достаём (имя, цена, количество) самого дешёвого подходящего лота."""
        items = data
        if isinstance(data, dict):
            for key in ("items", "data", "orders", "result"):
                if isinstance(data.get(key), list):
                    items = data[key]
                    break
        if not isinstance(items, list) or not items:
            return None

        qtokens = tokens(query)
        best = None  # (name, price)
        for it in items:
            if not isinstance(it, dict):
                continue
            name = _dig(it, ["asset", "names", "full"]) or it.get("name") \
                or it.get("fullName") or it.get("market_hash_name")
            price = _dig(it, ["pricing", "computed"]) or _dig(it, ["price"]) \
                or it.get("price")
            if name is None or price is None:
                continue
            try:
                price = float(price)
            except (TypeError, ValueError):
                continue
            # если ищем по токенам — отсеиваем нерелевантные лоты
            if qtokens and not all(tok in normalize(str(name)) for tok in qtokens):
                continue
            if best is None or price < best[1]:
                best = (str(name), price)

        if best is None:
            return None
        return best[0], best[1], None


def _dig(obj, path):
    """Безопасно достаём вложенное значение по списку ключей."""
    cur = obj
    for key in path:
        if isinstance(cur, dict) and key in cur:
            cur = cur[key]
        else:
            return None
    return cur
