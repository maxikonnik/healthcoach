from pathlib import Path

from healthcoach.knowledge.references import Interval, load_references
from healthcoach.scoring.references import (
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
        [Measurement("ферритин", 18, "мкг/л")],
        Subject(sex="ж", age=32, cycle_phase=None),
    )
    assert verdict.status == "единицы не сопоставлены"
    assert verdict.rule_missing is True


def test_resolves_analyte_by_synonym():
    (verdict,) = check_measurements(
        _refs(),
        [Measurement("Ferritin", 18, "нг/мл")],
        Subject(sex="ж", age=32, cycle_phase=None),
    )
    assert verdict.analyte_id == "ферритин"
    assert verdict.status == "дефицит"
