"""Разбор строк выгрузки лаборатории в записи бланка.

Роли колонок берутся из строки-шапки, а не из позиции: у одной
лаборатории единицы стоят до референса, у другой — после. Строка,
которая однозначно не читается, не разбирается по частям, а доходит
до коуча целиком: догадка здесь стоила бы неверного числа в анализе.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass

ROLE_NAME = "название"
ROLE_VALUE = "значение"
ROLE_UNITS = "единицы"
ROLE_REFERENCE = "референс"

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
    неизвестно, и подстановка 0.60 исказила бы динамику.
    """
    cleaned = text.strip().replace(",", ".")
    try:
        return float(cleaned)
    except ValueError:
        return None


def _header_roles(line: str) -> list[str] | None:
    """Порядок ролей колонок, если строка похожа на шапку."""
    roles: list[str] = []
    for word in _SPACES.split(line.strip().casefold()):
        role = _HEADER_WORDS.get(word.strip(".:"))
        if role is not None and role not in roles:
            roles.append(role)
    if ROLE_NAME in roles and ROLE_VALUE in roles:
        return roles
    return None


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

    # Референс бывает из трёх слов («0 - 5»), единицы — всегда из одного.
    # Последняя колонка забирает весь остаток: референс бывает из трёх
    # слов («0 - 5»), а единицы — всегда из одного.
    tail_roles = [role for role in roles if role != ROLE_NAME]
    for index, role in enumerate(tail_roles):
        if not rest:
            return None
        if index == len(tail_roles) - 1:
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
    roles: list[str] | None = None
    for line in lines:
        roles = _header_roles(line)
        if roles is not None:
            break
    if roles is None:
        raise LabTableError(
            "в выгрузке не найдена шапка таблицы: неизвестно, где значение, "
            "а где единицы"
        )

    rows: list[LabRow] = []
    unparsed: list[str] = []
    pending_name = ""

    for line in lines:
        stripped = line.strip()
        if not stripped or _header_roles(line) is not None or _SERVICE.match(stripped):
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
