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


def test_unmatched_units_are_reported_even_without_a_number():
    """Регресс: сверка единиц раньше пропускалась целиком, если числа не
    было — «единицы не сопоставлены» терялось, коуч вписывал число вручную
    вслепую, не зная, что единицы тоже не те."""
    references = load_references(REFS)
    table = _table(LabRow("Ферритин", "<0.60", "пмоль/л", "< 5", "строка"))

    (prepared,) = prepare_measurements(references, table)
    assert prepared.value is None
    assert prepared.analyte_id == "ферритин"
    assert "единицы" in prepared.problem
    assert "число не извлечено" in prepared.problem


def test_missing_units_do_not_leave_a_trailing_blank_message():
    references = load_references(REFS)
    table = _table(LabRow("Ферритин", "45", "", "10 - 120", "строка"))

    (prepared,) = prepare_measurements(references, table)
    assert prepared.problem == "единицы не сопоставлены: не указаны"


def test_unit_needing_a_factor_is_not_canonicalised_without_a_number(tmp_path):
    """Регресс: ветка `value is None` канонизировала единицы через ту же
    проверку, что и числовая ветка (`convert_to_reference` без исключения),
    и «Кальций <5.0 мг/дл» получал бы units='ммоль/л' — подпись референса —
    хотя число ещё не пересчитано и не будет: `set_value` впишет то, что
    коуч наберёт на форме, подписанной этими самыми единицами. Коуч увидел
    бы форму «ммоль/л» и вписал бы число из бланка в мг/дл как будто оно уже
    в ммоль/л. Без числа для умножения единицы, которым нужен множитель,
    обязаны остаться подписью бланка, а не референса — как для по-настоящему
    несопоставленных единиц.
    """
    (tmp_path / "test.yaml").write_text(
        "показатели:\n"
        "  - id: тест\n"
        "    название: Тестовый показатель\n"
        "    единицы: ед2\n"
        "    пересчёт:\n"
        "      - из: ед1\n"
        "        множитель: 2.0\n"
        "    целевые:\n"
        "      - оптимум: [1, 100]\n",
        encoding="utf-8",
    )
    references = load_references(tmp_path)
    table = _table(LabRow("Тестовый показатель", "<10", "ед1", "", "строка"))

    (prepared,) = prepare_measurements(references, table)
    assert prepared.analyte_id == "тест"
    assert prepared.value is None
    assert prepared.units == "ед1"
    assert "единицы" in prepared.problem


def test_conversion_factor_is_actually_applied(tmp_path):
    """Регресс, доказанный мутацией: тест на алиас `мкг/л -> нг/мл` (1:1)
    проходил бы, даже если результат `convert_to_reference` отбрасывался —
    ни один живой показатель не объявляет множитель пересчёта. Здесь
    множитель объявлен явно, и результат должен быть реально умножен."""
    (tmp_path / "test.yaml").write_text(
        "показатели:\n"
        "  - id: тест\n"
        "    название: Тестовый показатель\n"
        "    единицы: ед2\n"
        "    пересчёт:\n"
        "      - из: ед1\n"
        "        множитель: 2.0\n"
        "    целевые:\n"
        "      - оптимум: [1, 100]\n",
        encoding="utf-8",
    )
    references = load_references(tmp_path)
    table = _table(LabRow("Тестовый показатель", "10", "ед1", "", "строка"))

    (prepared,) = prepare_measurements(references, table)
    assert prepared.analyte_id == "тест"
    assert prepared.value == 20.0
    assert prepared.units == "ед2"
    assert prepared.problem is None
