"""Единицы измерения показателей.

Два механизма, оба объявляет коуч. Синонимы — разные написания одной и той
же единицы (нг/мл, мкг/л, ng/mL), арифметики нет вовсе. Пересчёт — множитель,
выписанный коучем для конкретного показателя. Всё остальное — ошибка:
таблица пересчётов «на все случаи» была бы источником тихих ошибок, потому
что перевод между массовыми и молярными единицами зависит от молярной массы.
"""

from __future__ import annotations

import re

from healthcoach.knowledge.references import Analyte

_SPACES = re.compile(r"\s+")


class UnitError(Exception):
    """Единицы измерения не сопоставлены с единицами референса."""


def normalize_units(units: str) -> str:
    """Привести запись единиц к виду, в котором они сравниваются."""
    return _SPACES.sub("", units).strip().casefold()


def convert_to_reference(analyte: Analyte, value: float, units: str) -> float:
    """Перевести значение в единицы референса показателя."""
    given = normalize_units(units)

    if given == normalize_units(analyte.units):
        return value

    for alias in analyte.unit_aliases:
        if given == normalize_units(alias):
            return value

    for conversion in analyte.conversions:
        if given == normalize_units(conversion.from_units):
            return value * conversion.factor

    known = [analyte.units, *analyte.unit_aliases, *(c.from_units for c in analyte.conversions)]
    raise UnitError(
        f"показатель {analyte.id!r}: единицы {units!r} не сопоставлены; "
        f"референс задан в {analyte.units!r}, известны также {known[1:]!r}"
    )


def units_match(analyte: Analyte, units: str) -> bool:
    """Сопоставлены ли единицы измерения с единицами показателя — без арифметики.

    Не то же самое, что «`convert_to_reference` не бросает исключение»: это
    была первая версия этого предиката, и она была неверна. `convert_to_reference`
    принимает и объявленный пересчёт (`analyte.conversions`) — единицы, для
    которых нужен множитель — а три вызывающих места сравнивают
    `measurement.value` с коридором как есть, не умножая ни на что. Единица,
    для которой convert_to_reference вернул бы `value * factor`, здесь обязана
    остаться несопоставленной: иначе, скажем, 10.0 мг/дл кальция читались бы
    как 10.0 против коридора, заданного в ммоль/л (нужно ×0.2495 → 2.495) —
    молча неверный вердикт, а не отказ.

    Пересчёт в проекте должен случаться там, где есть настоящее число для
    умножения — на импорте (`intake/measurements.py`) и при ручном вводе
    (`routes_snapshots.add_measurement`) — и результат сохраняется уже в
    единицах референса. К тому моменту, когда измерение доходит до сверки,
    его единицы обязаны быть уже каноническими; эта функция — не место
    досчитывать то, что не досчиталось раньше, а страховочная сеть, и сеть
    обязана быть строгой. Единицы совпадают, только если они совпадают с
    единицами референса или с объявленным синонимом (`unit_aliases`) —
    буквально то же сравнение, что `convert_to_reference` делает до цикла по
    `conversions`, и не после."""
    given = normalize_units(units)
    if given == normalize_units(analyte.units):
        return True
    return any(given == normalize_units(alias) for alias in analyte.unit_aliases)
