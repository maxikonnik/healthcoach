"""Всё, что нужно клиентскому отчёту, в одном объекте.

Шаблон не ходит в базу: он получает готовое и только раскладывает. Так
вёрстку можно править, не боясь сломать выборку, а выборку проверить
тестом без единой строки HTML.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime

from healthcoach.knowledge.coach import Coach
from healthcoach.knowledge.references import Interval, References
from healthcoach.knowledge.questionnaire import Questionnaire
from healthcoach.scoring.findings import Finding, collect_findings
from healthcoach.scoring.references import Measurement, Subject, select_target
from healthcoach.storage.drafts import DraftSection


class ReportError(Exception):
    """Отчёт собрать нельзя."""


@dataclass(frozen=True)
class Point:
    taken_on: date
    value: float


@dataclass(frozen=True)
class Series:
    analyte_id: str
    title: str
    units: str
    points: tuple[Point, ...]
    target: Interval | None

    @property
    def has_dynamics(self) -> bool:
        """Динамика начинается со второго измерения.

        Одна точка — это первое измерение, а не динамика. Рисовать по ней
        график значит показать клиенту линию, которой нет.
        """
        return len(self.points) > 1


@dataclass(frozen=True)
class ReportData:
    client_name: str
    client_code: str
    taken_on: date
    coach: Coach
    sections: tuple[DraftSection, ...]
    findings: tuple[Finding, ...]
    series: tuple[Series, ...]
    approved_at: datetime


def collect_report(
    repo,
    questionnaire: Questionnaire,
    references: References,
    coach: Coach,
    snapshot_id: int,
) -> ReportData:
    """Собрать данные отчёта по утверждённому черновику среза."""
    snapshot = repo.snapshots.get(snapshot_id)
    if snapshot is None:
        raise ReportError(f"нет среза {snapshot_id}")

    approved_at = repo.drafts.approved_at(snapshot_id)
    if approved_at is None:
        raise ReportError(
            f"черновик среза {snapshot_id} не утверждён — клиенту его отдавать нельзя"
        )

    client = repo.clients.get(snapshot.client_code)
    if client is None:
        raise ReportError(f"нет клиента {snapshot.client_code}")
    if not client.is_complete:
        raise ReportError(
            f"карточка клиента {client.code} не заполнена: без пола и даты "
            f"рождения целевой коридор не выбрать"
        )

    confirmed = [m for m in repo.snapshots.measurements(snapshot_id) if m.confirmed]
    subject = Subject(sex=client.sex, age=client.age_on(snapshot.taken_on))
    findings = collect_findings(
        questionnaire,
        references,
        repo.snapshots.answers(snapshot_id),
        [
            Measurement(m.analyte_id, m.value, m.units, label=m.raw_name, row_id=m.id)
            for m in confirmed
        ],
        subject,
    )

    return ReportData(
        client_name=client.full_name,
        client_code=client.code,
        taken_on=snapshot.taken_on,
        coach=coach,
        sections=tuple(repo.drafts.sections(snapshot_id)),
        findings=tuple(findings),
        series=_series(repo, references, subject, client.code, confirmed),
        approved_at=approved_at,
    )


def _series(repo, references, subject, client_code, confirmed) -> tuple[Series, ...]:
    """Ряды динамики по показателям этого среза.

    В ряд идут только сверенные измерения: клиент не должен увидеть точку,
    которую коуч не проверил.
    """
    result: list[Series] = []
    for analyte_id in dict.fromkeys(m.analyte_id for m in confirmed if m.analyte_id):
        analyte = references.analyte(analyte_id)
        if analyte is None:
            continue
        points = tuple(
            Point(taken_on=m.taken_on, value=m.value)
            for m in repo.snapshots.history(client_code, analyte_id)
            if m.confirmed and m.value is not None
        )
        if not points:
            continue
        chosen = select_target(analyte, subject)
        result.append(
            Series(
                analyte_id=analyte_id,
                title=analyte.name,
                units=analyte.units,
                points=points,
                target=chosen.optimal if chosen is not None else None,
            )
        )
    return tuple(result)
