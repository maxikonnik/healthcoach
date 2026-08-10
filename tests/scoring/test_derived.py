from datetime import date
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


def test_a_unit_needing_a_declared_factor_blocks_the_derived_value_unconverted(
    tmp_path,
):
    """Тот же регресс, что и в scoring/test_reference_matching.py, но на
    производном: 10.0 мг/дл кальция без пересчёта (нужен ×0.2495) дал бы
    отношение 10.0 / 4.0 = 2.5 — «в целевом» для коридора [2.0, 2.5] —
    хотя настоящее отношение 2.495 / 4.0 = 0.624 — далеко от него.
    `compute_derived` обязан отказаться считать, а не подставить число как
    есть."""
    (tmp_path / "x.yaml").write_text(
        "показатели:\n"
        "  - id: кальций\n"
        "    название: Кальций\n"
        "    единицы: ммоль/л\n"
        "    пересчёт:\n"
        "      - из: мг/дл\n"
        "        множитель: 0.2495\n"
        "    целевые:\n"
        "      - оптимум: [2.3, 2.5]\n"
        "  - id: калий\n"
        "    название: Калий\n"
        "    единицы: ммоль/л\n"
        "    целевые:\n"
        "      - оптимум: [4.0, 4.5]\n"
        "производные:\n"
        "  - id: кальций_калий\n"
        "    название: Кальций/Калий\n"
        "    формула: кальций / калий\n"
        "    оптимум: [2.0, 2.5]\n",
        encoding="utf-8",
    )
    (verdict,) = compute_derived(
        load_references(tmp_path),
        [
            Measurement("кальций", 10.0, "мг/дл"),
            Measurement("калий", 4.0, "ммоль/л"),
        ],
    )
    assert verdict.status == "не удалось вычислить"
    assert verdict.value is None
    assert verdict.rule_missing is True
    assert "ммоль/л" in verdict.note


def test_declared_unit_synonym_does_not_block_the_derived_value(tmp_path):
    """Регресс: compute_derived сравнивал единицы прямым равенством строк и
    не знал про объявленные синонимы — измерение в объявленном синониме
    отвергалось так же, как измерение в действительно чужих единицах."""
    (tmp_path / "x.yaml").write_text(
        "показатели:\n"
        "  - id: кальций\n"
        "    название: Кальций\n"
        "    единицы: мг/дл\n"
        "    синонимы_единиц: [mg/dL]\n"
        "    целевые:\n"
        "      - оптимум: [9.2, 10.0]\n"
        "  - id: калий\n"
        "    название: Калий\n"
        "    единицы: ммоль/л\n"
        "    целевые:\n"
        "      - оптимум: [4.0, 4.5]\n"
        "производные:\n"
        "  - id: кальций_калий\n"
        "    название: Кальций/Калий\n"
        "    формула: кальций / калий\n"
        "    оптимум: [2.0, 2.5]\n",
        encoding="utf-8",
    )
    (verdict,) = compute_derived(
        load_references(tmp_path),
        [
            Measurement("кальций", 10.0, "mg/dL"),
            Measurement("калий", 4.0, "ммоль/л"),
        ],
    )
    assert verdict.status == "в целевом"
    assert verdict.value == 2.5
    assert verdict.rule_missing is False


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


def test_derived_computed_when_operands_share_a_snapshot():
    """Правило 5: операнды одного среза — индекс считается, как раньше."""
    (verdict,) = compute_derived(
        load_references(REFS),
        [
            Measurement("кальций", 10.0, "мг/дл", snapshot_id=7),
            Measurement("калий", 4.0, "ммоль/л", snapshot_id=7),
        ],
    )
    assert verdict.status == "в целевом"
    assert verdict.value == 2.5


def test_derived_blocked_when_operands_come_from_different_snapshots():
    """Правило 5: мартовский кальций и августовский калий не образуют
    осмысленное соотношение — индекс не посчитан, причина называет обе
    даты."""
    (verdict,) = compute_derived(
        load_references(REFS),
        [
            Measurement(
                "кальций", 10.0, "мг/дл", taken_on=date(2026, 3, 10), snapshot_id=1
            ),
            Measurement(
                "калий", 4.0, "ммоль/л", taken_on=date(2026, 8, 9), snapshot_id=2
            ),
        ],
    )
    assert verdict.status == "не удалось вычислить"
    assert verdict.value is None
    assert verdict.rule_missing is True
    assert "разных срезов" in verdict.note
    assert "10.03" in verdict.note
    assert "09.08" in verdict.note


def test_the_cross_snapshot_reason_is_coach_only():
    """Причина непосчитанного индекса — рабочий текст коуча, а не находка
    для клиента: `safe_finding` обязан её скрыть от клиента."""
    (verdict,) = compute_derived(
        load_references(REFS),
        [
            Measurement(
                "кальций", 10.0, "мг/дл", taken_on=date(2026, 3, 10), snapshot_id=1
            ),
            Measurement(
                "калий", 4.0, "ммоль/л", taken_on=date(2026, 8, 9), snapshot_id=2
            ),
        ],
    )
    assert verdict.note_private is True


def test_the_blocked_note_does_not_echo_the_units_written_on_the_form():
    """Причина отказа уходит в note, а note уходит модели. Ручной ввод
    сохраняет подпись единиц дословно — пересказывать её наружу значит
    протащить текст документа мимо маски. Коуч видит подпись на экране
    среза, модели она не нужна."""
    (verdict,) = compute_derived(
        load_references(REFS),
        [
            Measurement("кальций", 10.0, "мг/дл"),
            Measurement("калий", 4.0, "ммоль/л SOLOVYOVA I.A."),
        ],
    )
    assert verdict.status == "не удалось вычислить"
    assert "SOLOVYOVA I.A." not in verdict.note
    # Референсные единицы из базы знаний остаются — по ним коуч поймёт,
    # с чем не сошлось.
    assert "ммоль/л" in verdict.note
