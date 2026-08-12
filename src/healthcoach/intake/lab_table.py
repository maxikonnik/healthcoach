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

_FUZZY_SHORT_WORD = 5
_FUZZY_DISTANCE_SHORT = 1
_FUZZY_DISTANCE_LONG = 2
"""Насколько слово шапки может отличаться от известного, чтобы всё же
считаться им. Мера — расстояние редактирования (Левенштейна), порог зависит
от длины известного слова: 1 для слов до пяти букв включительно, 2 для более
длинных.

Почему по длине. Опечатка распознавания — это одна-две перепутанные буквы
в слове, которое в остальном цело: «Ел.» вместо «Ед.», «Референскыю» вместо
«Референсные». Доля искажения, а не число букв, решает, то же это слово или
другое: две буквы из одиннадцати — та же «Референсные», а две буквы из двух
(«En.» вместо «Ед.») — слово, не разделившее с известным ни одной буквы.
Разрешить расстояние 2 коротким словам значит начать выдумывать роли на
пустом месте; запретить его длинным — потерять именно те шапки, ради
которых правило и написано, потому что на длинном слове распознавание
ошибается чаще одного раза.

Само по себе неточное совпадение колонки не раскладывает: документ,
которому оно понадобилось, помечается `LabTable.needs_confirmation` и не
создаёт измерений, пока коуч не подтвердит догадку (решение 2 плана)."""

_WORD_AMBIGUOUS_VALUES = "значения"
"""«Значения» — слово с двумя ролями: в «Референсные значения» это
референс, а само по себе («Показатель Значения Ед. изм.») — колонка
результата, отличающаяся от «Значение» одной буквой. Роль выбирается по
тому, что уже встречено левее в той же шапке (см. `_header_columns`);
в словаре слово стоит референсом — ролью, которая у него чаще."""

_NUMBER = re.compile(r"^[<>]?\d+(?:[.,]\d+)?$")
_STARTS_WITH_NUMBER = re.compile(r"^\s*[<>]?\d")
_HAS_DIGIT = re.compile(r"\d")
_SERVICE_LABEL = re.compile(
    r"^\s*(?:Страница|№\s*заказа)\b[\s:.№-]*\d", re.IGNORECASE
)
"""Метки с данными: за меткой стоит число — номер страницы или заказа.

Служебной строку делает именно число сразу за меткой, а не сама метка:
показателя, который зовётся «Страница» и дальше несёт номер, не бывает,
зато строка результата, начинающаяся на те же буквы («Страница белка …»),
бывает — и она обязана дойти до коуча. Что напечатано после номера («из 3»,
дата печати, фамилия пациента), роли не играет: строка целиком принадлежит
форме."""

_SERVICE_PHRASE = re.compile(
    r"^\s*(?:"
    r"Дата исследования|Дата рождения|ПЕЧАТЬ:|Штрихкод|Материал|Вн\.№"
    r"|Адрес пациента|Адрес ООО|Адрес вн\.тер\.г\.|Адрес:"
    r"|I{1,3}\s*триместр"
    r")(?![А-Яа-яЁёA-Za-z])",
    re.IGNORECASE,
)
"""Полные служебные фразы: метка целиком, от начала строки.

Не первое слово, а вся фраза: «Адрес» отдельным словом отсеивал бы и
«Адрес белок …», а «Материал» без границы слова съедал ещё и «Материалы
исследования …» — настоящий результат исчезал из списка коуча без следа
даже в unparsed. Каждая фраза встречена в отчёте табло корпуса образцов
(Task 3 плана), а не придумана заранее; отсюда четыре формы «Адреса» —
ровно те, что печатают лаборатории корпуса. Запрет буквы следом — та же
защита с другого конца: «Материалы» перестают быть «Материалом».

Регистр не различается: «СТРАНИЦА 1 ИЗ 3» — обыкновенный колонтитул, и
без этого дефект, ради которого писался отсев, выживал в капсе. Двоеточие
после заголовка триместра тоже не обязательно: «II триместр» без него
становился `pending_name` и приклеивался к следующей строке с числом."""
_SPACES = re.compile(r"\s+")
_HEADER_WORD_SPLIT = re.compile(r"[\s.]+")
"""Точка режет слово шапки так же, как пробел: «Ед.изм.» и «Ед. изм.» —
одно и то же, случайно склеенное или разбитое при извлечении текста из
PDF/OCR. Цифр в кандидате в шапку не бывает (см. `_find_header`), поэтому
резать по точке здесь безопасно — это не десятичная дробь."""
_RANGE_DASH = re.compile(r"^[-–—]$")
_COMPARISON_SIGN = re.compile(r"^[<>≤≥]$")

_MESSAGE_NOT_A_TABLE = (
    "это не похоже на таблицу лабораторных анализов. Инструмент принимает "
    "выгрузки лабораторий с таблицей показателей: название, значение, "
    "единицы. Заключения, протоколы и рекомендации сюда не загружаются — "
    "для них здесь пока нет места."
)
"""Показывается коучу, а не разработчику: не «шапка не найдена», а что
случилось с её документом и что дальше не пытаться загружать сюда. Пятнадцать
файлов корпуса — УЗИ, гастроскопия, биоимпеданс, рекомендации эндокринолога —
это не выгрузки анализов, и отказ от них правилен; неправильным было только
сообщение (см. Task 4 плана)."""

_MESSAGE_EMPTY_DOCUMENT = (
    "в документе не нашлось текста — похоже на пустой PDF или нечитаемое "
    "фото. Экспортируйте PDF из лаборатории заново или переснимите бланк "
    "и загрузите ещё раз."
)
"""Отдельное сообщение от `_MESSAGE_NOT_A_TABLE`: лечится не так же —
переснять/переэкспортировать, а не проверять, что это за документ."""


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

    header_line: str = ""
    """Строка-шапка так, как её прочитало распознавание, — без правок.
    Коуч подтверждает догадку, глядя на то же, что видел разбор."""

    columns: tuple[tuple[str, str], ...] = ()
    """Как разбор понял колонки: слово шапки → роль, по порядку."""

    needs_confirmation: bool = False
    """True — хотя бы одна колонка опознана неточно (по расстоянию
    редактирования, см. `_FUZZY_DISTANCE_SHORT`). Такая таблица разобрана,
    но разобрана по догадке: измерения из неё не создаются, пока коуч не
    посмотрит на догадку и не согласится (решение 2 плана). Точно опознанная
    шапка оставляет здесь False, и её путь не меняется вовсе."""


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


def _edit_distance(first: str, second: str) -> int:
    """Расстояние Левенштейна: сколько правок отделяет одно слово от другого.

    Своя реализация в пять строк, а не зависимость: слова шапки короткие,
    а словарь — полтора десятка записей, так что цена вычисления здесь
    ничего не значит, зато новых зависимостей у проекта не появляется.
    """
    previous = list(range(len(second) + 1))
    for i, left in enumerate(first, start=1):
        current = [i]
        for j, right in enumerate(second, start=1):
            current.append(
                min(
                    previous[j] + 1,
                    current[j - 1] + 1,
                    previous[j - 1] + (left != right),
                )
            )
        previous = current
    return previous[-1]


def _fuzzy_role(word: str) -> str | None:
    """Роль слова, которого нет в словаре точно, — или None.

    Ближайшее известное слово в пределах порога (`_FUZZY_DISTANCE_SHORT` /
    `_FUZZY_DISTANCE_LONG`) отдаёт свою роль. Если ближайшими оказались
    слова двух разных ролей на одном и том же расстоянии — совпадения нет:
    «Значени» одинаково близко к «значение» (результат) и «значения»
    (референс), и выбрать между ними можно только жребием. Инструмент не
    бросает жребий: неоднозначность — отказ, как и везде.
    """
    closest: dict[str, int] = {}
    for known, role in _HEADER_WORDS.items():
        limit = (
            _FUZZY_DISTANCE_SHORT
            if len(known) <= _FUZZY_SHORT_WORD
            else _FUZZY_DISTANCE_LONG
        )
        distance = _edit_distance(word, known)
        if distance > limit:
            continue
        if distance < closest.get(role, limit + 1):
            closest[role] = distance
    if not closest:
        return None
    best = min(closest.values())
    roles = [role for role, distance in closest.items() if distance == best]
    if len(roles) != 1:
        return None
    return roles[0]


def _header_role(word: str) -> tuple[str | None, bool]:
    """Роль слова шапки и точность совпадения (точное / по расстоянию)."""
    role = _HEADER_WORDS.get(word)
    if role is not None:
        return role, True
    return _fuzzy_role(word), False


@dataclass(frozen=True)
class _HeaderColumn:
    word: str
    role: str
    exact: bool
    """False — слово опознано неточно, по расстоянию редактирования. Такая
    колонка — догадка, и вся таблица уходит на подтверждение коучу."""


def _header_columns(line: str) -> list[_HeaderColumn]:
    """Колонки строки-шапки: слово и его роль, по порядку появления.

    Роль, встреченная второй раз, новой колонки не даёт: «Референсные
    значения» — два слова одной колонки, а не две колонки.

    «Значения» само по себе — колонка результата: пока ни результата, ни
    референса в шапке не встречено, читать его референсом значит остаться
    без обязательной колонки значения и убить документ отказом «шапка не
    найдена», который причины не называет.
    """
    columns: list[_HeaderColumn] = []
    seen: set[str] = set()
    for word in _header_words(line):
        role, exact = _header_role(word)
        if role is None:
            continue
        if word == _WORD_AMBIGUOUS_VALUES and not seen & {ROLE_VALUE, ROLE_REFERENCE}:
            role = ROLE_VALUE
        if role in seen:
            continue
        seen.add(role)
        columns.append(_HeaderColumn(word=word, role=role, exact=exact))
    return columns


def _unrecognised_header_words(line: str) -> list[str]:
    """Слова строки-шапки, не сопоставленные ни одной роли — ни точно, ни
    по расстоянию редактирования."""
    words: list[str] = []
    for word in _header_words(line):
        role, _ = _header_role(word)
        if role is None and word not in words:
            words.append(word)
    return words


def _find_header(lines: Sequence[str]) -> tuple[int, list[_HeaderColumn]]:
    """Найти строку-шапку и вернуть её номер в списке и её колонки по порядку.

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

    Опознанности мало: колонка обязана быть ещё и безопасной по месту.
    В ячейке «прочего» стоит свободный текст («в норме», «выше нормы
    в 2 раза»), а непоследняя колонка забирает ровно один токен — значит
    остальные слова комментария сдвинут все следующие колонки, и единицы
    придут из середины фразы. Разобрать свободный текст однозначно можно
    только последней колонкой; в любом другом месте шапки — отказ.

    Кандидат в шапку не нашёлся вовсе — два разных случая с разным
    лечением, и коуч должен различать их по сообщению, а не по попытке
    угадать. В документе есть строки, но ни одна не подошла под кандидата —
    это заключение УЗИ, протокол или другой не-табличный документ:
    сообщение так и говорит, что это не таблица анализов (`_MESSAGE_NOT_A_TABLE`).
    Строк нет вовсе (пустой PDF, нечитаемое фото) — лечится переснятием, а не
    перечитыванием того же файла, и сообщение об этом отдельное
    (`_MESSAGE_EMPTY_DOCUMENT`).
    """
    for index, line in enumerate(lines):
        if _HAS_DIGIT.search(line):
            continue
        columns = _header_columns(line)
        exact_roles = [column.role for column in columns if column.exact]
        if any(role not in exact_roles for role in _ROLES_MANDATORY):
            continue
        unrecognised = _unrecognised_header_words(line)
        if unrecognised:
            raise LabTableError(
                f"строка-шапка {line.strip()!r} не называет колонки: "
                f"нераспознанные слова: {', '.join(unrecognised)} — "
                "разбирать дальше нельзя, колонка встанет не на своё место"
            )
        for position, column in enumerate(columns):
            if column.role == ROLE_OTHER and position != len(columns) - 1:
                raise LabTableError(
                    f"строка-шапка {line.strip()!r}: колонка {column.word!r} — "
                    "свободный текст, а стоит не последней — разбирать "
                    "дальше нельзя, её слова сдвинут остальные колонки"
                )
        return index, columns
    if any(line.strip() for line in lines):
        raise LabTableError(_MESSAGE_NOT_A_TABLE)
    raise LabTableError(_MESSAGE_EMPTY_DOCUMENT)


def _is_service_line(line: str) -> bool:
    """Служебная разметка бланка, а не результат анализа.

    Два класса, и ни один не судит по одному лишь первому слову: строка,
    которая могла бы быть измерением, не имеет права исчезнуть без следа —
    ни записью, ни строкой в unparsed. Всё, что не подошло ни под один
    класс, идёт обычным путём разбора.
    """
    return bool(_SERVICE_PHRASE.match(line) or _SERVICE_LABEL.match(line))


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

    if first >= 2 and _COMPARISON_SIGN.match(tokens[first - 1]):
        # «Белок < 0.140 г/л»: знак отделён от числа пробелом, но
        # принадлежит значению, а не названию. Иначе бланк говорит
        # «меньше 0.140», а в анализ встаёт ровно 0.140 — число, которого
        # в бланке не было. Склеенный «<0.140» числом не считается
        # (см. `parse_number`) и доходит до коуча текстом, как и должен.
        tokens = [
            *tokens[: first - 1],
            f"{tokens[first - 1]}{tokens[first]}",
            *tokens[first + 1 :],
        ]
        first -= 1

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
            # Токены кончились раньше колонок. Пустая ячейка «прочего» —
            # обычное дело: комментарий пишут не к каждой строке, а
            # «Предыдущий» у первого в жизни анализа пуст всегда; терять
            # из-за этого сегодняшний результат нельзя, тем более что
            # содержимое «прочего» в запись бланка не идёт вовсе. Пустота
            # на колонке, которая в запись идёт, — другое дело: это
            # признак того, что граница колонок разобрана не там
            # («Пациентка беременна 12 недель»), и строка идёт в unparsed.
            if role != ROLE_OTHER:
                return None
            fields[role] = ""
            continue
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
    header_index, columns = _find_header(lines)
    roles = [column.role for column in columns]

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
        if not stripped or _is_service_line(stripped):
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

    return LabTable(
        rows=tuple(rows),
        unparsed=tuple(unparsed),
        header_line=lines[header_index].strip(),
        columns=tuple((column.word, column.role) for column in columns),
        needs_confirmation=any(not column.exact for column in columns),
    )
