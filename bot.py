"""Telegram-бот поиска цен на скины CS2 по разным площадкам.

Пользователь присылает название скина — бот параллельно опрашивает включённые
площадки (LisSkins, CS.Money, AIM Market, Steam) и присылает сводку цен,
отсортированную от дешёвых к дорогим.

Запуск:
    export TELEGRAM_TOKEN="123:ABC"
    python bot.py
"""
from __future__ import annotations

import asyncio
import html
import logging

import httpx
from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

import config
from providers import PriceResult, build_providers

logging.basicConfig(
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger("cs2-price-bot")

# Провайдеры создаём один раз (у LisSkins внутри кэш фида)
PROVIDERS = build_providers(config.ENABLED_PROVIDERS)

START_TEXT = (
    "👋 Привет! Я ищу цены на скины CS2 по площадкам:\n"
    + ", ".join(p.name for p in PROVIDERS)
    + ".\n\n"
    "Просто пришли название скина, например:\n"
    "<code>AK-47 | Redline (Field-Tested)</code>\n\n"
    "Или командой: <code>/price AWP | Asiimov (Field-Tested)</code>"
)

HELP_TEXT = (
    "📖 <b>Как пользоваться</b>\n\n"
    "• Пришли название скина текстом — я найду минимальные цены.\n"
    "• <code>/price &lt;название&gt;</code> — то же самое командой.\n\n"
    "Точнее всего работает полное имя со стиранием, например:\n"
    "<code>M4A4 | Howl (Minimal Wear)</code>\n\n"
    "Площадки опрашиваются параллельно; если одна недоступна — покажу остальные."
)


async def search_all(query: str) -> list[PriceResult]:
    """Опрашиваем все площадки параллельно, каждая изолирована от чужих сбоев."""
    query = query.strip()
    async with httpx.AsyncClient(
        timeout=config.REQUEST_TIMEOUT,
        follow_redirects=True,
        headers={"User-Agent": "Mozilla/5.0 (compatible; CS2PriceBot/1.0)"},
    ) as client:
        tasks = [p.search(client, query) for p in PROVIDERS]
        results = await asyncio.gather(*tasks, return_exceptions=True)

    out: list[PriceResult] = []
    for provider, res in zip(PROVIDERS, results):
        if isinstance(res, Exception):
            logger.exception("Провайдер %s упал: %s", provider.name, res)
            out.append(PriceResult(market=provider.name, query=query,
                                   error="внутренняя ошибка"))
        else:
            out.append(res)
    return out


def format_results(query: str, results: list[PriceResult]) -> str:
    """Формируем HTML-сообщение со сводкой цен."""
    lines = [f"🔎 <b>{html.escape(query)}</b>\n"]

    found = [r for r in results if r.ok]
    found.sort(key=lambda r: r.price)  # от дешёвых к дорогим

    if found:
        cheapest = found[0]
        for r in found:
            name = html.escape(r.matched_name or query)
            price = f"{r.price:.2f} {r.currency}"
            extra = f" · {r.count} шт." if r.count else ""
            mark = "🥇 " if r is cheapest else ""
            title = html.escape(r.market)
            if r.url:
                title = f'<a href="{html.escape(r.url, quote=True)}">{title}</a>'
            lines.append(f"{mark}<b>{title}</b> — {price}{extra}\n<i>{name}</i>")
    else:
        lines.append("😕 Нигде не нашёл цену по этому запросу.")

    # Показываем и площадки без результата — так видно, где не нашлось/ошибка
    misses = [r for r in results if not r.ok]
    if misses:
        lines.append("")
        parts = [f"{html.escape(r.market)}: {html.escape(r.error or 'нет данных')}"
                 for r in misses]
        lines.append("<i>Без цены — " + "; ".join(parts) + "</i>")

    return "\n".join(lines)


async def handle_query(update: Update, query: str) -> None:
    query = query.strip()
    if not query:
        await update.effective_message.reply_text(
            "Пришли название скина, например: AK-47 | Redline (Field-Tested)")
        return

    thinking = await update.effective_message.reply_text("⏳ Ищу цены…")
    try:
        results = await search_all(query)
        text = format_results(query, results)
    except Exception:  # noqa: BLE001
        logger.exception("Ошибка при обработке запроса %r", query)
        text = "⚠️ Что-то пошло не так при поиске. Попробуй ещё раз."

    await thinking.edit_text(
        text, parse_mode=ParseMode.HTML, disable_web_page_preview=True)


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.effective_message.reply_text(START_TEXT, parse_mode=ParseMode.HTML)


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.effective_message.reply_text(HELP_TEXT, parse_mode=ParseMode.HTML)


async def cmd_price(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = " ".join(context.args) if context.args else ""
    await handle_query(update, query)


async def on_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await handle_query(update, update.effective_message.text or "")


def main() -> None:
    if not config.TELEGRAM_TOKEN:
        raise SystemExit(
            "Не задан TELEGRAM_TOKEN. Получите токен у @BotFather и задайте его в "
            "переменной окружения TELEGRAM_TOKEN (или в файле .env)."
        )
    if not PROVIDERS:
        raise SystemExit("Не включено ни одной площадки (проверьте ENABLED_PROVIDERS).")

    app = Application.builder().token(config.TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(CommandHandler("price", cmd_price))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_message))

    logger.info("Бот запущен. Площадки: %s", ", ".join(p.name for p in PROVIDERS))
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
