from healthcoach.report.sections import SECTIONS, Section


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


def test_every_section_declares_which_findings_it_stands_on():
    """Раздел без привязки к находкам нечем обосновать перед коучем."""
    for section in SECTIONS:
        assert isinstance(section.kinds, tuple)
