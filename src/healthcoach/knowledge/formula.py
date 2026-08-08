"""Мини-язык формул базы знаний.

Формулы приходят из данных, поэтому разбираются деревом с белым списком
узлов: имена, числа, четыре арифметических действия и унарный минус.
Никакого eval — данные не должны уметь выполнять код.
"""

from __future__ import annotations

import ast
import operator

_OPS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
}

_VALIDATION_PLACEHOLDER = 1.0
"""Подставляется вместо операнда, когда проверяется только форма формулы."""


class FormulaError(Exception):
    """Формулу производного показателя невозможно вычислить."""


class MissingOperand(FormulaError):
    """Не хватает измерения для одного из операндов формулы.

    Единственный случай, в котором производный показатель пропускается
    молча: это не пробел в данных, а просто несобранный набор анализов.
    """


def _parse(formula: str) -> ast.Expression:
    try:
        return ast.parse(formula, mode="eval")
    except SyntaxError as exc:
        raise FormulaError(f"формула не разобрана: {formula!r}") from exc


def _walk(node: ast.AST, values: dict[str, float] | None, names: list[str]) -> float:
    """Обойти дерево формулы.

    При `values is None` идёт проверка формы: имена операндов собираются
    в `names`, вместо значений подставляется единица, измерения не нужны.
    """
    if isinstance(node, ast.BinOp) and type(node.op) in _OPS:
        left = _walk(node.left, values, names)
        right = _walk(node.right, values, names)
        if isinstance(node.op, ast.Div) and right == 0:
            raise FormulaError("деление на ноль")
        return _OPS[type(node.op)](left, right)
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub):
        return -_walk(node.operand, values, names)
    if isinstance(node, ast.Name):
        names.append(node.id)
        if values is None:
            return _VALIDATION_PLACEHOLDER
        if node.id not in values:
            raise MissingOperand(f"нет значения для операнда {node.id!r}")
        return values[node.id]
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
        return float(node.value)
    raise FormulaError(f"недопустимая конструкция в формуле: {type(node).__name__}")


def evaluate_formula(formula: str, values: dict[str, float]) -> float:
    """Вычислить формулу. Разрешены только имена, числа и арифметика."""
    return _walk(_parse(formula).body, values, [])


def validate_formula(formula: str) -> tuple[str, ...]:
    """Проверить форму формулы, не вычисляя её, и вернуть имена операндов."""
    names: list[str] = []
    _walk(_parse(formula).body, None, names)
    return tuple(names)
