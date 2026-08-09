from datetime import date

import pytest

from healthcoach.storage.clients import ClientRepository
from healthcoach.storage.db import open_database
from healthcoach.storage.requests import RequestRepository
from healthcoach.storage.snapshots import SnapshotRepository


@pytest.fixture
def repositories(tmp_path):
    connection = open_database(tmp_path / "db.sqlite")
    client = ClientRepository(connection).add("Иванова Мария", "ж", date(1990, 5, 17))
    snapshots = SnapshotRepository(connection)
    snapshot = snapshots.create(client.code, date(2026, 9, 1))
    yield snapshot, snapshots, RequestRepository(connection)
    connection.close()


def test_request_is_saved_and_read_back(repositories):
    snapshot, _, requests = repositories
    saved = requests.save(snapshot.id, "Хочу разобраться с усталостью")

    read_back = requests.get(snapshot.id)
    assert read_back == saved
    assert read_back.raw == "Хочу разобраться с усталостью"
    assert read_back.redacted == ""
    assert read_back.approved is False


def test_saving_again_replaces_the_text_and_drops_the_approval(repositories):
    """Клиент переписал запрос — прежняя вычитка к новому тексту не относится."""
    snapshot, _, requests = repositories
    requests.save(snapshot.id, "Первый текст")
    requests.set_redacted(snapshot.id, "Первый текст без имён")
    requests.approve(snapshot.id)

    requests.save(snapshot.id, "Второй текст")

    read_back = requests.get(snapshot.id)
    assert read_back.raw == "Второй текст"
    assert read_back.redacted == ""
    assert read_back.approved is False


def test_redaction_does_not_touch_the_original(repositories):
    snapshot, _, requests = repositories
    requests.save(snapshot.id, "Работаю в школе № 1234")
    requests.set_redacted(snapshot.id, "Работаю в школе")

    read_back = requests.get(snapshot.id)
    assert read_back.raw == "Работаю в школе № 1234"
    assert read_back.redacted == "Работаю в школе"


def test_approval_requires_a_redacted_text(repositories):
    """Утвердить нечего, пока коуч не вычитал."""
    snapshot, _, requests = repositories
    requests.save(snapshot.id, "Текст")

    assert requests.approve(snapshot.id) is False
    assert requests.get(snapshot.id).approved is False


def test_unknown_snapshot_reports_failure(repositories):
    _, _, requests = repositories
    assert requests.get(99999) is None
    assert requests.set_redacted(99999, "что-то") is False
    assert requests.approve(99999) is False
