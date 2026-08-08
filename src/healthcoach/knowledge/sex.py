"""Словарь пола.

Строка «м»/«ж» — контракт между спецификацией опросника, референсами
и скорингом. Раньше он нигде не проверялся, и «М» с заглавной буквы
молча не совпадал ни с одним порогом.
"""

from __future__ import annotations

SEX_MALE = "м"
SEX_FEMALE = "ж"
SEXES = frozenset({SEX_MALE, SEX_FEMALE})


class SexError(ValueError):
    """Пол задан значением вне словаря."""


def normalize_sex(sex: str) -> str:
    """Привести пол к каноническому виду или поднять ошибку."""
    value = sex.strip().casefold()
    if value not in SEXES:
        raise SexError(f"пол должен быть 'м' или 'ж', получено {sex!r}")
    return value
