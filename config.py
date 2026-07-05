"""Конфигурация бота из переменных окружения (.env поддерживается)."""
from __future__ import annotations

import os

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    # python-dotenv не обязателен — можно задать переменные окружения напрямую
    pass


# Токен Telegram-бота от @BotFather
TELEGRAM_TOKEN: str = os.environ.get("TELEGRAM_TOKEN", "").strip()

# Список включённых площадок через запятую, например: "lisskins,csmoney,steam"
# Пусто -> включаются все доступные.
_enabled_raw = os.environ.get("ENABLED_PROVIDERS", "").strip()
ENABLED_PROVIDERS: list[str] | None = (
    [p for p in _enabled_raw.split(",") if p.strip()] if _enabled_raw else None
)

# Таймаут запроса к площадкам, секунд
REQUEST_TIMEOUT: float = float(os.environ.get("REQUEST_TIMEOUT", "15"))
