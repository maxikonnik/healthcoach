from pathlib import Path

import pytest

from healthcoach.knowledge.references import (
    Condition,
    Interval,
    ReferenceError,
    load_references,
)

REFS = Path(__file__).parents[2] / "knowledge" / "references"


def test_interval_contains_with_open_bounds():
    assert Interval(60, 90).contains(75)
    assert not Interval(60, 90).contains(59.9)
    assert Interval(None, 30).contains(5)
    assert Interval(80, None).contains(1000)


def test_condition_matches_sex_and_age():
    c = Condition(sex="ж", age_min=18, age_max=50, cycle_phase=None)
    assert c.matches(sex="ж", age=30, cycle_phase=None)
    assert not c.matches(sex="м", age=30, cycle_phase=None)
    assert not c.matches(sex="ж", age=55, cycle_phase=None)


def test_empty_condition_matches_anything():
    c = Condition(sex=None, age_min=None, age_max=None, cycle_phase=None)
    assert c.matches(sex="м", age=70, cycle_phase="лютеиновая")


def test_loads_ferritin_from_knowledge_base():
    refs = load_references(REFS)
    ferritin = refs.analyte("ферритин")
    assert ferritin is not None
    assert ferritin.units == "нг/мл"
    assert ferritin.lab_range == Interval(10, 120)
    assert "срб" in ferritin.interpret_with
    assert len(ferritin.targets) >= 2


def test_resolve_by_synonym_ignores_case():
    refs = load_references(REFS)
    assert refs.resolve("FERRITIN") is refs.analyte("ферритин")
    assert refs.resolve("  Ферритин ") is refs.analyte("ферритин")
    assert refs.resolve("несуществующий") is None


def test_duplicate_analyte_id_raises(tmp_path):
    for name in ("a.yaml", "b.yaml"):
        (tmp_path / name).write_text(
            "показатели:\n"
            "  - id: дубль\n"
            "    название: Дубль\n"
            "    единицы: ед\n"
            "    целевые:\n"
            "      - оптимум: [1, 2]\n",
            encoding="utf-8",
        )
    with pytest.raises(ReferenceError, match="дубль"):
        load_references(tmp_path)


def test_target_without_optimal_raises(tmp_path):
    (tmp_path / "x.yaml").write_text(
        "показатели:\n"
        "  - id: x\n"
        "    название: Икс\n"
        "    единицы: ед\n"
        "    целевые:\n"
        "      - условие: {пол: м}\n",
        encoding="utf-8",
    )
    with pytest.raises(ReferenceError, match="оптимум"):
        load_references(tmp_path)


def test_non_numeric_interval_bound_names_file_and_analyte(tmp_path):
    """Латинская O вместо нуля — типичная опечатка при ручной правке."""
    (tmp_path / "ferritin_broken.yaml").write_text(
        "показатели:\n"
        "  - id: ферритин\n"
        "    название: Ферритин\n"
        "    единицы: нг/мл\n"
        "    целевые:\n"
        "      - оптимум: [6O, 90]\n",
        encoding="utf-8",
    )
    with pytest.raises(ReferenceError) as excinfo:
        load_references(tmp_path)
    message = str(excinfo.value)
    assert "ferritin_broken.yaml" in message
    assert "ферритин" in message


def test_malformed_condition_names_file_and_analyte(tmp_path):
    (tmp_path / "broken_condition.yaml").write_text(
        "показатели:\n"
        "  - id: ферритин\n"
        "    название: Ферритин\n"
        "    единицы: нг/мл\n"
        "    целевые:\n"
        "      - условие: 5\n"
        "        оптимум: [60, 90]\n",
        encoding="utf-8",
    )
    with pytest.raises(ReferenceError) as excinfo:
        load_references(tmp_path)
    message = str(excinfo.value)
    assert "broken_condition.yaml" in message
    assert "ферритин" in message


def test_malformed_interval_shape_names_file_and_analyte(tmp_path):
    (tmp_path / "broken_shape.yaml").write_text(
        "показатели:\n"
        "  - id: ферритин\n"
        "    название: Ферритин\n"
        "    единицы: нг/мл\n"
        "    целевые:\n"
        "      - оптимум: 60\n",
        encoding="utf-8",
    )
    with pytest.raises(ReferenceError) as excinfo:
        load_references(tmp_path)
    message = str(excinfo.value)
    assert "broken_shape.yaml" in message
    assert "ферритин" in message


def test_broken_formula_names_file_and_derived(tmp_path):
    (tmp_path / "broken_formula.yaml").write_text(
        "производные:\n"
        "  - id: плохой\n"
        "    название: Плохой\n"
        "    формула: 'кальций /'\n"
        "    оптимум: [1, 2]\n",
        encoding="utf-8",
    )
    with pytest.raises(ReferenceError) as excinfo:
        load_references(tmp_path)
    message = str(excinfo.value)
    assert "broken_formula.yaml" in message
    assert "плохой" in message


def test_unit_aliases_and_conversions_are_parsed(tmp_path):
    (tmp_path / "x.yaml").write_text(
        "показатели:\n"
        "  - id: глюкоза\n"
        "    название: Глюкоза\n"
        "    единицы: ммоль/л\n"
        "    синонимы_единиц: [mmol/L]\n"
        "    пересчёт:\n"
        "      - из: мг/дл\n"
        "        множитель: 0.0555\n"
        "    целевые:\n"
        "      - оптимум: [4.1, 5.3]\n",
        encoding="utf-8",
    )
    glucose = load_references(tmp_path).analyte("глюкоза")
    assert glucose.unit_aliases == ("mmol/L",)
    assert glucose.conversions[0].from_units == "мг/дл"
    assert glucose.conversions[0].factor == 0.0555


def test_analytes_without_the_new_keys_still_load(tmp_path):
    (tmp_path / "x.yaml").write_text(
        "показатели:\n"
        "  - id: x\n"
        "    название: Икс\n"
        "    единицы: ед\n"
        "    целевые:\n"
        "      - оптимум: [1, 2]\n",
        encoding="utf-8",
    )
    analyte = load_references(tmp_path).analyte("x")
    assert analyte.unit_aliases == ()
    assert analyte.conversions == ()


def test_empty_synonym_is_refused(tmp_path):
    """Пустой ключ в указателе ловил бы каждое нераспознанное измерение.

    Нераспознанные измерения хранятся с пустым идентификатором показателя.
    Ключ "" в указателе означает, что сверка находит по нему этот показатель,
    и чужое значение выходит в находки под его именем.
    """
    directory = tmp_path / "references"
    directory.mkdir()
    (directory / "ferritin.yaml").write_text(
        "показатели:\n"
        "  - id: ферритин\n"
        "    название: Ферритин\n"
        "    единицы: нг/мл\n"
        "    синонимы: [Ferritin, '']\n"
        "    целевые:\n"
        "      - оптимум: [50, 90]\n",
        encoding="utf-8",
    )
    with pytest.raises(ReferenceError, match="пустое название или синоним"):
        load_references(directory)
