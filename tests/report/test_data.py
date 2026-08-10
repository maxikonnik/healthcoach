from datetime import date, datetime
from pathlib import Path

import pytest

from healthcoach.knowledge.coach import Coach
from healthcoach.knowledge.questionnaire import load_questionnaire
from healthcoach.knowledge.references import load_references
from healthcoach.report.data import ReportError, collect_report
from healthcoach.storage.clients import ClientRepository
from healthcoach.storage.db import open_database
from healthcoach.storage.drafts import DraftRepository
from healthcoach.storage.snapshots import SnapshotRepository

REFS = Path(__file__).parents[2] / "knowledge" / "references"
SPEC = Path(__file__).parents[2] / "knowledge" / "questionnaire.yaml"
COACH = Coach(name="Иконникова Екатерина", title="нутрициолог", signature="")


@pytest.fixture(scope="module")
def knowledge():
    return load_questionnaire(SPEC), load_references(REFS)


def _collect(repo, knowledge, snapshot_id):
    questionnaire, references = knowledge
    return collect_report(repo, questionnaire, references, COACH, snapshot_id)


class Repos:
    """Три хранилища на одном соединении — как их выдаёт Context.session()."""

    def __init__(self, connection):
        self.clients = ClientRepository(connection)
        self.snapshots = SnapshotRepository(connection)
        self.drafts = DraftRepository(connection)


@pytest.fixture
def repo(tmp_path):
    connection = open_database(tmp_path / "db.sqlite")
    yield Repos(connection)
    connection.close()


def _client_with_snapshot(repo, taken_on=date(2026, 9, 1)):
    client = repo.clients.add("Соловьёва Ирина", "ж", date(1985, 3, 24))
    snapshot = repo.snapshots.create(client.code, taken_on)
    return client, snapshot


def _approved_draft(repo, snapshot_id):
    repo.drafts.save_section(snapshot_id, "запрос", "Текст запроса.", ())
    repo.drafts.save_section(snapshot_id, "показатели", "Текст показателей.", ())
    repo.drafts.approve(snapshot_id, datetime(2026, 9, 2, 10, 0))


def test_report_carries_the_client_and_the_coach(repo, knowledge):
    _, snapshot = _client_with_snapshot(repo)
    _approved_draft(repo, snapshot.id)

    data = _collect(repo, knowledge, snapshot.id)

    assert data.client_name == "Соловьёва Ирина"
    assert data.client_code == "CL-0001"
    assert data.taken_on == date(2026, 9, 1)
    assert data.coach.name == "Иконникова Екатерина"
    assert data.approved_at == datetime(2026, 9, 2, 10, 0)


def test_sections_come_in_the_order_of_the_report(repo, knowledge):
    _, snapshot = _client_with_snapshot(repo)
    _approved_draft(repo, snapshot.id)

    data = _collect(repo, knowledge, snapshot.id)

    assert [s.section_id for s in data.sections] == ["запрос", "показатели"]


def test_section_takes_the_coach_edit_over_the_model_text(repo, knowledge):
    """В отчёт идёт то, что оставил коуч, а не то, что написала модель."""
    _, snapshot = _client_with_snapshot(repo)
    saved = repo.drafts.save_section(snapshot.id, "запрос", "Текст модели.", ())
    repo.drafts.edit_section(saved.id, snapshot.id, "Правка коуча.")
    repo.drafts.approve(snapshot.id, datetime(2026, 9, 2))

    data = _collect(repo, knowledge, snapshot.id)

    assert data.sections[0].text == "Правка коуча."


def test_unapproved_draft_is_refused(repo, knowledge):
    """Неутверждённый черновик клиенту не отдаётся ни при каких условиях."""
    _, snapshot = _client_with_snapshot(repo)
    repo.drafts.save_section(snapshot.id, "запрос", "Текст.", ())

    with pytest.raises(ReportError, match="не утверждён"):
        _collect(repo, knowledge, snapshot.id)


def test_missing_draft_is_refused(repo, knowledge):
    _, snapshot = _client_with_snapshot(repo)
    with pytest.raises(ReportError, match="не утверждён"):
        _collect(repo, knowledge, snapshot.id)


def test_unknown_snapshot_is_refused(repo, knowledge):
    with pytest.raises(ReportError, match="нет среза"):
        _collect(repo, knowledge, 99999)


def test_only_confirmed_measurements_reach_the_report(repo, knowledge):
    """Ворота сверки держатся и здесь: клиент видит только сверенное."""
    client, snapshot = _client_with_snapshot(repo)
    confirmed = repo.snapshots.add_measurement(
        snapshot.id, "ферритин", "Ферритин", 18.0, "18", "нг/мл", date(2026, 8, 20)
    )
    repo.snapshots.add_measurement(
        snapshot.id, "ферритин", "Ферритин", 999.0, "999", "нг/мл", date(2026, 8, 21)
    )
    repo.snapshots.confirm_measurement(confirmed.id, snapshot.id)
    _approved_draft(repo, snapshot.id)

    data = _collect(repo, knowledge, snapshot.id)

    values = [f.value for f in data.findings]
    assert 18.0 in values
    assert 999.0 not in values


def test_a_single_measurement_is_not_dynamics(repo, knowledge):
    """Одна точка — первое измерение, а не динамика: линии здесь нет."""
    client, snapshot = _client_with_snapshot(repo)
    stored = repo.snapshots.add_measurement(
        snapshot.id, "ферритин", "Ферритин", 18.0, "18", "нг/мл", date(2026, 8, 20)
    )
    repo.snapshots.confirm_measurement(stored.id, snapshot.id)
    _approved_draft(repo, snapshot.id)

    data = _collect(repo, knowledge, snapshot.id)

    (series,) = data.series
    assert len(series.points) == 1
    assert series.has_dynamics is False


def test_two_snapshots_give_dynamics_sorted_by_sampling_date(repo, knowledge):
    client, first = _client_with_snapshot(repo, date(2026, 6, 1))
    second = repo.snapshots.create(client.code, date(2026, 9, 1))

    later = repo.snapshots.add_measurement(
        second.id, "ферритин", "Ферритин", 45.0, "45", "нг/мл", date(2026, 8, 25)
    )
    earlier = repo.snapshots.add_measurement(
        first.id, "ферритин", "Ферритин", 18.0, "18", "нг/мл", date(2026, 5, 20)
    )
    repo.snapshots.confirm_measurement(later.id, second.id)
    repo.snapshots.confirm_measurement(earlier.id, first.id)
    _approved_draft(repo, second.id)

    data = _collect(repo, knowledge, second.id)

    (series,) = data.series
    assert series.has_dynamics is True
    assert [p.value for p in series.points] == [18.0, 45.0]
    assert [p.taken_on for p in series.points] == [date(2026, 5, 20), date(2026, 8, 25)]


def test_unconfirmed_history_does_not_reach_the_chart(repo, knowledge):
    """График строится по сверенному, иначе клиент увидит непроверенную точку."""
    client, first = _client_with_snapshot(repo, date(2026, 6, 1))
    second = repo.snapshots.create(client.code, date(2026, 9, 1))
    repo.snapshots.add_measurement(
        first.id, "ферритин", "Ферритин", 5.0, "5", "нг/мл", date(2026, 5, 20)
    )
    stored = repo.snapshots.add_measurement(
        second.id, "ферритин", "Ферритин", 45.0, "45", "нг/мл", date(2026, 8, 25)
    )
    repo.snapshots.confirm_measurement(stored.id, second.id)
    _approved_draft(repo, second.id)

    data = _collect(repo, knowledge, second.id)

    (series,) = data.series
    assert [p.value for p in series.points] == [45.0]
    assert series.has_dynamics is False


def test_unrecognised_measurement_has_no_series(repo, knowledge):
    """У показателя без идентификатора нечего откладывать по оси."""
    client, snapshot = _client_with_snapshot(repo)
    stored = repo.snapshots.add_measurement(
        snapshot.id, "", "Гомоцистеин", 12.0, "12", "мкмоль/л", date(2026, 8, 20)
    )
    repo.snapshots.confirm_measurement(stored.id, snapshot.id)
    _approved_draft(repo, snapshot.id)

    data = _collect(repo, knowledge, snapshot.id)

    assert data.series == ()
