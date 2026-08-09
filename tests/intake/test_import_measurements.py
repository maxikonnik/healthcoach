from pathlib import Path

from healthcoach.intake.lab_table import LabRow, LabTable
from healthcoach.intake.measurements import prepare_measurements
from healthcoach.knowledge.references import load_references

REFS = Path(__file__).parents[2] / "knowledge" / "references"


def _table(*rows: LabRow) -> LabTable:
    return LabTable(rows=rows, unparsed=())


def test_known_analyte_is_recognised_and_converted():
    references = load_references(REFS)
    table = _table(LabRow("Ферритин", "45", "мкг/л", "10 - 120", "строка"))

    (prepared,) = prepare_measurements(references, table)
    assert prepared.analyte_id == "ферритин"
    assert prepared.value == 45.0
    assert prepared.units == "нг/мл"
    assert prepared.problem is None


def test_unknown_analyte_is_kept_not_dropped():
    """21 показатель в выгрузке против трёх в базе — терять их нельзя."""
    references = load_references(REFS)
    table = _table(LabRow("Гомоцистеин", "12", "мкмоль/л", "5 - 15", "строка"))

    (prepared,) = prepare_measurements(references, table)
    assert prepared.analyte_id == ""
    assert prepared.raw_name == "Гомоцистеин"
    assert prepared.value == 12.0
    assert prepared.problem == "показатель не распознан"


def test_non_numeric_value_keeps_its_text():
    references = load_references(REFS)
    table = _table(LabRow("Ферритин", "<0.60", "нг/мл", "< 5", "строка"))

    (prepared,) = prepare_measurements(references, table)
    assert prepared.value is None
    assert prepared.raw_value == "<0.60"
    assert prepared.problem == "число не извлечено"


def test_unmatched_units_are_not_assumed_equivalent():
    references = load_references(REFS)
    table = _table(LabRow("Ферритин", "45", "пмоль/л", "10 - 120", "строка"))

    (prepared,) = prepare_measurements(references, table)
    assert prepared.units == "пмоль/л"
    assert prepared.value == 45.0
    assert "единицы" in prepared.problem


def test_laboratory_code_in_the_name_does_not_prevent_recognition():
    references = load_references(REFS)
    table = _table(
        LabRow("Ферритин A09.05.076 (Приказ МЗ РФ № 804н)", "45", "нг/мл", "", "строка")
    )

    (prepared,) = prepare_measurements(references, table)
    assert prepared.analyte_id == "ферритин"
