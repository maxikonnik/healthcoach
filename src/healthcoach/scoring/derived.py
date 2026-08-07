"""Производные показатели: соотношения и индексы."""

from __future__ import annotations

import ast
import operator

from healthcoach.knowledge.references import References
from healthcoach.scoring.references import (
    STATUS_ABOVE,
    STATUS_BELOW,
    STATUS_WITHIN,
    AnalyteVerdict,
    Measurement,
)

_OPS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
}


class FormulaError(Exception):
    """Формулу производного показателя невозможно вычислить."""


def _eval(node: ast.AST, values: dict[str, float]) -> float:
    if isinstance(node, ast.BinOp) and type(node.op) in _OPS:
        left = _eval(node.left, values)
        right = _eval(node.right, values)
        if isinstance(node.op, ast.Div) and right == 0:
            raise FormulaError("деление на ноль")
        return _OPS[type(node.op)](left, right)
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub):
        return -_eval(node.operand, values)
    if isinstance(node, ast.Name):
        if node.id not in values:
            raise FormulaError(f"нет значения для операнда {node.id!r}")
        return values[node.id]
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
        return float(node.value)
    raise FormulaError(f"недопустимая конструкция в формуле: {type(node).__name__}")


def evaluate_formula(formula: str, values: dict[str, float]) -> float:
    """Вычислить формулу. Разрешены только имена, числа и арифметика."""
    try:
        tree = ast.parse(formula, mode="eval")
    except SyntaxError as exc:
        raise FormulaError(f"формула не разобрана: {formula!r}") from exc
    return _eval(tree.body, values)


def compute_derived(
    references: References, measurements: list[Measurement]
) -> list[AnalyteVerdict]:
    """Посчитать производные показатели по имеющимся измерениям.

    Производный, для которого не хватает операндов, пропускается молча —
    это не пробел в данных, а просто несобранный набор анализов.
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
        except FormulaError:
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
