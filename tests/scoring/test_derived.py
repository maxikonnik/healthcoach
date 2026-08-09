from pathlib import Path

import pytest

from healthcoach.knowledge.formula import MissingOperand, validate_formula
from healthcoach.knowledge.references import Interval, load_references
from healthcoach.scoring.derived import FormulaError, compute_derived, evaluate_formula
from healthcoach.scoring.references import Measurement

REFS = Path(__file__).parents[2] / "knowledge" / "references"


def test_evaluate_simple_ratio():
    assert evaluate_formula("кальций / калий", {"кальций": 10.0, "калий": 4.0}) == 2.5


def test_evaluate_respects_arithmetic():
    values = {"a": 2.0, "b": 3.0, "c": 4.0}
    assert evaluate_formula("a + b * c", values) == 14.0


def test_missing_operand_raises():
    with pytest.raises(FormulaError, match="калий"):
        evaluate_formula("кальций / калий", {"кальций": 10.0})


def test_division_by_zero_raises():
    with pytest.raises(FormulaError, match="деление на ноль"):
        evaluate_formula("a / b", {"a": 1.0, "b": 0.0})


def test_function_call_rejected():
    with pytest.raises(FormulaError, match="недопустимая конструкция"):
        evaluate_formula("__import__('os').system('ls')", {})


def test_attribute_access_rejected():
    with pytest.raises(FormulaError, match="недопустимая конструкция"):
        evaluate_formula("a.__class__", {"a": 1.0})


def test_computes_calcium_potassium_ratio():
    (verdict,) = compute_derived(
        load_references(REFS),
        [Measurement("кальций", 10.0, "мг/дл"), Measurement("калий", 4.0, "ммоль/л")],
    )
    assert verdict.analyte_id == "кальций_калий"
    assert verdict.value == 2.5
    assert verdict.status == "в целевом"
    assert verdict.target == Interval(2.0, 4.0)


def test_derived_outside_target():
    (verdict,) = compute_derived(
        load_references(REFS),
        [Measurement("кальций", 10.0, "мг/дл"), Measurement("калий", 2.0, "ммоль/л")],
    )
    assert verdict.value == 5.0
    assert verdict.status == "выше целевого"


def test_derived_skipped_when_operand_absent():
    assert compute_derived(
        load_references(REFS), [Measurement("кальций", 10.0, "мг/дл")]
    ) == []


def test_missing_operand_has_its_own_type():
    """Только этот случай пропускается молча, поэтому у него отдельный тип."""
    with pytest.raises(MissingOperand):
        evaluate_formula("кальций / калий", {"кальций": 10.0})


def test_validate_formula_returns_operand_names():
    assert validate_formula("кальций / калий") == ("кальций", "калий")


def test_validate_formula_rejects_syntax_error():
    with pytest.raises(FormulaError, match="не разобрана"):
        validate_formula("кальций /")


def test_validate_formula_rejects_call():
    with pytest.raises(FormulaError, match="недопустимая конструкция"):
        validate_formula("__import__('os').system('ls')")


def test_division_by_zero_gives_verdict_not_silence():
    (verdict,) = compute_derived(
        load_references(REFS),
        [Measurement("кальций", 10.0, "мг/дл"), Measurement("калий", 0.0, "ммоль/л")],
    )
    assert verdict.analyte_id == "кальций_калий"
    assert verdict.status == "не удалось вычислить"
    assert verdict.value is None
    assert verdict.rule_missing is True
    assert "деление на ноль" in verdict.note


def test_unit_mismatch_blocks_the_derived_value():
    """Калий в мг/дл вместо ммоль/л давал уверенное неверное соотношение."""
    (verdict,) = compute_derived(
        load_references(REFS),
        [
            Measurement("кальций", 10.0, "мг/дл"),
            Measurement("калий", 16.0, "мг/дл"),
        ],
    )
    assert verdict.analyte_id == "кальций_калий"
    assert verdict.status == "не удалось вычислить"
    assert verdict.value is None
    assert verdict.rule_missing is True
    assert "ммоль/л" in verdict.note


def test_conflicting_measurements_block_the_derived_value():
    (verdict,) = compute_derived(
        load_references(REFS),
        [
            Measurement("кальций", 10.0, "мг/дл"),
            Measurement("калий", 4.0, "ммоль/л"),
            Measurement("калий", 5.0, "ммоль/л"),
        ],
    )
    assert verdict.status == "не удалось вычислить"
    assert "два разных измерения" in verdict.note


def test_missing_value_operand_blocks_the_derived_value_instead_of_crashing():
    """Регресс: `prepare_measurements` намеренно отдаёт признанный показатель
    с value=None («<0.60» в бланке). Формула, использующая такой операнд,
    раньше пыталась делить None и падала с TypeError — теперь получает
    вердикт с объяснением."""
    (verdict,) = compute_derived(
        load_references(REFS),
        [
            Measurement("кальций", None, "мг/дл"),
            Measurement("калий", 4.3, "ммоль/л"),
        ],
    )
    assert verdict.analyte_id == "кальций_калий"
    assert verdict.status == "не удалось вычислить"
    assert verdict.value is None
    assert verdict.rule_missing is True
    assert "значение не распознано" in verdict.note
