"""Разбор строк выгрузки лаборатории в записи бланка.

Роли колонок берутся из строки-шапки, а не из позиции: у одной
лаборатории единицы стоят до референса, у другой — после. Строка,
которая однозначно не читается, не разбирается по частям, а доходит
до коуча целиком: догадка здесь стоила бы неверного числа в анализе.
"""

from __future__ import annotations

import math
import re
from collections.abc import Sequence
from dataclasses import dataclass

ROLE_NAME = "название"
ROLE_VALUE = "значение"
ROLE_UNITS = "единицы"
ROLE_REFERENCE = "референс"

_ROLES_REQUIRED = (ROLE_NAME, ROLE_VALUE, ROLE_UNITS, ROLE_REFERENCE)

_HEADER_WORDS = {
    "исследование": ROLE_NAME,
    "показатель": ROLE_NAME,
    "параметр": ROLE_NAME,
    "значение": ROLE_VALUE,
    "результат": ROLE_VALUE,
    "ед": ROLE_UNITS,
    "нормальные": ROLE_REFERENCE,
    "референсные": ROLE_REFERENCE,
}

_LAB_CODE = re.compile(r"\bA\d{2}\.\d{2}\.\d{3}\b\s*(\([^()]*\))?")
_NUMBER = re.compile(r"^[<>]?\d+(?:[.,]\d+)?$")
_STARTS_WITH_NUMBER = re.compile(r"^\s*[<>]?\d")
_HAS_DIGIT = re.compile(r"\d")
_SERVICE = re.compile(r"^\s*(Дата исследования|Штрихкод|Материал|Вн\.№)")
_SPACES = re.compile(r"\s+")


class LabTableError(Exception):
    """Выгрузку разобрать нельзя."""


@dataclass(frozen=True)
class LabRow:
    name: str
    value_text: str
    units: str
    reference_text: str
    line: str


@dataclass(frozen=True)
class LabTable:
    rows: tuple[LabRow, ...]
    unparsed: tuple[str, ...]
    """Строки, которые не читаются однозначно. Показываются коучу как есть."""


def parse_number(text: str) -> float | None:
    """Число из ячейки бланка. None, если числа там нет.

    «<0.60» числом не считается: настоящее значение меньше, а насколько —
    неизвестно, и подстановка 0.60 исказила бы динамику. «nan»/«inf» тоже
    не числа бланка: они молча испортили бы любое дальнейшее сравнение
    с коридором нормы.
    """
    cleaned = text.strip().replace(",", ".")
    try:
        value = float(cleaned)
    except ValueError:
        return None
    if not math.isfinite(value):
        return None
    return value


def _header_word_roles(line: str) -> list[str]:
    """Роли, узнанные среди слов строки, по порядку появления."""
    roles: list[str] = []
    for word in _SPACES.split(line.strip().casefold()):
        role = _HEADER_WORDS.get(word.strip(".:"))
        if role is not None and role not in roles:
            roles.append(role)
    return roles


def _unrecognised_header_words(line: str) -> list[str]:
    """Слова строки-шапки, не сопоставленные ни одной роли."""
    words: list[str] = []
    for word in _SPACES.split(line.strip().casefold()):
        cleaned = word.strip(".:")
        if cleaned and cleaned not in _HEADER_WORDS and cleaned not in words:
            words.append(cleaned)
    return words


def _find_header(lines: Sequence[str]) -> tuple[int, list[str]]:
    """Найти строку-шапку и вернуть её номер в списке и порядок её ролей.

    Кандидат в шапку — строка без цифр, в которой встречаются слова ролей
    «название» и «значение». Цифры исключают кандидата: строка результата
    со словами, похожими на шапку (`Показатель: Глюкоза Результат: 5.2 ...`),
    шапкой быть не может, и её значение не должно пропасть под видом шапки.

    Если у найденного кандидата нет всех четырёх ролей, разбирать дальше
    нельзя: колонка, роль которой не опознана, встанет не на своё место
    (например, единицы — в референс), а это опаснее отказа.
    """
    for index, line in enumerate(lines):
        if _HAS_DIGIT.search(line):
            continue
        roles = _header_word_roles(line)
        if ROLE_NAME not in roles or ROLE_VALUE not in roles:
            continue
        missing = [role for role in _ROLES_REQUIRED if role not in roles]
        if missing:
            unrecognised = _unrecognised_header_words(line)
            raise LabTableError(
                f"строка-шапка {line.strip()!r} не называет колонки: "
                f"{', '.join(missing)}; нераспознанные слова: "
                f"{', '.join(unrecognised) if unrecognised else 'нет'} — "
                "разбирать дальше нельзя, колонка встанет не на своё место"
            )
        return index, roles
    raise LabTableError(
        "в выгрузке не найдена шапка таблицы: неизвестно, где значение, "
        "а где единицы"
    )


def _strip_lab_code(line: str) -> str:
    return _SPACES.sub(" ", _LAB_CODE.sub("", line)).strip()


def _split_row(line: str, roles: Sequence[str]) -> LabRow | None:
    """Разобрать строку результата или вернуть None, если не читается."""
    tokens = _SPACES.split(line.strip())
    first = next(
        (i for i, token in enumerate(tokens) if _NUMBER.match(token)), None
    )
    if first is None or first == 0:
        return None

    name = " ".join(tokens[:first])
    rest = tokens[first:]
    fields: dict[str, str] = {ROLE_NAME: name}

    # Последняя колонка забирает весь остаток: референс бывает из трёх
    # слов («0 - 5»), а единицы — всегда из одного. Если остаток из
    # нескольких слов достаётся единицам, граница колонок разобрана не
    # там — строка идёт в unparsed, а не в запись с обрубленным референсом.
    tail_roles = [role for role in roles if role != ROLE_NAME]
    for index, role in enumerate(tail_roles):
        if not rest:
            return None
        if index == len(tail_roles) - 1:
            if role == ROLE_UNITS and len(rest) > 1:
                return None
            fields[role] = " ".join(rest)
            rest = []
        else:
            fields[role] = rest.pop(0)

    if not _NUMBER.match(fields.get(ROLE_VALUE, "")):
        return None
    return LabRow(
        name=fields[ROLE_NAME],
        value_text=fields[ROLE_VALUE],
        units=fields.get(ROLE_UNITS, ""),
        reference_text=fields.get(ROLE_REFERENCE, ""),
        line=line,
    )


def parse_lab_lines(lines: Sequence[str]) -> LabTable:
    """Разобрать строки выгрузки в записи бланка."""
    header_index, roles = _find_header(lines)

    rows: list[LabRow] = []
    unparsed: list[str] = []
    pending_name = ""

    for index, line in enumerate(lines):
        if index == header_index:
            continue
        stripped = line.strip()
        if not stripped or _SERVICE.match(stripped):
            continue

        if pending_name and _STARTS_WITH_NUMBER.match(stripped):
            candidate = f"{pending_name} {stripped}"
            pending_name = ""
        else:
            candidate = stripped

        cleaned = _strip_lab_code(candidate)
        if "(" in cleaned and cleaned.count("(") != cleaned.count(")"):
            unparsed.append(line)
            pending_name = ""
            continue

        row = _split_row(cleaned, roles)
        if row is not None:
            rows.append(row)
            pending_name = ""
        elif _HAS_DIGIT.search(cleaned):
            # В строке есть число, а записи не вышло: это может быть
            # результат, который разбор не осилил. Молча выбросить его
            # нельзя — он доходит до коуча текстом.
            unparsed.append(line)
            pending_name = ""
        elif cleaned:
            # Числа нет вовсе, значит это не результат: либо перенесённое
            # название, либо проза бланка. Ждём следующую строку.
            pending_name = cleaned

    return LabTable(rows=tuple(rows), unparsed=tuple(unparsed))
