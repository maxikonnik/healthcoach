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
