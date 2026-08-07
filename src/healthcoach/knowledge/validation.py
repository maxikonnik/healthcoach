"""Проверка спецификации опросника на внутренние противоречия."""

from __future__ import annotations

import re
from dataclasses import dataclass

from healthcoach.knowledge.questionnaire import Questionnaire, Subscale, Threshold

_RANGE = re.compile(r"^\s*(\d+)\s*-\s*(\d+)\s*$")
_GREATER = re.compile(r"^\s*>\s*(\d+)\s*$")
_LESS = re.compile(r"^\s*<\s*(\d+)\s*$")

_DEGREE_ORDER = ("низкая", "средняя", "умеренная", "высокая", "тяжёлая", "очень тяжёлая")


class RangeParseError(Exception):
    """Диапазон порога записан в неизвестном формате."""


@dataclass(frozen=True)
class Problem:
    where: str
    message: str


def parse_threshold_range(text: str) -> tuple[int | None, int | None]:
    """Разобрать запись диапазона из ключа опросника.

    Баллы целые, поэтому строгие неравенства сводятся к включающим границам:
    ">14" — это 15 и выше, "<40" — это 39 и ниже.
    """
    if (m := _RANGE.match(text)) is not None:
        return int(m.group(1)), int(m.group(2))
    if (m := _GREATER.match(text)) is not None:
        return int(m.group(1)) + 1, None
    if (m := _LESS.match(text)) is not None:
        return None, int(m.group(1)) - 1
    raise RangeParseError(f"не удалось разобрать диапазон {text!r}")


def _sort_key(threshold: Threshold) -> tuple[int, int]:
    order = (
        _DEGREE_ORDER.index(threshold.degree)
        if threshold.degree in _DEGREE_ORDER
        else len(_DEGREE_ORDER)
    )
    lower = threshold.min if threshold.min is not None else -10**9
    return order, lower


def _check_group(where: str, thresholds: list[Threshold]) -> list[Problem]:
    problems: list[Problem] = []
    ordered = sorted(thresholds, key=_sort_key)

    for earlier, later in zip(ordered, ordered[1:]):
        earlier_top = earlier.max
        later_bottom = later.min
        if earlier_top is None:
            problems.append(
                Problem(
                    where,
                    f"степень {earlier.degree!r} не имеет верхней границы, "
                    f"но после неё идёт {later.degree!r}",
                )
            )
            continue
        if later_bottom is None:
            continue
        if later_bottom <= earlier_top:
            problems.append(
                Problem(
                    where,
                    f"диапазоны {earlier.degree!r} и {later.degree!r} пересекаются: "
                    f"{earlier_top} и {later_bottom}",
                )
            )
        elif later_bottom > earlier_top + 1:
            problems.append(
                Problem(
                    where,
                    f"разрыв между {earlier.degree!r} и {later.degree!r}: "
                    f"баллы {earlier_top + 1}..{later_bottom - 1} никуда не попадают",
                )
            )

    if ordered and ordered[-1].max is not None:
        last = ordered[-1]
        problems.append(
            Problem(
                where,
                f"у высшей степени {last.degree!r} задана верхняя граница {last.max} — "
                f"баллы выше неё не получат никакой степени; вероятно, в источнике "
                f"должно быть '>{last.max}'",
            )
        )

    return problems


def _check_subscale(block_id: str, subscale: Subscale) -> list[Problem]:
    if not subscale.thresholds:
        return []
    where = f"{block_id}/{subscale.id}"

    by_sex: dict[str | None, list[Threshold]] = {}
    for threshold in subscale.thresholds:
        by_sex.setdefault(threshold.sex, []).append(threshold)

    problems: list[Problem] = []
    for sex, group in sorted(by_sex.items(), key=lambda kv: kv[0] or ""):
        label = where if sex is None else f"{where} (пол: {sex})"
        problems.extend(_check_group(label, group))
    return problems


def validate_questionnaire(questionnaire: Questionnaire) -> list[Problem]:
    """Найти пересечения, разрывы и незакрытые верхние пороги."""
    problems: list[Problem] = []
    for block in questionnaire.blocks:
        for subscale in block.subscales:
            problems.extend(_check_subscale(block.id, subscale))
    return problems
