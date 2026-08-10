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


def test_only_the_unresolved_path_says_the_title_came_from_the_document():
    """`rule_missing` поднят на четырёх путях, а заголовок из бланка
    приходит ровно с одного. Маска, стоящая на `rule_missing`, прячет от
    модели названия из базы знаний коуча — таблица ниже перечисляет все
    четыре пути и то, откуда у каждого берётся заголовок."""
    (unresolved,) = check_measurements(
        _refs(),
        [Measurement("", 12.0, "мкмоль/л", label="Гомоцистеин по Инвитро")],
        Subject(sex="ж", age=32, cycle_phase=None),
    )
    assert unresolved.rule_missing is True
    assert unresolved.title == "Гомоцистеин по Инвитро"
    assert unresolved.title_from_document is True
    assert unresolved.units_from_document is True

    (no_value,) = check_measurements(
        _refs(),
        [Measurement("ферритин", None, "нг/мл", label="SOLOVYOVA I.A. Ферритин")],
        Subject(sex="ж", age=32, cycle_phase=None),
    )
    assert no_value.rule_missing is True
    assert no_value.title_from_document is True

    (mismatch,) = check_measurements(
        _refs(),
        [Measurement("ферритин", 18.0, "мг/дл", label="SOLOVYOVA I.A. Ферритин")],
        Subject(sex="ж", age=32, cycle_phase=None),
    )
    assert mismatch.rule_missing is True
    assert mismatch.title == "Ферритин"
    # Название — из базы знаний, единицы — из бланка.
    assert mismatch.title_from_document is False
    assert mismatch.units_from_document is True


def test_a_target_missing_for_this_sex_and_age_keeps_the_title_from_the_knowledge_base(
    tmp_path,
):
    """Четвёртый путь с `rule_missing`: показатель распознан, единицы
    сошлись, но целевого коридора для этого пола и возраста нет."""
    (tmp_path / "test.yaml").write_text(
        "показатели:\n"
        "  - id: тестостерон\n"
        "    название: Тестостерон\n"
        "    единицы: нмоль/л\n"
        "    целевые:\n"
        "      - условие: {пол: м}\n"
        "        оптимум: [12.0, 30.0]\n",
        encoding="utf-8",
    )
    (verdict,) = check_measurements(
        load_references(tmp_path),
        [Measurement("тестостерон", 1.2, "нмоль/л", label="SOLOVYOVA I.A.")],
        Subject(sex="ж", age=32, cycle_phase=None),
    )
    assert verdict.status == "правило не задано"
    assert verdict.rule_missing is True
    assert verdict.title == "Тестостерон"
    assert verdict.title_from_document is False
    assert verdict.units_from_document is False


def test_the_row_of_the_snapshot_reaches_the_verdict():
    """Различитель нераспознанных находок берётся отсюда."""
    (verdict,) = check_measurements(
        _refs(),
        [Measurement("", 12.0, "мкмоль/л", label="Гомоцистеин", row_id=41)],
        Subject(sex="ж", age=32, cycle_phase=None),
    )
    assert verdict.row_id == 41
