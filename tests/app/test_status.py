from datetime import date, datetime
from pathlib import Path

import pytest

from healthcoach.app.status import client_overview, snapshot_steps
from healthcoach.storage.clients import ClientRepository
from healthcoach.storage.db import open_database
from healthcoach.storage.drafts import DraftRepository
from healthcoach.storage.requests import RequestRepository
from healthcoach.storage.snapshots import SnapshotRepository


class Repos:
    def __init__(self, c):
        self.clients = ClientRepository(c)
        self.snapshots = SnapshotRepository(c)
        self.drafts = DraftRepository(c)
        self.requests = RequestRepository(c)


@pytest.fixture
def repo(tmp_path):
    c = open_database(tmp_path / "db.sqlite")
    yield Repos(c)
    c.close()


def _client(repo):
    return repo.clients.add("Соловьёва Ирина", "ж", date(1985, 3, 24))


def test_incomplete_card_is_the_only_badge(repo):
    client = _client(repo)
    import sqlite3
    repo.clients._connection.execute(
        "UPDATE identities SET sex='', birth_date='' WHERE code=?", (client.code,)
    )
    repo.clients._connection.commit()
    over = client_overview(repo, repo.clients.get(client.code))
    assert [b.kind for b in over.badges] == ["bad"]


def test_incomplete_card_still_reports_latest_snapshot(repo):
    client = _client(repo)
    import sqlite3
    repo.clients._connection.execute(
        "UPDATE identities SET sex='', birth_date='' WHERE code=?", (client.code,)
    )
    repo.clients._connection.commit()
    repo.snapshots.create(client.code, date(2026, 9, 1))
    over = client_overview(repo, repo.clients.get(client.code))
    assert over.latest_taken_on == date(2026, 9, 1)
    assert [b.kind for b in over.badges] == ["bad"]


def test_no_snapshots_says_so(repo):
    over = client_overview(repo, _client(repo))
    assert over.latest_taken_on is None
    assert [b.text for b in over.badges] == ["нет срезов"]


def test_unverified_measurements_are_counted(repo):
    client = _client(repo)
    s = repo.snapshots.create(client.code, date(2026, 9, 1))
    a = repo.snapshots.add_measurement(s.id, "ферритин", "Ферритин", 18.0, "18", "нг/мл", date(2026, 8, 20))
    repo.snapshots.add_measurement(s.id, "", "Калий", 4.2, "4.2", "ммоль/л", date(2026, 8, 20))
    repo.snapshots.confirm_measurement(a.id, s.id)
    over = client_overview(repo, client)
    assert over.latest_taken_on == date(2026, 9, 1)
    assert any(b.text == "не сверено: 1" and b.kind == "warn" for b in over.badges)


def test_badges_come_from_the_latest_snapshot_only(repo):
    client = _client(repo)
    old = repo.snapshots.create(client.code, date(2026, 3, 1))
    repo.snapshots.add_measurement(old.id, "ферритин", "Ферритин", 18.0, "18", "нг/мл", date(2026, 2, 20))
    fresh = repo.snapshots.create(client.code, date(2026, 9, 1))
    repo.drafts.save_section(fresh.id, "запрос", "Текст", ())
    repo.drafts.approve(fresh.id, datetime(2026, 9, 2))
    over = client_overview(repo, client)
    assert [b.text for b in over.badges] == ["отчёт готов"]


def test_draft_waiting_for_approval(repo):
    client = _client(repo)
    s = repo.snapshots.create(client.code, date(2026, 9, 1))
    repo.drafts.save_section(s.id, "запрос", "Текст", ())
    over = client_overview(repo, client)
    assert any(b.text == "черновик ждёт утверждения" for b in over.badges)


def test_empty_snapshot_awaits_client_data(repo):
    client = _client(repo)
    repo.snapshots.create(client.code, date(2026, 9, 1))
    over = client_overview(repo, client)
    assert [b.text for b in over.badges] == ["ожидаем данные клиента"]


def test_steps_are_always_five_in_order(repo):
    client = _client(repo)
    s = repo.snapshots.create(client.code, date(2026, 9, 1))
    steps = snapshot_steps(repo, s.id)
    assert [st.title for st in steps] == ["Анкета", "Показатели", "Запрос", "Черновик", "PDF"]
    assert all(st.state == "todo" for st in steps)


def test_partially_verified_measurements_are_a_part_step(repo):
    client = _client(repo)
    s = repo.snapshots.create(client.code, date(2026, 9, 1))
    a = repo.snapshots.add_measurement(s.id, "ферритин", "Ферритин", 18.0, "18", "нг/мл", date(2026, 8, 20))
    repo.snapshots.add_measurement(s.id, "", "Калий", 4.2, "4.2", "ммоль/л", date(2026, 8, 20))
    repo.snapshots.confirm_measurement(a.id, s.id)
    step = snapshot_steps(repo, s.id)[1]
    assert step.state == "part"
    assert step.detail == "сверено 1 из 2"
    assert step.anchor == "#показатели"


def test_pdf_step_is_done_only_after_approval(repo):
    client = _client(repo)
    s = repo.snapshots.create(client.code, date(2026, 9, 1))
    repo.drafts.save_section(s.id, "запрос", "Текст", ())
    assert snapshot_steps(repo, s.id)[4].state == "todo"
    repo.drafts.approve(s.id, datetime(2026, 9, 2))
    steps = snapshot_steps(repo, s.id)
    assert steps[3].state == "done"
    assert steps[4].state == "done"


def test_request_states(repo):
    client = _client(repo)
    s = repo.snapshots.create(client.code, date(2026, 9, 1))
    repo.requests.save(s.id, "Устал")
    assert snapshot_steps(repo, s.id)[2].detail == "не вычитан"
    repo.requests.set_redacted(s.id, "Устал")
    assert snapshot_steps(repo, s.id)[2].detail == "вычитан, не утверждён"
    repo.requests.approve(s.id)
    assert snapshot_steps(repo, s.id)[2].state == "done"
