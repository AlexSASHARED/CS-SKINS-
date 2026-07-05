"""Telegram-бот поиска цен на скины CS2 по разным площадкам.

Пользователь присылает название скина (на русском или английском). Бот:
  1. переводит запрос в английские названия каталога;
  2. если совпадений несколько — показывает кнопки выбора скина;
  3. затем кнопки выбора износа (FN/MW/FT/WW/BS);
  4. по точному имени параллельно опрашивает площадки и присылает сводку цен.

Запуск:
    export TELEGRAM_TOKEN="123:ABC"
    python bot.py
"""
from __future__ import annotations

import asyncio
import hashlib
import html
import logging

import httpx
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ParseMode
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

import config
from catalog import CATALOG
from localization import LOCALIZATION
from providers import PriceResult, build_providers
from skinutils import WEAR_ORDER, WEAR_SHORT
from translit import translate_query

logging.basicConfig(
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger("cs2-price-bot")

# Провайдеры создаём один раз (у LisSkins/каталога внутри кэш фида)
PROVIDERS = build_providers(config.ENABLED_PROVIDERS)

# Кэш коротких токенов для callback_data (ограничение Telegram — 64 байта).
# token(md5-обрезок) -> строка (нормализованное базовое имя или полное имя).
_TOKENS: dict[str, str] = {}


def _token(value: str) -> str:
    key = hashlib.md5(value.encode("utf-8")).hexdigest()[:12]
    _TOKENS[key] = value
    return key


START_TEXT = (
    "👋 Привет! Я ищу цены на скины CS2 по площадкам:\n"
    + ", ".join(p.name for p in PROVIDERS)
    + ".\n\n"
    "Пришли название скина — можно <b>по-русски или по-английски</b>, например:\n"
    "<code>ак редлайн</code> или <code>AK-47 Redline</code>\n\n"
    "Я покажу кнопки для выбора конкретного скина и износа. Можно сразу указать "
    "износ: <code>калаш редлайн бс</code> или <code>AWP Asiimov FT</code>."
)

HELP_TEXT = (
    "📖 <b>Как пользоваться</b>\n\n"
    "• Пришли название скина текстом (RU/EN) — я найду минимальные цены.\n"
    "• Если вариантов несколько — выберешь кнопкой скин, затем износ.\n"
    "• Износ можно указать сразу словом или сокращением: "
    "FN/MW/FT/WW/BS или фн/мв/фт/вв/бс.\n"
    "• <code>/price &lt;название&gt;</code> — то же самое командой.\n\n"
    "Примеры: <code>ак редлайн</code>, <code>awp азимов ft</code>, "
    "<code>M4A1-S Printstream</code>, <code>нож керамбит fade</code>.\n\n"
    "Площадки опрашиваются параллельно; если одна недоступна — покажу остальные."
)


# --------------------------------------------------------------------------- #
#  Поиск цен по площадкам
# --------------------------------------------------------------------------- #
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

    misses = [r for r in results if not r.ok]
    if misses:
        lines.append("")
        parts = [f"{html.escape(r.market)}: {html.escape(r.error or 'нет данных')}"
                 for r in misses]
        lines.append("<i>Без цены — " + "; ".join(parts) + "</i>")

    return "\n".join(lines)


async def _run_prices(message, full_name: str, *, edit: bool) -> None:
    """Ищем цены по точному имени и показываем результат (новым или тем же сообщением)."""
    placeholder = "⏳ Ищу цены: <b>%s</b>…" % html.escape(full_name)
    if edit:
        target = message
        await target.edit_text(placeholder, parse_mode=ParseMode.HTML)
    else:
        target = await message.reply_text(placeholder, parse_mode=ParseMode.HTML)

    try:
        results = await search_all(full_name)
        text = format_results(full_name, results)
    except Exception:  # noqa: BLE001
        logger.exception("Ошибка при поиске цен %r", full_name)
        text = "⚠️ Что-то пошло не так при поиске. Попробуй ещё раз."

    await target.edit_text(text, parse_mode=ParseMode.HTML,
                           disable_web_page_preview=True)


# --------------------------------------------------------------------------- #
#  Экраны выбора: скин -> износ
# --------------------------------------------------------------------------- #
async def _show_bases(message, bases, total, wear, *, edit: bool) -> None:
    widx = (WEAR_ORDER.index(wear) + 1) if wear else 0
    keyboard = [
        [InlineKeyboardButton(b["name"], callback_data=f"b:{_token(nb)}:{widx}")]
        for nb, b in bases
    ]
    text = "🔎 Нашёл несколько вариантов — выбери скин:"
    if total > len(bases):
        text += f"\n<i>Показаны первые {len(bases)} из {total}. Уточни запрос, если нужного нет.</i>"
    markup = InlineKeyboardMarkup(keyboard)
    if edit:
        await message.edit_text(text, reply_markup=markup, parse_mode=ParseMode.HTML)
    else:
        await message.reply_text(text, reply_markup=markup, parse_mode=ParseMode.HTML)


async def _show_wears(message, base_entry, wear, *, edit: bool) -> None:
    wears = base_entry["wears"]

    # Износ уже выбран пользователем и доступен — сразу к ценам
    if wear and wear in wears:
        await _run_prices(message, wears[wear], edit=edit)
        return
    # У предмета нет градаций износа — одно значение
    if list(wears.keys()) == [""]:
        await _run_prices(message, wears[""], edit=edit)
        return

    row = [
        InlineKeyboardButton(WEAR_SHORT[w], callback_data=f"w:{_token(wears[w])}")
        for w in WEAR_ORDER if w in wears
    ]
    keyboard = [[btn] for btn in row]  # по одной кнопке в ряд — подписи длинные
    if "" in wears:
        keyboard.append(
            [InlineKeyboardButton("Без износа", callback_data=f"w:{_token(wears[''])}")]
        )

    text = f"🎯 <b>{html.escape(base_entry['name'])}</b>\nВыбери износ:"
    markup = InlineKeyboardMarkup(keyboard)
    if edit:
        await message.edit_text(text, reply_markup=markup, parse_mode=ParseMode.HTML)
    else:
        await message.reply_text(text, reply_markup=markup, parse_mode=ParseMode.HTML)


# --------------------------------------------------------------------------- #
#  Обработчики
# --------------------------------------------------------------------------- #
async def handle_text(message, raw: str) -> None:
    raw = (raw or "").strip()
    if not raw:
        await message.reply_text(
            "Пришли название скина, например: ак редлайн или AK-47 Redline")
        return

    query, wear = translate_query(raw)
    query = query or raw

    # Каталог отдаётся из кэша мгновенно; ждём только при самой первой загрузке.
    try:
        await CATALOG.ensure()
    except Exception:  # noqa: BLE001
        logger.warning("Каталог недоступен, прямой поиск по %r", query)
        await _run_prices(await message.reply_text("⏳ Ищу цены…"),
                          query, edit=True)
        return

    bases, total = CATALOG.search_bases(query)
    if not bases:
        await message.reply_text(
            f"😕 Не нашёл скин по запросу «{html.escape(raw)}».\n"
            "Попробуй иначе, например: <code>AK-47 Redline</code> или "
            "<code>ак редлайн</code>.",
            parse_mode=ParseMode.HTML)
        return

    if len(bases) == 1:
        await _show_wears(message, bases[0][1], wear, edit=False)
    else:
        await _show_bases(message, bases, total, wear, edit=False)


async def on_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    data = query.data or ""

    if data.startswith("b:"):
        _, tok, widx = data.split(":", 2)
        nb = _TOKENS.get(tok)
        entry = CATALOG.bases.get(nb) if nb else None
        if entry is None:
            await query.edit_message_text(
                "⏳ Сессия устарела — отправь название скина заново.")
            return
        wear = WEAR_ORDER[int(widx) - 1] if widx != "0" else None
        await _show_wears(query.message, entry, wear, edit=True)

    elif data.startswith("w:"):
        _, tok = data.split(":", 1)
        full_name = _TOKENS.get(tok)
        if not full_name:
            await query.edit_message_text(
                "⏳ Сессия устарела — отправь название скина заново.")
            return
        await _run_prices(query.message, full_name, edit=True)


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.effective_message.reply_text(START_TEXT, parse_mode=ParseMode.HTML)


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.effective_message.reply_text(HELP_TEXT, parse_mode=ParseMode.HTML)


async def cmd_price(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await handle_text(update.effective_message,
                      " ".join(context.args) if context.args else "")


async def on_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await handle_text(update.effective_message, update.effective_message.text or "")


async def _post_init(app: Application) -> None:
    """Прогреваем каталог в фоне сразу после старта, чтобы первый запрос не ждал фид."""
    async def _warm() -> None:
        try:
            await CATALOG.ensure()
            logger.info("Каталог прогрет: %d скинов", len(CATALOG.bases))
        except Exception as exc:  # noqa: BLE001
            logger.warning("Не удалось прогреть каталог при старте: %s", exc)

    async def _warm_loc() -> None:
        await LOCALIZATION.ensure()
        if LOCALIZATION.loaded:
            logger.info("Локализация прогрета: %d финишей, %d видов оружия",
                        len(LOCALIZATION.ru_patterns), len(LOCALIZATION.ru_weapons))

    asyncio.create_task(_warm())
    asyncio.create_task(_warm_loc())


def main() -> None:
    if not config.TELEGRAM_TOKEN:
        raise SystemExit(
            "Не задан TELEGRAM_TOKEN. Получите токен у @BotFather и задайте его в "
            "переменной окружения TELEGRAM_TOKEN (или в файле .env)."
        )
    if not PROVIDERS:
        raise SystemExit("Не включено ни одной площадки (проверьте ENABLED_PROVIDERS).")

    # В Python 3.12+/3.14 asyncio больше не создаёт event loop автоматически,
    # а python-telegram-bot внутри run_polling вызывает asyncio.get_event_loop().
    try:
        asyncio.get_event_loop()
    except RuntimeError:
        asyncio.set_event_loop(asyncio.new_event_loop())

    app = Application.builder().token(config.TELEGRAM_TOKEN).post_init(_post_init).build()
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(CommandHandler("price", cmd_price))
    app.add_handler(CallbackQueryHandler(on_callback))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_message))

    logger.info("Бот запущен. Площадки: %s", ", ".join(p.name for p in PROVIDERS))
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
