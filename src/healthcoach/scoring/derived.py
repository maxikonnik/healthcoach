"""Производные показатели: соотношения и индексы."""

from __future__ import annotations

from healthcoach.knowledge.formula import (
    FormulaError,
    MissingOperand,
    evaluate_formula,
)
from healthcoach.knowledge.references import References
from healthcoach.scoring.references import (
    STATUS_ABOVE,
    STATUS_BELOW,
    STATUS_NOT_COMPUTED,
    STATUS_WITHIN,
    AnalyteVerdict,
    Measurement,
)

__all__ = [
    "FormulaError",
    "MissingOperand",
    "compute_derived",
    "evaluate_formula",
]


def compute_derived(
    references: References, measurements: list[Measurement]
) -> list[AnalyteVerdict]:
    """Посчитать производные показатели по имеющимся измерениям.

    Производный, для которого не хватает операндов, пропускается молча —
    это не пробел в данных, а просто несобранный набор анализов. Любая
    другая ошибка вычисления даёт вердикт: молча не теряется ничего.
    """
    values: dict[str, float] = {}
    for measurement in measurements:
        analyte = references.resolve(measurement.analyte_id)
        key = analyte.id if analyte is not None else measurement.analyte_id
        values[key] = measurement.value

    verdicts: list[AnalyteVerdict] = []
    for derived in references.derived:
        try:
            value = evaluate_formula(derived.formula, values)
        except MissingOperand:
            continue
        except FormulaError as exc:
            verdicts.append(
                AnalyteVerdict(
                    analyte_id=derived.id,
                    title=derived.name,
                    value=None,
                    units="",
                    status=STATUS_NOT_COMPUTED,
                    target=derived.optimal,
                    lab_range=None,
                    note=str(exc),
                    rule_missing=True,
                )
            )
            continue

        if derived.optimal.contains(value):
            status = STATUS_WITHIN
        elif derived.optimal.low is not None and value < derived.optimal.low:
            status = STATUS_BELOW
        else:
            status = STATUS_ABOVE

        verdicts.append(
            AnalyteVerdict(
                analyte_id=derived.id,
                title=derived.name,
                value=round(value, 4),
                units="",
                status=status,
                target=derived.optimal,
                lab_range=None,
                note=derived.note,
                rule_missing=False,
            )
        )

    return verdicts
