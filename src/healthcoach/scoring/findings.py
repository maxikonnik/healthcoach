"""Единый список находок — вход для интерпретации."""

from __future__ import annotations

from dataclasses import dataclass

from healthcoach.knowledge.degrees import degree_rank
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
    STATUS_BELOW: 1,
    STATUS_ABOVE: 1,
    STATUS_WITHIN: 3,
    STATUS_NORMAL: 3,
    STATUS_UNIT_MISMATCH: 4,
    STATUS_NOT_COMPUTED: 4,
    STATUS_NO_RULE: 5,
}

_SEVERITY_BY_DEGREE_RANK = (3, 2, 1, 1, 1, 1, 0, 0, 0, 0, 0)
"""Тяжесть по позиции степени в DEGREE_ORDER: 0 — требует внимания, 3 — норма."""

_SEVERITY_UNKNOWN = 1
"""Незнакомый статус не прячется среди нормальных находок."""


def _severity(status: str) -> int:
    """Тяжесть статуса: у степеней она берётся из общего словаря."""
    known = _SEVERITY.get(status)
    if known is not None:
        return known
    rank = degree_rank(status)
    if rank is not None:
        return _SEVERITY_BY_DEGREE_RANK[rank]
    return _SEVERITY_UNKNOWN


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

    findings.sort(key=lambda f: (_severity(f.status), f.kind, f.title))
    return findings
