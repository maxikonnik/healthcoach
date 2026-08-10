"""Единый список находок — вход для интерпретации."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date

from healthcoach.knowledge.degrees import degree_severity
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
    STATUS_NO_VALUE,
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
STATUS_UNSCORED = "степень не выставлена"

_SEVERITY = {
    STATUS_DEFICIT: 0,
    STATUS_EXCESS: 0,
    STATUS_BELOW: 1,
    STATUS_ABOVE: 1,
    STATUS_WITHIN: 3,
    STATUS_NORMAL: 3,
    STATUS_UNIT_MISMATCH: 4,
    STATUS_NOT_COMPUTED: 4,
    STATUS_UNSCORED: 4,
    STATUS_NO_VALUE: 4,
    STATUS_NO_RULE: 5,
}

_SEVERITY_UNKNOWN = 1
"""Незнакомый статус не прячется среди нормальных находок."""


def _severity(status: str) -> int:
    """Тяжесть статуса: у степеней она берётся из общего словаря."""
    known = _SEVERITY.get(status)
    if known is not None:
        return known
    from_degree = degree_severity(status)
    if from_degree is not None:
        return from_degree
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
    answered: int | None = None
    """Сколько вопросов подгруппы клиент заполнил. None у показателей."""
    total: int | None = None
    row_id: int | None = None
    """Строка измерения в срезе — различает находки с пустым subject_id."""
    title_from_document: bool = False
    """title списан с бланка клиента, а не взят из базы знаний коуча."""
    units_from_document: bool = False
    """units — написание из бланка, а не объявленные единицы показателя."""
    note_private: bool = False
    """note — заметка коуча из базы знаний: наружу не идёт (см. AnalyteVerdict)."""
    taken_on: date | None = None
    """Дата измерения, из которого получилась находка. `None` у опросника и
    там, где вход не несёт своей даты (обратная совместимость с вызовами до
    многосрезового отчёта)."""

    @property
    def partial(self) -> bool:
        """Степень выставлена не по всем вопросам подгруппы.

        Пропущенный вопрос считается за ноль баллов, а больше баллов —
        хуже. Значит каждый пропуск смещает клиента в сторону здорового,
        и степень по неполным ответам мягче настоящей.
        """
        return (
            self.answered is not None
            and self.total is not None
            and self.answered < self.total
        )


def _from_verdict(
    verdict: AnalyteVerdict, kind: str, *, taken_on: date | None = None
) -> Finding:
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
        row_id=verdict.row_id,
        title_from_document=verdict.title_from_document,
        units_from_document=verdict.units_from_document,
        note_private=verdict.note_private,
        taken_on=taken_on,
    )


def collect_findings(
    questionnaire: Questionnaire,
    references: References,
    answers: Answers,
    measurements: list[Measurement],
    subject: Subject,
    subject_at: Callable[[date], Subject] | None = None,
) -> list[Finding]:
    """Собрать находки из опросника, показателей и производных в один список.

    `subject_at` — необязательный источник субъекта по дате измерения
    (правило 4): коридор каждого показателя выбирается по возрасту клиента
    на дату этого измерения, а не на дату отчёта. Вызовы без него ведут
    себя ровно как раньше — параметр по умолчанию `None`."""
    findings: list[Finding] = []

    for scored in score_questionnaire(questionnaire, answers, subject.sex):
        title = (
            scored.block_title
            if scored.subscale_id == "весь"
            else f"{scored.block_title} — {scored.subscale_title}"
        )
        if scored.degree is not None:
            status, note, rule_missing = scored.degree, None, False
        elif scored.degree_missing is None:
            status, note, rule_missing = STATUS_NORMAL, None, False
        else:
            status, note, rule_missing = (
                STATUS_UNSCORED,
                scored.degree_missing,
                True,
            )
        findings.append(
            Finding(
                kind=KIND_QUESTIONNAIRE,
                subject_id=f"{scored.block_id}/{scored.subscale_id}",
                title=title,
                value=scored.score,
                units="баллов",
                status=status,
                target=None,
                lab_range=None,
                note=note,
                rule_missing=rule_missing,
                answered=scored.answered,
                total=scored.total,
            )
        )

    verdicts = check_measurements(references, measurements, subject, subject_at)
    # check_measurements выдаёт ровно один вердикт на измерение, в том же
    # порядке — можно взять дату для находки прямо из входа, не расширяя
    # AnalyteVerdict полем, которое ему самому не нужно.
    for measurement, verdict in zip(measurements, verdicts):
        findings.append(_from_verdict(verdict, KIND_ANALYTE, taken_on=measurement.taken_on))

    for verdict in compute_derived(references, measurements):
        findings.append(_from_verdict(verdict, KIND_DERIVED))

    findings.sort(key=lambda f: (_severity(f.status), f.kind, f.title))
    return findings
