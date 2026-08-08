"""Чистые функции разбора исходного xlsx-опросника.

Живут в пакете, а не в скрипте, потому что их поведение неочевидно
и должно быть закреплено тестами.
"""

from __future__ import annotations

import re

_SECTION = re.compile(r"^\s*(?:\d+\.\s*)?([А-ЯЁ][А-ЯЁ \-/()]{4,})\s*$")
_INLINE_SCALE = re.compile(r"^\s*(\d+)\s*[-–—]\s*(.+)$")
"""Балл может быть многозначным: в опроснике Candida встречаются 10, 20, 35."""

_TRANSLIT = str.maketrans(
    {
        "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e", "ё": "e",
        "ж": "z", "з": "z", "и": "i", "й": "y", "к": "k", "л": "l", "м": "m",
        "н": "n", "о": "o", "п": "p", "р": "r", "с": "s", "т": "t", "у": "u",
        "ф": "f", "х": "h", "ц": "c", "ч": "c", "ш": "s", "щ": "s", "ъ": "",
        "ы": "y", "ь": "", "э": "e", "ю": "u", "я": "a",
    }
)


def slugify(title: str) -> str:
    """Превратить русское название блока в латинский идентификатор."""
    latin = title.strip().lower().translate(_TRANSLIT)
    return re.sub(r"[^a-z0-9]+", "_", latin).strip("_")


def split_inline_scale(text: str) -> tuple[str, list[dict]]:
    """Отделить шкалу, вписанную в текст вопроса переводами строки.

    Возвращает текст вопроса и список вариантов. Если шкалы нет,
    список пуст и применяется шкала блока.
    """
    question_lines: list[str] = []
    options: list[dict] = []
    for line in text.splitlines():
        if not line.strip():
            continue
        if (m := _INLINE_SCALE.match(line)) is not None:
            options.append({"score": int(m.group(1)), "label": m.group(2).strip()})
        else:
            question_lines.append(line.strip())
    return " ".join(question_lines), options


def is_section_heading(text: str) -> str | None:
    """Название секции, если строка им является, иначе None."""
    if not text:
        return None
    match = _SECTION.match(text)
    return match.group(1).strip() if match else None
