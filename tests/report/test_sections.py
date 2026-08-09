from healthcoach.report.sections import SECTIONS, Section
from healthcoach.scoring.findings import (
    KIND_ANALYTE,
    KIND_DERIVED,
    KIND_QUESTIONNAIRE,
)


def test_sections_are_the_ones_the_specification_names():
    ids = [s.id for s in SECTIONS]
    assert ids == [
        "запрос",
        "карта_систем",
        "показатели",
        "динамика",
        "врачи",
        "образ_жизни",
        "практики",
        "шаги",
    ]


def test_every_section_has_an_instruction_and_a_title():
    for section in SECTIONS:
        assert section.title.strip()
        assert len(section.instruction.strip()) > 40


def test_section_ids_are_unique():
    ids = [s.id for s in SECTIONS]
    assert len(ids) == len(set(ids))


KINDS_BY_SECTION = {
    # «Запрос» пересказывает цели клиента его же словами и не трактует ни
    # одной находки — пустой кортеж здесь осознанный, а не забытый.
    "запрос": (),
    "карта_систем": (KIND_QUESTIONNAIRE,),
    "показатели": (KIND_ANALYTE, KIND_DERIVED),
    "динамика": (KIND_ANALYTE, KIND_DERIVED),
    "врачи": (KIND_ANALYTE, KIND_DERIVED, KIND_QUESTIONNAIRE),
    "образ_жизни": (KIND_QUESTIONNAIRE, KIND_ANALYTE),
    "практики": (KIND_QUESTIONNAIRE,),
    "шаги": (KIND_ANALYTE, KIND_DERIVED, KIND_QUESTIONNAIRE),
}


def test_every_section_declares_which_findings_it_stands_on():
    """Раздел без привязки к находкам нечем обосновать перед коучем.

    Проверка именная, а не «это кортеж»: последняя проходила и с начисто
    стёртой привязкой у всех восьми разделов — она не удерживала ничего.
    Здесь перечислен каждый раздел, так что стереть привязку молча нельзя
    ни у одного.
    """
    assert {s.id: s.kinds for s in SECTIONS} == KINDS_BY_SECTION


def test_every_declared_kind_is_a_kind_that_findings_actually_carry():
    """Вид, которого никто не выставляет, оставил бы раздел без находок,
    ничем не пожаловавшись."""
    known = {KIND_ANALYTE, KIND_DERIVED, KIND_QUESTIONNAIRE}
    for section in SECTIONS:
        assert set(section.kinds) <= known, section.id
