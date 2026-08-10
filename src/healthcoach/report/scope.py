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

    Свёртка (правило 1) применяется «среди выбранных срезов» — то есть
    только между измерениями из *разных* срезов набора. Внутри одного
    среза два бланка одного показателя (например, два отдельных забора,
    внесённые за один визит) — не повтор одного и того же среза, а
    нормальная запись; свёртка их не трогает, обе строки идут в находки.

    Реализовано в два прохода. Сначала измерения группируются по
    `(analyte_id, snapshot_id, taken_on)`: это ловит только буквальный
    дубль — одна и та же дата забора, тот же срез, — где выживает более
    поздний ввод (`id`). Затем среди срезов, где показатель вообще
    встретился, выбирается один «победивший» — тот, что несёт самое
    свежее по `(taken_on, id)` измерение этого показателя; из него в
    находки идут все его даты забора, а измерения показателя из
    остальных срезов отбрасываются целиком — они уже видны в динамике.
    """
    members = sorted(
        (repo.snapshots.get(member_id) for member_id in repo.scopes.members(snapshot.id)),
        key=lambda s: (s.taken_on, s.id),
    )

    by_draw: dict[tuple[str, int, date], StoredMeasurement] = {}
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
            draw_key = (measurement.analyte_id, measurement.snapshot_id, measurement.taken_on)
            current = by_draw.get(draw_key)
            if current is None or measurement.id > current.id:
                by_draw[draw_key] = measurement

    winning_snapshot: dict[str, tuple[tuple[date, int], int]] = {}
    for (analyte_id, member_id, _taken_on), measurement in by_draw.items():
        rep_key = (measurement.taken_on, measurement.id)
        best = winning_snapshot.get(analyte_id)
        if best is None or rep_key > best[0]:
            winning_snapshot[analyte_id] = (rep_key, member_id)

    measurements = tuple(
        measurement
        for (analyte_id, member_id, _taken_on), measurement in by_draw.items()
        if winning_snapshot[analyte_id][1] == member_id
    ) + tuple(unrecognised)

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
