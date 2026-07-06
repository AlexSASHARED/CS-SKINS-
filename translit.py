"""Перевод/транслитерация пользовательского запроса (RU/EN) в форму,
пригодную для поиска по каталогу (английские названия LisSkins).

translate_query():
  1. вычленяет износ (FN/MW/FT/WW/BS и русские варианты);
  2. заменяет русские названия оружия и популярных скинов на английские;
  3. транслитерирует оставшуюся кириллицу как запасной вариант.

Словари намеренно небольшие и легко расширяются — добавьте пару alias -> english.
"""
from __future__ import annotations

import re

from localization import LOCALIZATION
from skinutils import clean_phrase

# Русские/сокращённые обозначения износа -> каноничное английское имя.
# Держим только однозначные варианты и стандартные сокращения, чтобы случайно
# не «съесть» слово из названия скина.
WEAR_ALIASES: dict[str, str] = {
    "прямо с завода": "Factory New",
    "factory new": "Factory New",
    "fn": "Factory New",
    "фн": "Factory New",
    "немного поношенное": "Minimal Wear",
    "minimal wear": "Minimal Wear",
    "mw": "Minimal Wear",
    "мв": "Minimal Wear",
    "после полевых испытаний": "Field-Tested",
    "field-tested": "Field-Tested",
    "field tested": "Field-Tested",
    "ft": "Field-Tested",
    "фт": "Field-Tested",
    "поношенное": "Well-Worn",
    "well-worn": "Well-Worn",
    "well worn": "Well-Worn",
    "ww": "Well-Worn",
    "вв": "Well-Worn",
    "закалённое в боях": "Battle-Scarred",
    "закаленное в боях": "Battle-Scarred",
    "battle-scarred": "Battle-Scarred",
    "battle scarred": "Battle-Scarred",
    "bs": "Battle-Scarred",
    "бс": "Battle-Scarred",
}

# Русские/разговорные названия оружия -> как оно пишется в каталоге (англ.)
WEAPON_ALIASES: dict[str, str] = {
    "калашников": "ak-47", "калаш": "ak-47", "ак-47": "ak-47",
    "ак47": "ak-47", "ак": "ak-47",
    "авп": "awp", "авпшка": "awp", "скаут": "ssg 08",
    "м4а4": "m4a4", "м4а1": "m4a1-s", "м4а1-с": "m4a1-s",
    "дезерт игл": "desert eagle", "пустынный орёл": "desert eagle",
    "дигл": "desert eagle", "орёл": "desert eagle",
    "глок": "glock-18", "глок-18": "glock-18",
    "усп": "usp-s", "юсп": "usp-s",
    "фамас": "famas", "галил": "galil ar", "галилка": "galil ar",
    "ауг": "aug", "сг": "sg 553", "сг553": "sg 553",
    "тек-9": "tec-9", "тек9": "tec-9", "файв-севен": "five-seven",
    "дуалы": "dual berettas", "дуал": "dual berettas",
    "маг-7": "mag-7", "негев": "negev", "мп9": "mp9", "мп7": "mp7",
    "п90": "p90", "п250": "p250", "п2000": "p2000",
    "нож": "knife", "штык-нож": "bayonet", "штык": "bayonet",
    "керамбит": "karambit", "бабочка": "butterfly knife",
    "перчатки": "gloves",
}

# Русские/транслит названия популярных скинов -> английское имя из каталога
PATTERN_ALIASES: dict[str, str] = {
    "редлайн": "redline", "редлан": "redline",
    "асиимов": "asiimov", "азимов": "asiimov", "асимов": "asiimov",
    "вулкан": "vulcan",
    "фейд": "fade", "градиент": "fade", "выцветание": "fade",
    "гипербист": "hyper beast", "гипер бист": "hyper beast",
    "нептун": "neptune",
    "драгон лор": "dragon lore", "лор дракона": "dragon lore",
    "медуза": "medusa",
    "хаул": "howl", "вой": "howl",
    "нео-нуар": "neo-noir", "неонуар": "neo-noir",
    "принтстрим": "printstream", "принт стрим": "printstream",
    "поток информации": "printstream",  # официальное RU-название Printstream
    "красная линия": "redline",
    "гипер-зверь": "hyper beast", "гипер зверь": "hyper beast",
    "императрица": "empress",
    "гунгнир": "gungnir",
    "кровавая паутина": "crimson web",
    "тигриный клык": "tiger tooth", "тигр": "tiger tooth",
    "дамасская сталь": "damascus steel", "дамаск": "damascus steel",
    "мраморный градиент": "marble fade", "марбл фейд": "marble fade",
    "доплер": "doppler", "неон райдер": "neon rider",
    "автотроник": "autotronic",
}

# Таблица транслитерации кириллицы (нижний регистр)
_TRANSLIT = {
    "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e", "ё": "e",
    "ж": "zh", "з": "z", "и": "i", "й": "y", "к": "k", "л": "l", "м": "m",
    "н": "n", "о": "o", "п": "p", "р": "r", "с": "s", "т": "t", "у": "u",
    "ф": "f", "х": "h", "ц": "ts", "ч": "ch", "ш": "sh", "щ": "sch",
    "ъ": "", "ы": "y", "ь": "", "э": "e", "ю": "yu", "я": "ya",
}


def transliterate(text: str) -> str:
    return "".join(_TRANSLIT.get(ch, ch) for ch in text)


# Статические словари с очищенными ключами (готовы к пословному матчингу)
_WEAPONS_C = {clean_phrase(k): v for k, v in WEAPON_ALIASES.items()}
_PATTERNS_C = {clean_phrase(k): v for k, v in PATTERN_ALIASES.items()}
_WEARS_C = {clean_phrase(k): v for k, v in WEAR_ALIASES.items()}

_MAX_WORDS = 8  # самое длинное составное название (кейсы/коллекции)


def _extract_wear(words: list[str]) -> tuple[str | None, list[str]]:
    """Находим и вырезаем из токенов упоминание износа (длиннейшее совпадение)."""
    n = len(words)
    for i in range(n):
        for j in range(min(4, n - i), 0, -1):
            phrase = " ".join(words[i:i + j])
            if phrase in _WEARS_C:
                return _WEARS_C[phrase], words[:i] + words[i + j:]
    return None, words


def _apply_map(words: list[str], mapping: dict[str, str]) -> list[str]:
    """Жадно заменяем последовательности слов на значения из словаря.

    На каждой позиции берём самую длинную фразу, которая есть в словаре
    (O(1) поиск по dict) — быстро даже для тысяч записей.
    """
    out: list[str] = []
    i, n = 0, len(words)
    while i < n:
        hit = False
        for j in range(min(_MAX_WORDS, n - i), 0, -1):
            phrase = " ".join(words[i:i + j])
            repl = mapping.get(phrase)
            if repl is not None:
                out.extend(repl.split())
                i += j
                hit = True
                break
        if not hit:
            out.append(words[i])
            i += 1
    return out


def translate_query(text: str) -> tuple[str, str | None]:
    """Возвращает (строка_для_поиска_на_английском, износ_или_None)."""
    words = clean_phrase(text).split()

    # 1. Износ (вырезаем из запроса)
    wear, words = _extract_wear(words)

    # 2. Единый словарь RU->EN: официальная локализация (кейсы/оружие/финиши)
    #    поверх статических синонимов. Самая длинная фраза выигрывает, поэтому
    #    'поток информации' (2 слова) бьёт любое односложное совпадение.
    combined = {
        **_WEAPONS_C, **_PATTERNS_C,
        **LOCALIZATION.ru_names,
        **LOCALIZATION.ru_weapons, **LOCALIZATION.ru_patterns,
    }
    words = _apply_map(words, combined)

    s = " ".join(words)
    # 3. Остаток кириллицы -> латиница (запасной вариант)
    if re.search(r"[а-яё]", s):
        s = transliterate(s)
    return " ".join(s.split()), wear
