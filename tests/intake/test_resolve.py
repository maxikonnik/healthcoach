from pathlib import Path

import pytest

from healthcoach.intake.resolve import resolve_analyte
from healthcoach.knowledge.references import load_references

REFS = Path(__file__).parents[2] / "knowledge" / "references"


@pytest.fixture
def references():
    return load_references(REFS)


@pytest.mark.parametrize(
    "raw",
    [
        "Ферритин",
        "ферритин",
        "ФЕРРИТИН",
        "  Ферритин  ",
        "Ферритин (S-Ferritin)",
        "Ферритин, нг/мл",
        "Ферритин*",
        "Ferritin",
        "S-Ferritin",
    ],
)
def test_recognises_ferritin_in_its_many_spellings(references, raw):
    resolution = resolve_analyte(references, raw)
    assert resolution.is_certain
    assert resolution.analyte.id == "ферритин"
    assert resolution.raw_name == raw


def test_lab_code_with_the_order_boilerplate_is_stripped(references):
    resolution = resolve_analyte(references, "Кальций A09.05.206 (Приказ МЗ РФ № 804н)")
    assert resolution.is_certain
    assert resolution.analyte.id == "кальций"


def test_lab_code_with_a_qualifying_parenthesis_is_not_stripped(references):
    """Регресс: код + любая другая скобка стирались целиком, и «Кальций
    A09.05.206 (ионизированный)» — общий кальций с корзиной 9.2-10.0 мг/дл —
    находился по имени общего кальция, хотя ионизированный кальций мерится
    в других единицах и имеет другой коридор. Скобка должна остаться в
    имени, чтобы показатель остался нераспознанным, а не был перепутан."""
    resolution = resolve_analyte(references, "Кальций A09.05.206 (ионизированный)")
    assert not resolution.is_certain
    assert resolution.is_unknown


def test_unknown_name_is_reported_not_guessed(references):
    resolution = resolve_analyte(references, "Гомоцистеин")
    assert resolution.is_unknown
    assert resolution.analyte is None
    assert resolution.candidates == ()


def test_ambiguous_name_returns_all_candidates(tmp_path):
    (tmp_path / "two.yaml").write_text(
        "показатели:\n"
        "  - id: витамин_д_25oh\n"
        "    название: Витамин D\n"
        "    синонимы: [Витамин D]\n"
        "    единицы: нг/мл\n"
        "    целевые:\n"
        "      - оптимум: [50, 80]\n"
        "  - id: витамин_д_125oh\n"
        "    название: Витамин D активный\n"
        "    синонимы: [Витамин D]\n"
        "    единицы: пг/мл\n"
        "    целевые:\n"
        "      - оптимум: [20, 60]\n",
        encoding="utf-8",
    )
    references = load_references(tmp_path)
    resolution = resolve_analyte(references, "Витамин D")
    assert resolution.is_ambiguous
    assert resolution.analyte is None
    assert {a.id for a in resolution.candidates} == {
        "витамин_д_25oh",
        "витамин_д_125oh",
    }


def test_empty_name_is_unknown(references):
    assert resolve_analyte(references, "   ").is_unknown


def test_certainty_flags_are_mutually_exclusive(references):
    for raw in ("Ферритин", "Гомоцистеин", ""):
        resolution = resolve_analyte(references, raw)
        flags = [
            resolution.is_certain,
            resolution.is_unknown,
            resolution.is_ambiguous,
        ]
        assert sum(flags) == 1


def test_resolution_refuses_a_lone_candidate_without_the_analyte():
    """Все три признака оказались бы ложными, и вызывающий код провалился бы мимо ветвей."""
    from healthcoach.intake.resolve import Resolution

    references = load_references(REFS)
    ferritin = references.analyte("ферритин")
    with pytest.raises(ValueError, match="единственный кандидат"):
        Resolution(analyte=None, candidates=(ferritin,), raw_name="Ферритин")


def test_resolution_refuses_an_analyte_absent_from_its_own_candidates():
    from healthcoach.intake.resolve import Resolution

    references = load_references(REFS)
    ferritin = references.analyte("ферритин")
    with pytest.raises(ValueError, match="единственным кандидатом"):
        Resolution(analyte=ferritin, candidates=(), raw_name="Ферритин")


def test_every_outcome_of_the_real_resolver_satisfies_the_invariant():
    """Инвариант выполняется на всех исходах, а не только на удобных."""
    references = load_references(REFS)
    for raw in ("Ферритин", "Гомоцистеин", "", "(нг/мл)", "Ferritin", "Кальций"):
        resolution = resolve_analyte(references, raw)
        flags = [resolution.is_certain, resolution.is_unknown, resolution.is_ambiguous]
        assert sum(flags) == 1, f"{raw!r}: {flags}"
