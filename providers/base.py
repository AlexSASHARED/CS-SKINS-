"""Базовый интерфейс провайдера площадки и общая модель результата."""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional

import httpx


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


def normalize(name: str) -> str:
    """Приводим название к единому виду для сравнения.

    Убираем регистр, лишние пробелы и повторяющиеся разделители, чтобы
    'AK-47 | Redline (Field-Tested)' и 'ak47 redline field tested'
    считались похожими.
    """
    name = name.lower()
    name = name.replace("★", " ").replace("™", " ")
    # унифицируем разделители
    name = re.sub(r"[|()\-_/]", " ", name)
    name = re.sub(r"\s+", " ", name)
    return name.strip()


def tokens(name: str) -> list[str]:
    return [t for t in normalize(name).split(" ") if t]


class BaseProvider:
    """Наследники реализуют search(). Имя площадки задаётся в name."""

    name: str = "base"
    enabled: bool = True

    async def search(self, client: httpx.AsyncClient, query: str) -> PriceResult:
        raise NotImplementedError

    # Утилита для единообразного формирования результата с ошибкой
    def _error(self, query: str, message: str) -> PriceResult:
        return PriceResult(market=self.name, query=query, error=message)
