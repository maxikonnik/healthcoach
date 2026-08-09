"""Производные показатели: соотношения и индексы."""

from __future__ import annotations

from healthcoach.knowledge.formula import (
    FormulaError,
    MissingOperand,
    evaluate_formula,
    validate_formula,
)
from healthcoach.knowledge.references import References
from healthcoach.knowledge.units import units_match
from healthcoach.scoring.references import (
    STATUS_ABOVE,
    STATUS_BELOW,
    STATUS_NOT_COMPUTED,
    STATUS_NO_VALUE,
    STATUS_WITHIN,
    AnalyteVerdict,
    Measurement,
)

__all__ = [
    "FormulaError",
    "MissingOperand",
    "compute_derived",
    "evaluate_formula",
    "validate_formula",
]


def compute_derived(
    references: References, measurements: list[Measurement]
) -> list[AnalyteVerdict]:
    """Посчитать производные показатели по имеющимся измерениям.

    Производный, для которого не хватает операндов, пропускается молча —
    это не пробел в данных, а просто несобранный набор анализов. Любая
    другая ошибка вычисления даёт вердикт: молча не теряется ничего.

    Измерение без числа («<0.60» в бланке) — операнд, а не пробел: если
    формула его использует, она должна отказаться с объяснением, а не
    получить None вместо float. `values` копит только настоящие числа;
    отсутствующее значение сразу помечает операнд негодным.
    """
    values: dict[str, float] = {}
    unusable: dict[str, str] = {}

    for measurement in measurements:
        analyte = references.resolve(measurement.analyte_id)
        key = analyte.id if analyte is not None else measurement.analyte_id
        title = analyte.name if analyte is not None else (measurement.label or key)

        if measurement.value is None:
            unusable[key] = f"{title}: {STATUS_NO_VALUE}"
            continue

        if analyte is not None and not units_match(analyte, measurement.units):
            # Написание единиц из бланка сюда не переписывается: эта причина
            # уходит в note вердикта, а note уходит модели. Ручной ввод
            # сохраняет подпись единиц дословно — там может оказаться что
            # угодно, вплоть до строки с именем клиента. Коуч видит исходную
            # подпись на экране среза, модели она не нужна.
            unusable[key] = (
                f"{analyte.name}: референс задан в единицах {analyte.units!r}, "
                f"единицы из бланка с ними не сопоставлены"
            )
        if key in values and values[key] != measurement.value:
            unusable[key] = (
                f"{key}: два разных измерения — {values[key]} и {measurement.value}"
            )
        values[key] = measurement.value

    verdicts: list[AnalyteVerdict] = []
    for derived in references.derived:
        blocked = [
            unusable[name]
            for name in dict.fromkeys(validate_formula(derived.formula))
            if name in unusable
        ]
        if blocked:
            verdicts.append(
                AnalyteVerdict(
                    analyte_id=derived.id,
                    title=derived.name,
                    value=None,
                    units="",
                    status=STATUS_NOT_COMPUTED,
                    target=derived.optimal,
                    lab_range=None,
                    note="; ".join(blocked),
                    rule_missing=True,
                )
            )
            continue

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
