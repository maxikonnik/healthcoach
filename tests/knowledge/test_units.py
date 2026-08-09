from pathlib import Path

import pytest

from healthcoach.knowledge.references import load_references
from healthcoach.knowledge.units import UnitError, convert_to_reference, normalize_units

REFS = Path(__file__).parents[2] / "knowledge" / "references"


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("нг/мл", "нг/мл"),
        ("  НГ/МЛ  ", "нг/мл"),
        ("нг / мл", "нг/мл"),
        ("ng/mL", "ng/ml"),
        ("мкг/л", "мкг/л"),
    ],
)
def test_normalize_units(raw, expected):
    assert normalize_units(raw) == expected


def test_same_units_pass_through():
    ferritin = load_references(REFS).analyte("ферритин")
    assert convert_to_reference(ferritin, 18.0, "нг/мл") == 18.0


def test_alias_needs_no_arithmetic():
    """мкг/л и нг/мл — одно и то же число, пересчитывать нечего."""
    ferritin = load_references(REFS).analyte("ферритин")
    assert convert_to_reference(ferritin, 18.0, "мкг/л") == 18.0
    assert convert_to_reference(ferritin, 18.0, "ng/mL") == 18.0


def test_alias_matching_ignores_case_and_spaces():
    ferritin = load_references(REFS).analyte("ферритин")
    assert convert_to_reference(ferritin, 18.0, " МКГ / Л ") == 18.0


def test_unknown_units_raise_naming_both():
    ferritin = load_references(REFS).analyte("ферритин")
    with pytest.raises(UnitError) as excinfo:
        convert_to_reference(ferritin, 18.0, "пмоль/л")
    message = str(excinfo.value)
    assert "ферритин" in message
    assert "пмоль/л" in message
    assert "нг/мл" in message


def test_declared_conversion_is_applied(tmp_path):
    (tmp_path / "glucose.yaml").write_text(
        "показатели:\n"
        "  - id: глюкоза\n"
        "    название: Глюкоза\n"
        "    единицы: ммоль/л\n"
        "    пересчёт:\n"
        "      - из: мг/дл\n"
        "        множитель: 0.0555\n"
        "    целевые:\n"
        "      - оптимум: [4.1, 5.3]\n",
        encoding="utf-8",
    )
    glucose = load_references(tmp_path).analyte("глюкоза")
    assert convert_to_reference(glucose, 90.0, "мг/дл") == pytest.approx(4.995)


def test_conversion_without_multiplier_is_refused(tmp_path):
    (tmp_path / "bad.yaml").write_text(
        "показатели:\n"
        "  - id: x\n"
        "    название: Икс\n"
        "    единицы: ед\n"
        "    пересчёт:\n"
        "      - из: другие\n"
        "    целевые:\n"
        "      - оптимум: [1, 2]\n",
        encoding="utf-8",
    )
    from healthcoach.knowledge.references import ReferenceError

    with pytest.raises(ReferenceError, match="множитель"):
        load_references(tmp_path)


def test_normalisers_in_the_two_modules_agree():
    """references.py нормализует единицы своей копией — она не должна разойтись."""
    from healthcoach.knowledge.references import _normalized_unit

    for raw in ("нг/мл", "  НГ / МЛ ", "ng/mL", "ммоль/л", "МКГ/Л"):
        assert _normalized_unit(raw) == normalize_units(raw)


@pytest.mark.parametrize("bad", [".inf", "-.inf", ".nan", "0", "-1.5"])
def test_degenerate_multiplier_is_refused(tmp_path, bad):
    """Опечатка в множителе превратила бы анализ в бесконечность или ноль."""
    from healthcoach.knowledge.references import ReferenceError

    (tmp_path / "x.yaml").write_text(
        "показатели:\n"
        "  - id: глюкоза\n"
        "    название: Глюкоза\n"
        "    единицы: ммоль/л\n"
        "    пересчёт:\n"
        "      - из: мг/дл\n"
        f"        множитель: {bad}\n"
        "    целевые:\n"
        "      - оптимум: [4.1, 5.3]\n",
        encoding="utf-8",
    )
    with pytest.raises(ReferenceError) as excinfo:
        load_references(tmp_path)
    message = str(excinfo.value)
    assert "глюкоза" in message
    assert "множитель" in message


def test_unit_declared_both_ways_is_refused(tmp_path):
    from healthcoach.knowledge.references import ReferenceError

    (tmp_path / "x.yaml").write_text(
        "показатели:\n"
        "  - id: ферритин\n"
        "    название: Ферритин\n"
        "    единицы: нг/мл\n"
        "    синонимы_единиц: [мкг/л]\n"
        "    пересчёт:\n"
        "      - из: МКГ / Л\n"
        "        множитель: 2\n"
        "    целевые:\n"
        "      - оптимум: [60, 90]\n",
        encoding="utf-8",
    )
    with pytest.raises(ReferenceError) as excinfo:
        load_references(tmp_path)
    message = str(excinfo.value)
    assert "ферритин" in message
    assert "одно" in message


def test_reference_units_cannot_also_be_a_conversion_source(tmp_path):
    from healthcoach.knowledge.references import ReferenceError

    (tmp_path / "x.yaml").write_text(
        "показатели:\n"
        "  - id: ферритин\n"
        "    название: Ферритин\n"
        "    единицы: нг/мл\n"
        "    пересчёт:\n"
        "      - из: нг/мл\n"
        "        множитель: 3\n"
        "    целевые:\n"
        "      - оптимум: [60, 90]\n",
        encoding="utf-8",
    )
    with pytest.raises(ReferenceError, match="ферритин"):
        load_references(tmp_path)
