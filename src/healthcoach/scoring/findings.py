"""Единый список находок — вход для интерпретации."""

from __future__ import annotations

from dataclasses import dataclass

from healthcoach.knowledge.questionnaire import Questionnaire
from healthcoach.knowledge.references import Interval, References
from healthcoach.scoring.derived import compute_derived
from healthcoach.scoring.questionnaire import Answers, score_questionnaire
from healthcoach.scoring.references import (
    STATUS_ABOVE,
    STATUS_BELOW,
    STATUS_DEFICIT,
    STATUS_EXCESS,
    STATUS_NOT_COMPUTED,
    STATUS_NO_RULE,
    STATUS_UNIT_MISMATCH,
    STATUS_WITHIN,
    AnalyteVerdict,
    Measurement,
    Subject,
    check_measurements,
)

KIND_ANALYTE = "показатель"
KIND_DERIVED = "производный"
KIND_QUESTIONNAIRE = "опросник"

STATUS_NORMAL = "в пределах нормы"

_SEVERITY = {
    STATUS_DEFICIT: 0,
    STATUS_EXCESS: 0,
    "высокая": 0,
    "тяжёлая": 0,
    "очень тяжёлая": 0,
    STATUS_BELOW: 1,
    STATUS_ABOVE: 1,
    "средняя": 1,
    "умеренная": 1,
    "низкая": 2,
    STATUS_WITHIN: 3,
    STATUS_NORMAL: 3,
    STATUS_UNIT_MISMATCH: 4,
    STATUS_NOT_COMPUTED: 4,
    STATUS_NO_RULE: 5,
}


@dataclass(frozen=True)
class Finding:
    kind: str
    subject_id: str
    title: str
    value: float | None
    units: str
    status: str
    target: Interval | None
    lab_range: Interval | None
    note: str | None
    rule_missing: bool


def _from_verdict(verdict: AnalyteVerdict, kind: str) -> Finding:
    return Finding(
        kind=kind,
        subject_id=verdict.analyte_id,
        title=verdict.title,
        value=verdict.value,
        units=verdict.units,
        status=verdict.status,
        target=verdict.target,
        lab_range=verdict.lab_range,
        note=verdict.note,
        rule_missing=verdict.rule_missing,
    )


def collect_findings(
    questionnaire: Questionnaire,
    references: References,
    answers: Answers,
    measurements: list[Measurement],
    subject: Subject,
) -> list[Finding]:
    """Собрать находки из опросника, показателей и производных в один список."""
    findings: list[Finding] = []

    for scored in score_questionnaire(questionnaire, answers, subject.sex):
        title = (
            scored.block_title
            if scored.subscale_id == "весь"
            else f"{scored.block_title} — {scored.subscale_title}"
        )
        findings.append(
            Finding(
                kind=KIND_QUESTIONNAIRE,
                subject_id=f"{scored.block_id}/{scored.subscale_id}",
                title=title,
                value=scored.score,
                units="баллов",
                status=scored.degree or STATUS_NORMAL,
                target=None,
                lab_range=None,
                note=(
                    None
                    if scored.answered == scored.total
                    else f"отвечено {scored.answered} из {scored.total} вопросов"
                ),
                rule_missing=False,
            )
        )

    for verdict in check_measurements(references, measurements, subject):
        findings.append(_from_verdict(verdict, KIND_ANALYTE))

    for verdict in compute_derived(references, measurements):
        findings.append(_from_verdict(verdict, KIND_DERIVED))

    findings.sort(key=lambda f: (_SEVERITY.get(f.status, 3), f.kind, f.title))
    return findings
