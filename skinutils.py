"""Общие утилиты для работы с названиями скинов (без внешних зависимостей).

Вынесены в отдельный модуль верхнего уровня, чтобы каталог и провайдеры могли
их импортировать без циклических импортов пакета providers.
"""
from __future__ import annotations

import re

# Порядок износов — используется для сортировки кнопок
WEAR_ORDER = [
    "Factory New",
    "Minimal Wear",
    "Field-Tested",
    "Well-Worn",
    "Battle-Scarred",
]

# Короткие подписи для кнопок
WEAR_SHORT = {
    "Factory New": "FN · Прямо с завода",
    "Minimal Wear": "MW · Немного поношенное",
    "Field-Tested": "FT · После полевых",
    "Well-Worn": "WW · Поношенное",
    "Battle-Scarred": "BS · Закалённое в боях",
}

_WEAR_RE = re.compile(
    r"\s*\((Factory New|Minimal Wear|Field-Tested|Well-Worn|Battle-Scarred)\)\s*$"
)


# Пунктуация -> пробел, но дефис сохраняем (ak-47, m4a1-s, нео-нуар).
_CLEAN_RE = re.compile(r"[^\w\s-]", re.UNICODE)


def clean_phrase(name: str) -> str:
    """Единая нормализация фраз для пословного матчинга (RU/EN словари).

    Нижний регистр, звёзды/™ и пунктуация (кавычки-ёлочки, скобки, точки…) ->
    пробел, дефис сохраняем, пробелы схлопываем. Чтобы 'кейс «Отдача»' и
    'кейс отдача' считались одним и тем же.
    """
    name = name.lower().replace("★", " ")
    name = _CLEAN_RE.sub(" ", name)
    return " ".join(name.split())


def normalize(name: str) -> str:
    """Приводим название к единому виду для сравнения."""
    name = name.lower()
    name = name.replace("★", " ").replace("™", " ")
    name = re.sub(r"[|()\-_/]", " ", name)
    name = re.sub(r"\s+", " ", name)
    return name.strip()


def tokens(name: str) -> list[str]:
    return [t for t in normalize(name).split(" ") if t]


def split_base_wear(name: str) -> tuple[str, str | None]:
    """Разбиваем полное имя на (базовое имя скина, износ).

    'AK-47 | Redline (Field-Tested)' -> ('AK-47 | Redline', 'Field-Tested')
    'Sticker | Titan (Holo)'         -> ('Sticker | Titan (Holo)', None)
    """
    m = _WEAR_RE.search(name)
    if m:
        return name[: m.start()].strip(), m.group(1)
    return name.strip(), None
