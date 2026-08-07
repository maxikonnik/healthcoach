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
