"""Базовый интерфейс провайдера площадки и общая модель результата."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import httpx

# Утилиты имён живут в модуле верхнего уровня, чтобы избежать циклических
# импортов; ре-экспортируем их здесь для удобства провайдеров.
from skinutils import normalize, tokens  # noqa: F401


@dataclass
class PriceResult:
    """Результат поиска цены на одной площадке."""

    market: str                     # человекочитаемое имя площадки (LisSkins, CS.Money, ...)
    query: str                      # исходный запрос пользователя
    matched_name: Optional[str] = None   # что реально нашлось на площадке
    price: Optional[float] = None        # минимальная цена
    currency: str = "USD"
    url: Optional[str] = None            # ссылка на позицию/поиск
    count: Optional[int] = None          # сколько лотов в наличии
    error: Optional[str] = None          # текст ошибки, если что-то пошло не так

    @property
    def ok(self) -> bool:
        return self.error is None and self.price is not None


class BaseProvider:
    """Наследники реализуют search(). Имя площадки задаётся в name."""

    name: str = "base"
    enabled: bool = True

    async def search(self, client: httpx.AsyncClient, query: str) -> PriceResult:
        raise NotImplementedError

    # Утилита для единообразного формирования результата с ошибкой
    def _error(self, query: str, message: str) -> PriceResult:
        return PriceResult(market=self.name, query=query, error=message)
