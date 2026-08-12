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

from healthcoach.intake.resolve import LAB_CODE

ROLE_NAME = "название"
ROLE_VALUE = "значение"
ROLE_UNITS = "единицы"
ROLE_REFERENCE = "референс"
ROLE_OTHER = "прочее"
"""Колонка опознана, но её содержимое коучу не нужно (комментарий лаборатории,
предыдущее значение, динамика). Опознана — значит не пуста строкой отказа;
не нужна — значит в `LabRow` не попадает."""

_ROLES_MANDATORY = (ROLE_NAME, ROLE_VALUE)
"""Без имени и значения строка не запись бланка вовсе. Единицы и референс —
не обязательны: бланк без колонки единиц — обычное дело (единицы часто
стоят в самом названии, «Гемоглобин, г/л»), и его отсутствие не повод для
отказа. Опасность не в отсутствующей колонке, а в неопознанной — см.
`_find_header`."""

_HEADER_WORDS = {
    "исследование": ROLE_NAME,
    "показатель": ROLE_NAME,
    "параметр": ROLE_NAME,
    "значение": ROLE_VALUE,
    "результат": ROLE_VALUE,
    "ед": ROLE_UNITS,
    "единицы": ROLE_UNITS,
    "изм": ROLE_UNITS,
    "нормальные": ROLE_REFERENCE,
    "референсные": ROLE_REFERENCE,
    "реф": ROLE_REFERENCE,
    "пределы": ROLE_REFERENCE,
    "значения": ROLE_REFERENCE,
    "комментарий": ROLE_OTHER,
    "предыдущий": ROLE_OTHER,
    "динамика": ROLE_OTHER,
}

_NUMBER = re.compile(r"^[<>]?\d+(?:[.,]\d+)?$")
_STARTS_WITH_NUMBER = re.compile(r"^\s*[<>]?\d")
_HAS_DIGIT = re.compile(r"\d")
_SERVICE = re.compile(r"^\s*(Дата исследования|Штрихкод|Материал|Вн\.№)")
_SPACES = re.compile(r"\s+")
_HEADER_WORD_SPLIT = re.compile(r"[\s.]+")
"""Точка режет слово шапки так же, как пробел: «Ед.изм.» и «Ед. изм.» —
одно и то же, случайно склеенное или разбитое при извлечении текста из
PDF/OCR. Цифр в кандидате в шапку не бывает (см. `_find_header`), поэтому
резать по точке здесь безопасно — это не десятичная дробь."""
_RANGE_DASH = re.compile(r"^[-–—]$")
_COMPARISON_SIGN = re.compile(r"^[<>≤≥]$")


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


def _header_words(line: str) -> list[str]:
    """Слова строки-шапки, очищенные от пунктуации, без пустых."""
    words = [
        word.strip(":") for word in _HEADER_WORD_SPLIT.split(line.strip().casefold())
    ]
    return [word for word in words if word]


def _header_word_roles(line: str) -> list[str]:
    """Роли, узнанные среди слов строки, по порядку появления."""
    roles: list[str] = []
    for word in _header_words(line):
        role = _HEADER_WORDS.get(word)
        if role is not None and role not in roles:
            roles.append(role)
    return roles


def _unrecognised_header_words(line: str) -> list[str]:
    """Слова строки-шапки, не сопоставленные ни одной роли."""
    words: list[str] = []
    for word in _header_words(line):
        if word not in _HEADER_WORDS and word not in words:
            words.append(word)
    return words


def _find_header(lines: Sequence[str]) -> tuple[int, list[str]]:
    """Найти строку-шапку и вернуть её номер в списке и порядок её ролей.

    Кандидат в шапку — строка без цифр, в которой встречаются слова ролей
    «название» и «значение». Цифры исключают кандидата: строка результата
    со словами, похожими на шапку (`Показатель: Глюкоза Результат: 5.2 ...`),
    шапкой быть не может, и её значение не должно пропасть под видом шапки.

    Отказ наступает не когда колонки не хватает, а когда колонку не
    удалось опознать. Бланк без колонки единиц или референса — обычное
    дело (единицы часто стоят в самом названии, «Гемоглобин, г/л») и не
    повод отказывать. Опасность в другом: колонка, чьё слово шапки не
    входит в словарь, встанет не на своё место (например, единицы — в
    референс), а это опаснее отказа. Поэтому обязательны только «название»
    и «значение»; каждое остальное слово шапки обязано быть опознано хоть
    какой-то ролью, включая «прочее» — известную, но не нужную колонку
    вроде «Комментарий» или «Предыдущий».
    """
    for index, line in enumerate(lines):
        if _HAS_DIGIT.search(line):
            continue
        roles = _header_word_roles(line)
        if any(role not in roles for role in _ROLES_MANDATORY):
            continue
        unrecognised = _unrecognised_header_words(line)
        if unrecognised:
            raise LabTableError(
                f"строка-шапка {line.strip()!r} не называет колонки: "
                f"нераспознанные слова: {', '.join(unrecognised)} — "
                "разбирать дальше нельзя, колонка встанет не на своё место"
            )
        return index, roles
    raise LabTableError(
        "в выгрузке не найдена шапка таблицы: неизвестно, где значение, "
        "а где единицы"
    )


def _strip_lab_code(line: str) -> str:
    """Стереть код номенклатуры услуги — тем же правилом, что и resolve.py.

    Общий объект `LAB_CODE`, а не вторая копия регулярки: копия однажды уже
    разошлась с оригиналом и съедала квалифицирующую скобку («ионизированный»),
    из-за чего ионизированный кальций читался как общий.
    """
    return _SPACES.sub(" ", LAB_CODE.sub("", line)).strip()


def _consume_reference(rest: list[str]) -> tuple[str, list[str]]:
    """Взять из остатка явный диапазон референса, если он там есть.

    На фото референс иногда печатается с пробелами вокруг тире
    («3,89 - 9,23») или с отдельным знаком сравнения («< 5») — тогда он
    занимает не один токен, а два-три. Диапазон опознаётся однозначно —
    по тире между двумя числами или по знаку сравнения перед числом, а
    не по счёту слов вслепую. Если ни одна из форм не подошла, референс,
    как и любая другая непоследняя колонка, забирает один токен.
    """
    if (
        len(rest) >= 3
        and _NUMBER.match(rest[0])
        and _RANGE_DASH.match(rest[1])
        and _NUMBER.match(rest[2])
    ):
        return " ".join(rest[:3]), rest[3:]
    if len(rest) >= 2 and _COMPARISON_SIGN.match(rest[0]) and _NUMBER.match(rest[1]):
        return " ".join(rest[:2]), rest[2:]
    return rest[0], rest[1:]


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
        elif role == ROLE_REFERENCE:
            fields[role], rest = _consume_reference(rest)
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
    pending_line = ""
    """Исходный текст строки, из которой взято `pending_name` — на случай,
    если следующая строка со значением всё равно не разберётся: имя не
    должно пропасть из того, что видит коуч, только потому что оно жило
    отдельной строкой."""

    for index, line in enumerate(lines):
        if index == header_index:
            continue
        stripped = line.strip()
        if not stripped or _SERVICE.match(stripped):
            continue

        if pending_name and _STARTS_WITH_NUMBER.match(stripped):
            candidate = f"{pending_name} {stripped}"
            display = f"{pending_line} {line}"
            pending_name = ""
            pending_line = ""
        else:
            candidate = stripped
            display = line

        cleaned = _strip_lab_code(candidate)
        if "(" in cleaned and cleaned.count("(") != cleaned.count(")"):
            unparsed.append(display)
            pending_name = ""
            pending_line = ""
            continue

        row = _split_row(cleaned, roles)
        if row is not None:
            rows.append(row)
            pending_name = ""
            pending_line = ""
        elif _HAS_DIGIT.search(cleaned):
            # В строке есть число, а записи не вышло: это может быть
            # результат, который разбор не осилил. Молча выбросить его
            # нельзя — он доходит до коуча текстом. Перенесённое с
            # предыдущей строки имя уходит вместе с ней: иначе коуч увидел
            # бы голое число без названия показателя.
            unparsed.append(display)
            pending_name = ""
            pending_line = ""
        elif cleaned:
            # Числа нет вовсе, значит это не результат: либо перенесённое
            # название, либо проза бланка. Ждём следующую строку.
            pending_name = cleaned
            pending_line = line

    return LabTable(rows=tuple(rows), unparsed=tuple(unparsed))
