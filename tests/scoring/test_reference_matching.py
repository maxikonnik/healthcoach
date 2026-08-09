from pathlib import Path

from healthcoach.knowledge.references import Interval, load_references
from healthcoach.scoring.references import (
    STATUS_NO_VALUE,
    Measurement,
    Subject,
    check_measurements,
    select_target,
)

REFS = Path(__file__).parents[2] / "knowledge" / "references"


def _refs():
    return load_references(REFS)


def test_selects_target_by_sex_and_age():
    ferritin = _refs().analyte("ферритин")
    woman = select_target(ferritin, Subject(sex="ж", age=32, cycle_phase=None))
    assert woman.optimal == Interval(60, 90)

    man = select_target(ferritin, Subject(sex="м", age=32, cycle_phase=None))
    assert man.optimal == Interval(80, 150)


def test_falls_back_to_unconditional_target():
    ferritin = _refs().analyte("ферритин")
    older_woman = select_target(ferritin, Subject(sex="ж", age=64, cycle_phase=None))
    assert older_woman.optimal == Interval(60, 120)


def test_deficit_status():
    verdicts = check_measurements(
        _refs(),
        [Measurement("ферритин", 18, "нг/мл")],
        Subject(sex="ж", age=32, cycle_phase=None),
    )
    (verdict,) = verdicts
    assert verdict.status == "дефицит"
    assert verdict.target == Interval(60, 90)
    assert verdict.lab_range == Interval(10, 120)
    assert verdict.rule_missing is False


def test_below_target_but_not_deficit():
    (verdict,) = check_measurements(
        _refs(),
        [Measurement("ферритин", 45, "нг/мл")],
        Subject(sex="ж", age=32, cycle_phase=None),
    )
    assert verdict.status == "ниже целевого"


def test_within_target():
    (verdict,) = check_measurements(
        _refs(),
        [Measurement("ферритин", 75, "нг/мл")],
        Subject(sex="ж", age=32, cycle_phase=None),
    )
    assert verdict.status == "в целевом"


def test_above_target():
    (verdict,) = check_measurements(
        _refs(),
        [Measurement("ферритин", 130, "нг/мл")],
        Subject(sex="ж", age=32, cycle_phase=None),
    )
    assert verdict.status == "выше целевого"


def test_boundary_values_are_inside_target():
    subject = Subject(sex="ж", age=32, cycle_phase=None)
    low, high = check_measurements(
        _refs(),
        [Measurement("ферритин", 60, "нг/мл"), Measurement("ферритин", 90, "нг/мл")],
        subject,
    )
    assert low.status == "в целевом"
    assert high.status == "в целевом"


def test_unknown_analyte_is_reported_not_dropped():
    (verdict,) = check_measurements(
        _refs(),
        [Measurement("гомоцистеин", 12, "мкмоль/л")],
        Subject(sex="ж", age=32, cycle_phase=None),
    )
    assert verdict.status == "правило не задано"
    assert verdict.rule_missing is True
    assert verdict.value == 12


def test_unit_mismatch_is_not_interpreted():
    (verdict,) = check_measurements(
        _refs(),
        [Measurement("ферритин", 18, "пмоль/л")],
        Subject(sex="ж", age=32, cycle_phase=None),
    )
    assert verdict.status == "единицы не сопоставлены"
    assert verdict.rule_missing is True


def test_a_unit_needing_a_declared_factor_is_reported_not_scored_unconverted(tmp_path):
    """Регресс: `units_match` какое-то время принимала и единицы,
    объявленные как требующие пересчёта (`analyte.conversions`), — а
    `check_measurements` сравнивает `measurement.value` с коридором как
    есть, не умножая. 10.0 мг/дл кальция без пересчёта — это 10.0 против
    коридора 2.3-2.5 ммоль/л: «выше целевого», хотя настоящее значение
    (10.0 × 0.2495 = 2.495) — «в целевом». Молча неверный вердикт хуже
    отказа: коуч обязан увидеть «единицы не сопоставлены», а не число,
    которое выглядит как вычисленное, но не пересчитано.
    """
    (tmp_path / "calcium.yaml").write_text(
        "показатели:\n"
        "  - id: кальций\n"
        "    название: Кальций\n"
        "    единицы: ммоль/л\n"
        "    пересчёт:\n"
        "      - из: мг/дл\n"
        "        множитель: 0.2495\n"
        "    целевые:\n"
        "      - оптимум: [2.3, 2.5]\n",
        encoding="utf-8",
    )
    references = load_references(tmp_path)
    (verdict,) = check_measurements(
        references,
        [Measurement("кальций", 10.0, "мг/дл")],
        Subject(sex="ж", age=32, cycle_phase=None),
    )
    assert verdict.status == "единицы не сопоставлены"
    assert verdict.rule_missing is True
    assert verdict.value == 10.0


def test_declared_unit_synonym_is_not_a_mismatch():
    """Регресс: check_measurements сравнивал единицы напрямую строкой и не
    знал про объявленные синонимы (`синонимы_единиц` в ferritin.yaml) — тот
    же самый показатель отвергался как «единицы не сопоставлены» из-за
    написания, которое коуч сам объявил равнозначным. Правило теперь одно —
    `units_match`, оно же используется `convert_to_reference`."""
    (verdict,) = check_measurements(
        _refs(),
        [Measurement("ферритин", 18, "мкг/л")],
        Subject(sex="ж", age=32, cycle_phase=None),
    )
    assert verdict.status == "дефицит"
    assert verdict.rule_missing is False


def test_missing_value_is_reported_not_computed():
    """Регресс: подтверждённое измерение с value=None («<0.60» в бланке)
    раньше падало на сравнении `value > target.optimal.low` (None > float).
    Теперь оно получает свой статус раньше, чем доходит до сравнения."""
    (verdict,) = check_measurements(
        _refs(),
        [Measurement("ферритин", None, "нг/мл")],
        Subject(sex="ж", age=32, cycle_phase=None),
    )
    assert verdict.status == STATUS_NO_VALUE
    assert verdict.value is None
    assert verdict.rule_missing is True


def test_resolves_analyte_by_synonym():
    (verdict,) = check_measurements(
        _refs(),
        [Measurement("Ferritin", 18, "нг/мл")],
        Subject(sex="ж", age=32, cycle_phase=None),
    )
    assert verdict.analyte_id == "ферритин"
    assert verdict.status == "дефицит"
