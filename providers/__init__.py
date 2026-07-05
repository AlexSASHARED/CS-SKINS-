"""Реестр провайдеров площадок.

Чтобы добавить новую площадку: создайте класс-наследник BaseProvider в новом
модуле и зарегистрируйте его в ALL_PROVIDERS ниже.
"""
from __future__ import annotations

from .aimmarket import AimMarketProvider
from .base import BaseProvider, PriceResult
from .csfloat import CSFloatProvider
from .csmoney import CSMoneyProvider
from .lisskins import LisSkinsProvider
from .skinport import SkinportProvider
from .steam import SteamProvider

# ключ (нижним регистром) -> класс провайдера
ALL_PROVIDERS: dict[str, type[BaseProvider]] = {
    "lisskins": LisSkinsProvider,     # открытый фид, без ключа
    "skinport": SkinportProvider,     # открытый фид, без ключа
    "steam": SteamProvider,           # открытый API, без ключа
    "csfloat": CSFloatProvider,       # нужен CSFLOAT_API_KEY
    "csmoney": CSMoneyProvider,       # за Cloudflare, нестабильно
    "aimmarket": AimMarketProvider,   # за Cloudflare, нестабильно
}

# Набор по умолчанию (когда ENABLED_PROVIDERS не задан): только надёжные
# площадки с открытым API без ключей.
DEFAULT_ENABLED = ["lisskins", "skinport", "steam"]


def build_providers(enabled: list[str] | None = None) -> list[BaseProvider]:
    """Создаём экземпляры включённых провайдеров.

    enabled=None -> набор по умолчанию (DEFAULT_ENABLED).
    Иначе — только перечисленные ключи (в заданном порядке).
    """
    keys = DEFAULT_ENABLED if enabled is None else [
        k.strip().lower() for k in enabled if k.strip()
    ]
    providers: list[BaseProvider] = []
    for key in keys:
        cls = ALL_PROVIDERS.get(key)
        if cls is not None:
            providers.append(cls())
    return providers


__all__ = [
    "ALL_PROVIDERS",
    "DEFAULT_ENABLED",
    "build_providers",
    "BaseProvider",
    "PriceResult",
]
