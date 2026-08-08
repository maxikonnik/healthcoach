from pathlib import Path

from healthcoach.knowledge.questionnaire import (
    Block,
    Question,
    Questionnaire,
    ScaleOption,
    Subscale,
    Threshold,
)
from healthcoach.knowledge.references import load_references
from healthcoach.scoring.findings import collect_findings
from healthcoach.scoring.references import Measurement, Subject

REFS = Path(__file__).parents[2] / "knowledge" / "references"

SCALE = (ScaleOption(0, "нет"), ScaleOption(1, "иногда"), ScaleOption(2, "часто"))


def _questionnaire() -> Questionnaire:
    questions = tuple(
        Question(
            id=f"nadpochechniki.{i}",
            number=i,
            text=f"Симптом {i}",
            scale=None,
            block_scale=SCALE,
        )
        for i in range(1, 4)
    )
    block = Block(
        id="nadpochechniki",
        title="Надпочечники",
        part="клиническая",
        core=True,
        scale=SCALE,
        questions=questions,
        subscales=(
            Subscale(
                id="весь",
                title="Весь блок",
                question_ids=tuple(q.id for q in questions),
                thresholds=(
                    Threshold("низкая", 1, 2, None),
                    Threshold("средняя", 3, 4, None),
                    Threshold("высокая", 5, None, None),
                ),
            ),
        ),
    )
    return Questionnaire(version="1.0", blocks=(block,))


SUBJECT = Subject(sex="ж", age=32, cycle_phase=None)


def test_collects_all_three_kinds():
    findings = collect_findings(
        _questionnaire(),
        load_references(REFS),
        answers={f"nadpochechniki.{i}": 2 for i in range(1, 4)},
        measurements=[
            Measurement("ферритин", 18, "нг/мл"),
            Measurement("кальций", 10.0, "мг/дл"),
            Measurement("калий", 4.0, "ммоль/л"),
        ],
        subject=SUBJECT,
    )
    kinds = {f.kind for f in findings}
    assert kinds == {"показатель", "производный", "опросник"}


def test_questionnaire_finding_carries_degree_as_status():
    findings = collect_findings(
        _questionnaire(),
        load_references(REFS),
        answers={f"nadpochechniki.{i}": 2 for i in range(1, 4)},  # сумма 6
        measurements=[],
        subject=SUBJECT,
    )
    (finding,) = findings
    assert finding.kind == "опросник"
    assert finding.subject_id == "nadpochechniki/весь"
    assert finding.title == "Надпочечники"
    assert finding.status == "высокая"
    assert finding.value == 6


def test_severe_findings_come_first_and_unknown_last():
    findings = collect_findings(
        _questionnaire(),
        load_references(REFS),
        answers={f"nadpochechniki.{i}": 0 for i in range(1, 4)},  # норма
        measurements=[
            Measurement("гомоцистеин", 12, "мкмоль/л"),  # правило не задано
            Measurement("ферритин", 18, "нг/мл"),  # дефицит
            Measurement("кальций", 9.5, "мг/дл"),  # в целевом
            Measurement("калий", 4.2, "ммоль/л"),  # в целевом
        ],
        subject=SUBJECT,
    )
    statuses = [f.status for f in findings]
    assert statuses[0] == "дефицит"
    assert statuses[-1] == "правило не задано"
    assert "в пределах нормы" in statuses  # находка опросника не потерялась


def test_questionnaire_without_degree_still_reported():
    findings = collect_findings(
        _questionnaire(),
        load_references(REFS),
        answers={"nadpochechniki.1": 0, "nadpochechniki.2": 0, "nadpochechniki.3": 0},
        measurements=[],
        subject=SUBJECT,
    )
    (finding,) = findings
    assert finding.status == "в пределах нормы"
    assert finding.value == 0
