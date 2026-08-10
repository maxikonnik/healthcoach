"""Всё, что нужно клиентскому отчёту, в одном объекте.

Шаблон не ходит в базу: он получает готовое и только раскладывает. Так
вёрстку можно править, не боясь сломать выборку, а выборку проверить
тестом без единой строки HTML.

`ReportData` безопасен по построению: всё, что в нём лежит, можно
напечатать клиенту. Держится это одним местом — `privacy.safe_finding`,
через которую здесь проходит каждая находка, и тем же предикатом единиц,
которым сверка решает, можно ли об измерении судить. Печатать что-то из
`ReportData` можно, не перечитывая, откуда взялся текст.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime

from healthcoach.knowledge.coach import Coach
from healthcoach.knowledge.references import Interval, References
from healthcoach.knowledge.questionnaire import Questionnaire
from healthcoach.knowledge.units import units_match
from healthcoach.privacy.findings import FOR_CLIENT, safe_finding
from healthcoach.report.scope import build_subject_at, collect_inputs, to_measurements
from healthcoach.scoring.findings import Finding, collect_findings
from healthcoach.scoring.references import select_target
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
        """Динамика появляется начиная со второго среза.

        Одна точка — это точка отсчёта, а не динамика. Рисовать по ней
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

    scoped = collect_inputs(repo, snapshot)
    subject_at = build_subject_at(client)
    subject = subject_at(snapshot.taken_on)
    findings = collect_findings(
        questionnaire,
        references,
        scoped.answers,
        to_measurements(scoped.measurements),
        subject,
        subject_at=subject_at,
    )

    return ReportData(
        client_name=client.full_name,
        client_code=client.code,
        taken_on=snapshot.taken_on,
        coach=coach,
        sections=tuple(repo.drafts.sections(snapshot_id)),
        # Маска ставится здесь, на границе сборки отчёта, а не в шаблоне —
        # чтобы всё, что построено на `ReportData`, было безопасно по
        # построению, а не по памяти о том, что title, units и note иногда
        # бывают чужим текстом. Правило одно на два пути наружу и живёт в
        # `privacy/findings.py`.
        findings=tuple(safe_finding(f, audience=FOR_CLIENT) for f in findings),
        series=_series(
            repo, references, subject, client.code, snapshot.taken_on, scoped.measurements
        ),
        approved_at=approved_at,
    )


def _series(
    repo, references, subject, client_code, taken_on: date, measurements
) -> tuple[Series, ...]:
    """Ряды динамики по показателям свода (`report.scope.collect_inputs`).

    Список показателей берётся из всего набора срезов, а не только из
    первичного, — график может появиться для показателя, которого в
    первичном срезе нет вовсе. Верхняя граница истории (`taken_on`) при
    этом не меняется: она остаётся датой первичного среза, а не самой
    свежей датой набора.

    Три условия, и каждое отсекает точку, которой на графике быть не должно.

    Сверенность: клиент не должен увидеть точку, которую коуч не проверил.

    Дата забора не позже даты среза: отчёт печатается по срезу, и коуч
    может напечатать его заново через полгода. Без верхней границы график
    в мартовском отчёте дотягивался бы до сентябрьского забора — и спорил
    бы с собственным текстом: находки собираются по одному срезу, модели
    сказали «это точка отсчёта», а рядом нарисована линия.

    Единицы: `units_match` — тот же предикат, которым сверка решает,
    можно ли вообще судить об измерении. Если единицы с референсом не
    сопоставлены, вердикт отказывается судить («единицы не сопоставлены»,
    без целевого коридора) — а точка на графике судила бы: её отложили бы
    по оси, подписанной единицами из базы знаний, и сравнили с коридором.
    2.4 мг/дл калия (это около 0.61 ммоль/л) нарисовались бы падением с
    4.2 ммоль/л под нижнюю границу коридора — падением, которого не было.
    Отдельного сравнения здесь нет намеренно: две копии одного правила уже
    расходились в этом проекте.
    """
    result: list[Series] = []
    for analyte_id in dict.fromkeys(m.analyte_id for m in measurements if m.analyte_id):
        analyte = references.analyte(analyte_id)
        if analyte is None:
            continue
        points = tuple(
            Point(taken_on=m.taken_on, value=m.value)
            for m in repo.snapshots.history(client_code, analyte_id)
            if m.confirmed
            and m.value is not None
            and m.taken_on <= taken_on
            and units_match(analyte, m.units)
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
