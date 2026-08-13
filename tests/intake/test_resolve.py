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


@pytest.mark.parametrize(
    ("percent", "absolute", "percent_id", "absolute_id"),
    [
        ("Лимфоциты (LYMPH), %", "Лимфоциты (LYMPH), абсолютное количество",
         "лимфоциты", "лимфоциты_абс"),
        ("Моноциты (MON), %", "Моноциты (MON), абсолютное количество",
         "моноциты", "моноциты_абс"),
        ("Нейтрофилы (Ne), %", "Нейтрофилы (Ne), абсолютное количество",
         "нейтрофилы", "нейтрофилы_абс"),
        ("Эозинофилы (Ео), %", "Эозинофилы (Ео), абсолютное количество",
         "эозинофилы", "эозинофилы_абс"),
        ("Базофилы (Ва), %", "Базофилы (Ва), абсолютное количество",
         "базофилы", "базофилы_абс"),
    ],
)
def test_tail_after_the_comma_names_the_quantity_not_the_units(
    references, percent, absolute, percent_id, absolute_id
):
    """Хвост после запятой бывает не единицами, а именем самой величины.

    Лейкоцитарная формула печатает две строки на одну клеточную линию:
    процент и абсолютный счёт. Пока всё после первой запятой отбрасывалось,
    обе сходились в одно написание, обе находили процентный показатель, и
    абсолютный счёт отвергался с «единицы не сопоставлены» — жалобой на
    единицы вместо «это другой показатель».
    """
    percent_resolution = resolve_analyte(references, percent)
    assert percent_resolution.is_certain, f"{percent!r} не распознан"
    assert percent_resolution.analyte.id == percent_id

    absolute_resolution = resolve_analyte(references, absolute)
    assert absolute_resolution.is_certain, f"{absolute!r} не распознан"
    assert absolute_resolution.analyte.id == absolute_id

    assert percent_resolution.analyte.units == "%"
    assert absolute_resolution.analyte.units != "%"


@pytest.mark.parametrize(
    "raw",
    ["{cell}, абс.", "{cell}, абс", "{cell} абс."],
)
@pytest.mark.parametrize(
    ("cell", "absolute_id"),
    [
        ("Лимфоциты", "лимфоциты_абс"),
        ("Моноциты", "моноциты_абс"),
        ("Нейтрофилы", "нейтрофилы_абс"),
        ("Эозинофилы", "эозинофилы_абс"),
        ("Базофилы", "базофилы_абс"),
    ],
)
def test_abbreviated_absolute_count_is_not_the_percentage_analyte(
    references, raw, cell, absolute_id
):
    """«абс.» — то же, что «абсолютное количество», и написано так чаще.

    Словарь знал полное написание и «#», но не самое ходовое сокращение:
    «Лимфоциты, абс.» не находилось уточнённой попыткой, проваливалось в
    общую (всё после запятой отброшено) и приходило к процентному
    показателю — ровно то перепутывание величин, ради которого уточнённая
    попытка и написана. Сеть из единиц ловит это не всегда: бланк без
    колонки единиц законен, и тогда ловить нечем, а абсолютный счёт
    клиентки навсегда встанет в её динамику под процентами.

    Этого написания нет в сегодняшнем корпусе — синоним заведён как
    осознанное исключение из правила «только по корпусу»: цена промаха
    здесь не «строка не распознана», а неверная величина в базе.
    """
    resolution = resolve_analyte(references, raw.format(cell=cell))
    assert resolution.is_certain, f"{raw!r} не распознан"
    assert resolution.analyte.id == absolute_id
    assert resolution.analyte.units != "%"


@pytest.mark.parametrize(
    ("raw", "analyte_id"),
    [
        ("Лимфоциты (LY) #", "лимфоциты_абс"),
        ("Моноциты (MO) #", "моноциты_абс"),
        ("Эозинофилы (EO) #", "эозинофилы_абс"),
        ("Базофилы (BA) #", "базофилы_абс"),
        ("Нейтрофилы (NE) #", "нейтрофилы_абс"),
        ("Незрелые гранулоциты (IG) #", "незрелые_гранулоциты"),
        ("Лимфоциты (LY) %", "лимфоциты"),
        ("Моноциты (MO) %", "моноциты"),
        ("Эозинофилы (EO) %", "эозинофилы"),
        ("Базофилы (BA) %", "базофилы"),
        ("Нейтрофилы (NE) %", "нейтрофилы"),
        ("Незрелые гранулоциты (IG) %", "незрелые_гранулоциты_процент"),
    ],
)
def test_hash_marks_the_absolute_count_percent_marks_the_share(
    references, raw, analyte_id
):
    """«#» и «%» той же лаборатории — две величины, а не два написания."""
    resolution = resolve_analyte(references, raw)
    assert resolution.is_certain, f"{raw!r} не распознан"
    assert resolution.analyte.id == analyte_id


def test_general_form_still_wins_when_the_tail_is_only_units(references):
    """Уточнённая попытка не отбирает у общей то, что она узнавала.

    «Гемоглобин, г/л» уточнённым написанием не является: за запятой стоят
    единицы, того же показателя, и найтись строка обязана по-прежнему.
    """
    for raw, analyte_id in (
        ("Гемоглобин, г/л", "гемоглобин"),
        ("Ферритин, нг/мл", "ферритин"),
        ("Лимфоциты", "лимфоциты"),
    ):
        resolution = resolve_analyte(references, raw)
        assert resolution.is_certain, f"{raw!r} не распознан"
        assert resolution.analyte.id == analyte_id


def test_lab_code_and_footnotes_are_stripped_on_both_attempts(references):
    """Обе попытки чистят одинаково: код номенклатуры, сноски, скобки.

    Уточнённая попытка идёт первой, и если бы она работала по сырой
    строке, код номенклатуры перед названием ломал бы её молча — а видно
    это стало бы только на строках с запятой.
    """
    with_code = resolve_analyte(
        references, "Лимфоциты A12.05.123, абсолютное количество"
    )
    assert with_code.is_certain
    assert with_code.analyte.id == "лимфоциты_абс"

    with_order = resolve_analyte(
        references,
        "Лимфоциты A12.05.123 (Приказ МЗ РФ № 804н), абсолютное количество",
    )
    assert with_order.is_certain
    assert with_order.analyte.id == "лимфоциты_абс"

    with_footnote = resolve_analyte(references, "Лимфоциты (LYMPH)*, %")
    assert with_footnote.is_certain
    assert with_footnote.analyte.id == "лимфоциты"


def test_unknown_name_is_reported_not_guessed(references):
    resolution = resolve_analyte(references, "Выдуманный показатель")
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
