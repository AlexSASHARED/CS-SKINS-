"""Реестр провайдеров площадок.

Чтобы добавить новую площадку: создайте класс-наследник BaseProvider в новом
модуле и зарегистрируйте его в ALL_PROVIDERS ниже.
"""
from __future__ import annotations

from .aimmarket import AimMarketProvider
from .base import BaseProvider, PriceResult
from .csmoney import CSMoneyProvider
from .lisskins import LisSkinsProvider
from .steam import SteamProvider

# ключ (нижним регистром) -> класс провайдера
ALL_PROVIDERS: dict[str, type[BaseProvider]] = {
    "lisskins": LisSkinsProvider,
    "csmoney": CSMoneyProvider,
    "aimmarket": AimMarketProvider,
    "steam": SteamProvider,
}


def build_providers(enabled: list[str] | None = None) -> list[BaseProvider]:
    """Создаём экземпляры включённых провайдеров.

    enabled=None -> включаем все. Иначе — только перечисленные ключи.
    """
    if enabled is None:
        keys = list(ALL_PROVIDERS.keys())
    else:
        keys = [k.strip().lower() for k in enabled if k.strip()]

    providers: list[BaseProvider] = []
    for key in keys:
        cls = ALL_PROVIDERS.get(key)
        if cls is not None:
            providers.append(cls())
    return providers


__all__ = ["ALL_PROVIDERS", "build_providers", "BaseProvider", "PriceResult"]
