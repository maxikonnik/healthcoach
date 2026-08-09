"""Запись бланка — в измерение среза.

Ничего не отбрасывается: нераспознанный показатель сохраняется с пустым
идентификатором и пометкой, нечисловое значение — исходным текстом.
В одной выгрузке два десятка показателей, а в базе знаний коуча их
единицы; отбросить лишнее значило бы потерять данные, которые
понадобятся, как только коуч заведёт референс.
"""

from __future__ import annotations

from dataclasses import dataclass

from healthcoach.intake.lab_table import LabTable, parse_number
from healthcoach.intake.resolve import resolve_analyte
from healthcoach.knowledge.references import References
from healthcoach.knowledge.units import UnitError, convert_to_reference

UNRESOLVED = ""
"""Идентификатор нераспознанного показателя: хранится, но не трактуется."""


@dataclass(frozen=True)
class PreparedMeasurement:
    analyte_id: str
    raw_name: str
    value: float | None
    raw_value: str
    units: str
    problem: str | None


def prepare_measurements(
    references: References, table: LabTable
) -> list[PreparedMeasurement]:
    """Превратить записи бланка в измерения, ничего не отбрасывая."""
    prepared: list[PreparedMeasurement] = []

    for row in table.rows:
        value = parse_number(row.value_text)
        resolution = resolve_analyte(references, row.name)

        analyte_id, units, problem = UNRESOLVED, row.units, None

        if resolution.is_ambiguous:
            candidates = ", ".join(a.name for a in resolution.candidates)
            problem = f"название подходит нескольким показателям: {candidates}"
        elif not resolution.is_certain:
            problem = "показатель не распознан"
        else:
            analyte_id = resolution.analyte.id
            if value is None:
                units = row.units
            else:
                try:
                    value = convert_to_reference(resolution.analyte, value, row.units)
                    units = resolution.analyte.units
                except UnitError:
                    problem = f"единицы не сопоставлены: {row.units}"

        if value is None and problem is None:
            problem = "число не извлечено"
        elif value is None:
            problem = f"{problem}; число не извлечено"

        prepared.append(
            PreparedMeasurement(
                analyte_id=analyte_id,
                raw_name=row.name,
                value=value,
                raw_value=row.value_text,
                units=units,
                problem=problem,
            )
        )

    return prepared

