from dataclasses import replace
from datetime import date
from pathlib import Path

import pytest

from healthcoach.knowledge.specialists import load_specialists
from healthcoach.llm.provider import LLMError
from healthcoach.report.draft import DraftError, generate_draft
from healthcoach.report.sections import SECTIONS
from healthcoach.scoring.findings import Finding
from healthcoach.scoring.references import Subject
from healthcoach.storage.clients import Client

SPECIALISTS = Path(__file__).parents[2] / "knowledge" / "specialists.yaml"

CLIENT = Client(
    code="CL-0001",
    full_name="Соловьёва Ирина Анатольевна",
    sex="ж",
    birth_date=date(1985, 3, 24),
    contacts=None,
    note=None,
)

ANALYTE = Finding(
    kind="показатель", subject_id="ферритин", title="Ферритин", value=18.0,
    units="нг/мл", status="дефицит", target=None, lab_range=None, note=None,
    rule_missing=False,
)
QUESTIONNAIRE = Finding(
    kind="опросник", subject_id="obraz_zizni/весь", title="ОБРАЗ ЖИЗНИ", value=8,
    units="баллов", status="высокая", target=None, lab_range=None, note=None,
    rule_missing=False,
)


class FakeProvider:
    """Провайдер, отдающий заранее известные ответы и запоминающий запросы."""

    def __init__(self, answers=None, fail_on=None):
        self.answers = answers or {}
        self.fail_on = fail_on
        self.prompts = []

    def complete(self, prompt: str) -> str:
        self.prompts.append(prompt)
        if self.fail_on is not None and self.fail_on in prompt:
            raise LLMError("модель недоступна")
        for key, answer in self.answers.items():
            if key in prompt:
                return answer
        return "Текст раздела."


def _specialties():
    return load_specialists(SPECIALISTS).public_view()


def test_every_section_is_generated():
    provider = FakeProvider()
    sections = generate_draft(
        provider, [ANALYTE, QUESTIONNAIRE], Subject(sex="ж", age=39), "",
        _specialties(), CLIENT,
    )
    assert [s.section_id for s in sections] == [s.id for s in SECTIONS]
    assert len(provider.prompts) == len(SECTIONS)


def test_section_carries_the_findings_it_stands_on():
    provider = FakeProvider()
    sections = generate_draft(
        provider, [ANALYTE, QUESTIONNAIRE], Subject(sex="ж", age=39), "",
        _specialties(), CLIENT,
    )
    by_id = {s.section_id: s for s in sections}
    assert "показатель/ферритин" in by_id["показатели"].finding_ids
    assert "опросник/obraz_zizni/весь" in by_id["карта_систем"].finding_ids


def test_a_section_does_not_claim_findings_of_another_kind():
    provider = FakeProvider()
    sections = generate_draft(
        provider, [ANALYTE, QUESTIONNAIRE], Subject(sex="ж", age=39), "",
        _specialties(), CLIENT,
    )
    by_id = {s.section_id: s for s in sections}
    assert "опросник/obraz_zizni/весь" not in by_id["показатели"].finding_ids


def test_findings_reach_every_prompt():
    """Модель трактует находки, а не додумывает — они должны быть в каждом запросе."""
    provider = FakeProvider()
    generate_draft(
        provider, [ANALYTE], Subject(sex="ж", age=39), "", _specialties(), CLIENT,
    )
    for prompt in provider.prompts:
        assert "Ферритин" in prompt


def test_model_failure_stops_the_draft_and_names_the_section():
    """Половина черновика молча — хуже, чем отказ: коуч решит, что это всё.

    Раздел взят из середины порядка («врачи», 5-й из 8), чтобы «после него
    вызовов не было» было содержательным утверждением, а не совпадением
    из-за того, что упавший раздел был последним.
    """
    order = [s.id for s in SECTIONS]
    failing_index = order.index("врачи")
    failing_section = SECTIONS[failing_index]
    provider = FakeProvider(fail_on=failing_section.title)

    with pytest.raises(DraftError, match="врачи"):
        generate_draft(
            provider, [ANALYTE], Subject(sex="ж", age=39), "", _specialties(), CLIENT,
        )

    # Вызван провайдер ровно для разделов до отказавшего включительно —
    # ни одним больше, ни одним меньше.
    assert len(provider.prompts) == failing_index + 1
    for later_section in SECTIONS[failing_index + 1 :]:
        for prompt in provider.prompts:
            assert later_section.title not in prompt


def test_the_request_section_stands_on_no_findings():
    """«Запрос» пересказывает цели клиента и не трактует ни одной находки —
    привязывать его ко всем находкам было бы нечем обосновать."""
    provider = FakeProvider()
    sections = generate_draft(
        provider, [ANALYTE, QUESTIONNAIRE], Subject(sex="ж", age=39), "",
        _specialties(), CLIENT,
    )
    by_id = {s.section_id: s for s in sections}
    assert by_id["запрос"].finding_ids == ()


def test_doctors_section_stands_on_every_kind_of_finding():
    provider = FakeProvider()
    sections = generate_draft(
        provider, [ANALYTE, QUESTIONNAIRE], Subject(sex="ж", age=39), "",
        _specialties(), CLIENT,
    )
    by_id = {s.section_id: s for s in sections}
    assert "показатель/ферритин" in by_id["врачи"].finding_ids
    assert "опросник/obraz_zizni/весь" in by_id["врачи"].finding_ids


def test_key_indicators_section_carries_only_the_analyte_finding():
    provider = FakeProvider()
    sections = generate_draft(
        provider, [ANALYTE, QUESTIONNAIRE], Subject(sex="ж", age=39), "",
        _specialties(), CLIENT,
    )
    by_id = {s.section_id: s for s in sections}
    assert by_id["показатели"].finding_ids == ("показатель/ферритин",)


# План, задача 6: если отчёт охватывает несколько дат, модель предупреждена
# об этом один раз в общем контексте, а не за находку и не за раздел.


def test_prompt_warns_once_when_findings_span_several_dates():
    provider = FakeProvider()
    early = replace(ANALYTE, taken_on=date(2026, 3, 10))
    late = replace(
        ANALYTE, subject_id="ттг", title="ТТГ", taken_on=date(2026, 8, 1)
    )
    generate_draft(
        provider, [early, late], Subject(sex="ж", age=39), "", _specialties(), CLIENT,
    )
    assert provider.prompts
    for prompt in provider.prompts:
        assert "разных дат" in prompt


def test_prompt_has_no_warning_when_every_dated_finding_shares_one_date():
    provider = FakeProvider()
    same_a = replace(ANALYTE, taken_on=date(2026, 8, 1))
    same_b = replace(
        ANALYTE, subject_id="ттг", title="ТТГ", taken_on=date(2026, 8, 1)
    )
    generate_draft(
        provider, [same_a, same_b], Subject(sex="ж", age=39), "", _specialties(), CLIENT,
    )
    for prompt in provider.prompts:
        assert "разных дат" not in prompt


def test_prompt_has_no_warning_when_findings_carry_no_date():
    """Находки без даты (обратная совместимость до задачи 6) не должны
    внезапно обзавестись предупреждением, которого не было ни разу."""
    provider = FakeProvider()
    generate_draft(
        provider, [ANALYTE, QUESTIONNAIRE], Subject(sex="ж", age=39), "",
        _specialties(), CLIENT,
    )
    for prompt in provider.prompts:
        assert "разных дат" not in prompt


def test_request_that_names_the_client_never_reaches_the_model():
    from healthcoach.privacy.leak import LeakError

    provider = FakeProvider()
    with pytest.raises(LeakError):
        generate_draft(
            provider, [ANALYTE], Subject(sex="ж", age=39),
            "Соловьёва жалуется на усталость", _specialties(), CLIENT,
        )
    assert provider.prompts == []
