"""Сверка измерений с целевыми коридорами коуча."""

from __future__ import annotations

from dataclasses import dataclass

from healthcoach.knowledge.references import Analyte, Interval, References, Target
from healthcoach.knowledge.sex import normalize_sex

STATUS_DEFICIT = "дефицит"
STATUS_BELOW = "ниже целевого"
STATUS_WITHIN = "в целевом"
STATUS_ABOVE = "выше целевого"
STATUS_EXCESS = "избыток"
STATUS_NO_RULE = "правило не задано"
STATUS_UNIT_MISMATCH = "единицы не сопоставлены"
STATUS_NOT_COMPUTED = "не удалось вычислить"


@dataclass(frozen=True)
class Subject:
    sex: str
    age: int
    cycle_phase: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "sex", normalize_sex(self.sex))


@dataclass(frozen=True)
class Measurement:
    analyte_id: str
    value: float
    units: str
    label: str = ""
    """Как показатель назван в бланке. Нужен нераспознанным: их
    analyte_id пуст, и без подписи находка была бы безымянной."""


@dataclass(frozen=True)
class AnalyteVerdict:
    analyte_id: str
    title: str
    value: float | None
    units: str
    status: str
    target: Interval | None
    lab_range: Interval | None
    note: str | None
    rule_missing: bool


def select_target(analyte: Analyte, subject: Subject) -> Target | None:
    """Первое целевое значение, чьё условие подошло. Порядок задаёт приоритет."""
    for target in analyte.targets:
        if target.condition.matches(subject.sex, subject.age, subject.cycle_phase):
            return target
    return None


def _status(target: Target, value: float) -> str:
    if target.deficient is not None and target.deficient.contains(value):
        return STATUS_DEFICIT
    if target.excessive is not None and target.excessive.contains(value):
        return STATUS_EXCESS
    if target.optimal.contains(value):
        return STATUS_WITHIN
    if target.optimal.low is not None and value < target.optimal.low:
        return STATUS_BELOW
    return STATUS_ABOVE


def _unresolved(measurement: Measurement, status: str) -> AnalyteVerdict:
    return AnalyteVerdict(
        analyte_id=measurement.analyte_id,
        title=measurement.label or measurement.analyte_id,
        value=measurement.value,
        units=measurement.units,
        status=status,
        target=None,
        lab_range=None,
        note=None,
        rule_missing=True,
    )


def check_measurements(
    references: References, measurements: list[Measurement], subject: Subject
) -> list[AnalyteVerdict]:
    """Сверить измерения с референсами. Ничего не отбрасывать молча."""
    verdicts: list[AnalyteVerdict] = []

    for measurement in measurements:
        analyte = references.resolve(measurement.analyte_id)
        if analyte is None:
            verdicts.append(_unresolved(measurement, STATUS_NO_RULE))
            continue

        if measurement.units.strip().casefold() != analyte.units.strip().casefold():
            verdicts.append(
                AnalyteVerdict(
                    analyte_id=analyte.id,
                    title=analyte.name,
                    value=measurement.value,
                    units=measurement.units,
                    status=STATUS_UNIT_MISMATCH,
                    target=None,
                    lab_range=analyte.lab_range,
                    note=(
                        f"референс задан в единицах {analyte.units!r}, "
                        f"измерение пришло в {measurement.units!r}"
                    ),
                    rule_missing=True,
                )
            )
            continue

        target = select_target(analyte, subject)
        if target is None:
            verdicts.append(
                AnalyteVerdict(
                    analyte_id=analyte.id,
                    title=analyte.name,
                    value=measurement.value,
                    units=measurement.units,
                    status=STATUS_NO_RULE,
                    target=None,
                    lab_range=analyte.lab_range,
                    note="нет целевого значения для этого пола и возраста",
                    rule_missing=True,
                )
            )
            continue

        verdicts.append(
            AnalyteVerdict(
                analyte_id=analyte.id,
                title=analyte.name,
                value=measurement.value,
                units=measurement.units,
                status=_status(target, measurement.value),
                target=target.optimal,
                lab_range=analyte.lab_range,
                note=analyte.note,
                rule_missing=False,
            )
        )

    return verdicts
