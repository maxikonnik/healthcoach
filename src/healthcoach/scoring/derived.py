"""Производные показатели: соотношения и индексы."""

from __future__ import annotations

from datetime import date

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

    Правило 5 плана многосрезового отчёта: индекс считается, лишь когда
    все его операнды пришли из одного среза. `snapshots`/`taken_on_by_key`
    копят происхождение каждого операнда, а несовпадение проверяется на
    уровне формулы (см. ниже) — единого среза может не быть даже тогда,
    когда у каждого отдельного операнда со значением всё в порядке.
    """
    values: dict[str, float] = {}
    snapshots: dict[str, int | None] = {}
    taken_on_by_key: dict[str, date | None] = {}
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
        snapshots[key] = measurement.snapshot_id
        taken_on_by_key[key] = measurement.taken_on

    verdicts: list[AnalyteVerdict] = []
    for derived in references.derived:
        operand_names = tuple(dict.fromkeys(validate_formula(derived.formula)))

        # Совсем отсутствующий операнд (ни одного измерения на этот id) —
        # не пробел в данных, а несобранный набор анализов, и должен
        # пропустить производный молча (см. докстроку выше). Эта проверка
        # обязана идти раньше правила 5: иначе у формулы с тремя и более
        # операндами «не хватает одного» превращалось в «значения из
        # разных срезов», как только два оставшихся операнда были
        # разнесены по срезам — реально отсутствующий операнд подменял
        # диагноз, вместо того чтобы промолчать.
        if any(name not in values and name not in unusable for name in operand_names):
            continue

        blocked = [unusable[name] for name in operand_names if name in unusable]

        operand_snapshots = {
            snapshots[name] for name in operand_names if snapshots.get(name) is not None
        }
        if len(operand_snapshots) > 1:
            operand_dates = sorted(
                {
                    taken_on_by_key[name]
                    for name in operand_names
                    if taken_on_by_key.get(name) is not None
                }
            )
            if len(operand_dates) > 1:
                detail = " и ".join(d.strftime("%d.%m") for d in operand_dates)
            else:
                # Дата не различает операнды: либо она у обоих одна и та
                # же (срезы сданы в один день), либо её вовсе нет. То, что
                # различает их по-настоящему, — номер среза; называем его,
                # а не оставляем тире висеть в пустоте.
                detail = " и ".join(
                    f"{name} (срез {snapshots[name]})"
                    for name in operand_names
                    if snapshots.get(name) is not None
                )
            blocked.append(f"значения из разных срезов — {detail}")

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
                    # Причина отказа — рабочий разбор кода для коуча
                    # («два разных измерения», «значения из разных
                    # срезов — …»), а не клиническая находка: клиенту она
                    # ничего не объясняет и не должна доходить.
                    note_private=True,
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
                # Как и у показателя: заметка написана коучем для коуча.
                note_private=True,
            )
        )

    return verdicts
