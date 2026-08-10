"""Состояние работы: плашки по клиенту и шаги по срезу.

Правила собраны в одном месте, потому что их читают два экрана:
рабочий стол ведёт ровно к тому шагу, который подсвечен на срезе.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from healthcoach.storage.clients import Client


@dataclass(frozen=True)
class Badge:
    kind: str
    text: str


@dataclass(frozen=True)
class Overview:
    latest_taken_on: date | None
    badges: tuple[Badge, ...]


@dataclass(frozen=True)
class Step:
    title: str
    state: str
    detail: str
    anchor: str


def client_overview(repo, client: Client) -> Overview:
    """Плашки клиента — по последнему срезу, плюс долг по прошлым."""
    snapshots = repo.snapshots.for_client(client.code)
    latest_taken_on = (
        max(snapshots, key=lambda s: (s.taken_on, s.id)).taken_on
        if snapshots
        else None
    )
    if not client.is_complete:
        return Overview(latest_taken_on, (Badge("bad", "карточка не заполнена"),))
    if not snapshots:
        return Overview(None, (Badge("muted", "нет срезов"),))
    latest = max(snapshots, key=lambda s: (s.taken_on, s.id))
    badges = list(_snapshot_badges(repo, latest.id))
    debt = _snapshots_with_unfinished_work(repo, client.code) - {latest.id}
    if debt:
        badges.append(Badge("warn", f"долг по прошлым срезам: {len(debt)}"))
    return Overview(latest.taken_on, tuple(badges))


def _snapshots_with_unfinished_work(repo, client_code: str) -> set[int]:
    """Срезы клиента с неподтверждённым измерением или черновиком без утверждения."""
    unverified = repo.snapshots.unverified_counts_by_snapshot(client_code)
    unapproved_drafts = repo.drafts.unapproved_snapshot_ids(client_code)
    return set(unverified) | set(unapproved_drafts)


def _snapshot_badges(repo, snapshot_id: int) -> tuple[Badge, ...]:
    badges: list[Badge] = []
    measurements = repo.snapshots.measurements(snapshot_id)
    answers = repo.snapshots.answers(snapshot_id)
    request = repo.requests.get(snapshot_id)
    unverified = sum(1 for m in measurements if not m.confirmed)
    if unverified:
        badges.append(Badge("warn", f"не сверено: {unverified}"))
    if request is not None and not request.approved:
        badges.append(Badge("warn", "запрос не утверждён"))
    if repo.drafts.approved_at(snapshot_id) is not None:
        badges.append(Badge("ok", "отчёт готов"))
    elif repo.drafts.sections(snapshot_id):
        badges.append(Badge("warn", "черновик ждёт утверждения"))
    if badges:
        return tuple(badges)
    if not measurements and not answers:
        return (Badge("muted", "ожидаем данные клиента"),)
    if request is None:
        return (Badge("muted", "нужен запрос клиента"),)
    return (Badge("muted", "черновик не собран"),)


def snapshot_steps(repo, snapshot_id: int) -> tuple[Step, ...]:
    """Пять шагов воронки среза, всегда в одном порядке."""
    answers = repo.snapshots.answers(snapshot_id)
    measurements = repo.snapshots.measurements(snapshot_id)
    confirmed = sum(1 for m in measurements if m.confirmed)
    request = repo.requests.get(snapshot_id)
    sections = repo.drafts.sections(snapshot_id)
    approved = repo.drafts.approved_at(snapshot_id) is not None
    draft_page = f"/snapshots/{snapshot_id}/draft"

    if answers:
        questionnaire = Step("Анкета", "done", f"ответов: {len(answers)}", "#анкета")
    else:
        questionnaire = Step("Анкета", "todo", "не загружена", "#анкета")

    total = len(measurements)
    if total and confirmed == total:
        indicators = Step("Показатели", "done", f"сверено: {total}", "#показатели")
    elif total:
        indicators = Step(
            "Показатели", "part", f"сверено {confirmed} из {total}", "#показатели"
        )
    else:
        indicators = Step("Показатели", "todo", "нет", "#показатели")

    if request is None:
        req = Step("Запрос", "todo", "не введён", draft_page)
    elif request.approved:
        req = Step("Запрос", "done", "утверждён", draft_page)
    elif request.redacted:
        req = Step("Запрос", "part", "вычитан, не утверждён", draft_page)
    else:
        req = Step("Запрос", "part", "не вычитан", draft_page)

    if approved:
        draft = Step("Черновик", "done", "утверждён", draft_page)
        pdf = Step("PDF", "done", "скачать", f"/snapshots/{snapshot_id}/report.pdf")
    elif sections:
        draft = Step("Черновик", "part", "ждёт утверждения", draft_page)
        pdf = Step("PDF", "todo", "после утверждения", draft_page)
    else:
        draft = Step("Черновик", "todo", "не собран", draft_page)
        pdf = Step("PDF", "todo", "после утверждения", draft_page)

    return (questionnaire, indicators, req, draft, pdf)
