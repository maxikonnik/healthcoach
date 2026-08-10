"""Вход интерпретации по набору срезов, а не по одному.

Отчёт по-прежнему принадлежит одному срезу — самому свежему из выбранных.
Этот модуль отвечает только за то, что попадает интерпретации на вход:
измерения и анкету он собирает со всего набора (`repo.scopes.members`), а
не с одного среза. Срез без сохранённого набора отдаёт `[snapshot_id]`
(правило 7 плана) — поэтому для сегодняшних срезов, где набор никто не
сохранял, результат совпадает с тем, что было до этой задачи.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from healthcoach.storage.snapshots import Answers, Snapshot, StoredMeasurement


@dataclass(frozen=True)
class ScopedInputs:
    measurements: tuple[StoredMeasurement, ...]
    """Свёрнутые сверенные измерения, по одному на распознанный показатель;
    нераспознанные (`analyte_id` пуст) идут по одному на строку — правило 2
    запрещает их сворачивать между собой."""
    answers: Answers
    answers_from: int | None
    """id среза, чья анкета взята; None — анкеты нет ни в одном срезе набора."""
    member_ids: tuple[int, ...]
    """Весь набор, по возрастанию даты среза."""
    dates: tuple[date, ...]
    """Различные даты вошедших измерений, по возрастанию, без повторов."""


def collect_inputs(repo, snapshot: Snapshot) -> ScopedInputs:
    """Собрать сверенные измерения и анкету по набору срезов владеющего среза.

    Свёртка (правило 1) сравнивает измерения одного показателя по ключу
    `(taken_on, id)` самого измерения — не среза, который его несёт: дата
    забора в бланке не обязана совпадать с датой среза, а `id` разрешает
    спор двух измерений одной даты в пользу более позднего ввода.
    """
    members = sorted(
        (repo.snapshots.get(member_id) for member_id in repo.scopes.members(snapshot.id)),
        key=lambda s: (s.taken_on, s.id),
    )

    latest_by_analyte: dict[str, StoredMeasurement] = {}
    unrecognised: list[StoredMeasurement] = []
    for member in members:
        for measurement in repo.snapshots.measurements(member.id):
            if not measurement.confirmed:
                continue
            if not measurement.analyte_id:
                # Правило 2: без распознанного показателя сворачивать не с
                # чем и не с кем — каждая строка идёт в находки отдельно.
                unrecognised.append(measurement)
                continue
            current = latest_by_analyte.get(measurement.analyte_id)
            key = (measurement.taken_on, measurement.id)
            if current is None or key > (current.taken_on, current.id):
                latest_by_analyte[measurement.analyte_id] = measurement
    measurements = tuple(latest_by_analyte.values()) + tuple(unrecognised)

    answers: Answers = {}
    answers_from: int | None = None
    for member in reversed(members):
        # Правило 3: анкета не объединяется — берётся целиком анкета самого
        # свежего среза, где она заполнена.
        candidate = repo.snapshots.answers(member.id)
        if candidate:
            answers = candidate
            answers_from = member.id
            break

    dates = tuple(sorted({measurement.taken_on for measurement in measurements}))

    return ScopedInputs(
        measurements=measurements,
        answers=answers,
        answers_from=answers_from,
        member_ids=tuple(member.id for member in members),
        dates=dates,
    )
