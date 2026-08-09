from datetime import date, datetime

import pytest

from healthcoach.storage.clients import ClientRepository
from healthcoach.storage.db import open_database
from healthcoach.storage.documents import DocumentRepository
from healthcoach.storage.snapshots import SOURCE_PDF, SnapshotRepository


@pytest.fixture
def repositories(tmp_path):
    connection = open_database(tmp_path / "db.sqlite")
    clients = ClientRepository(connection)
    client = clients.add("Иванова Мария", "ж", date(1990, 5, 17))
    snapshots = SnapshotRepository(connection)
    snapshot = snapshots.create(client.code, date(2026, 9, 1))
    yield snapshot, snapshots, DocumentRepository(connection)
    connection.close()


def test_document_is_stored_and_read_back(repositories):
    snapshot, _, documents = repositories
    added = datetime(2026, 9, 1, 12, 30)
    stored = documents.add(snapshot.id, "Биохимия.pdf", "/data/documents/1/a.pdf", added)

    (read_back,) = documents.for_snapshot(snapshot.id)
    assert read_back.id == stored.id
    assert read_back.filename == "Биохимия.pdf"
    assert read_back.stored_path == "/data/documents/1/a.pdf"
    assert read_back.added_at == added


def test_documents_of_another_snapshot_are_not_returned(repositories):
    snapshot, snapshots, documents = repositories
    other = snapshots.create(snapshot.client_code, date(2026, 10, 1))
    documents.add(other.id, "Чужой.pdf", "/data/documents/2/b.pdf", datetime(2026, 10, 1))

    assert documents.for_snapshot(snapshot.id) == []


def test_unknown_document_is_none(repositories):
    _, _, documents = repositories
    assert documents.get(99999) is None


def test_measurement_without_a_number_keeps_the_original_text(repositories):
    """«<0.60» — ниже порога чувствительности метода, а не 0.60."""
    snapshot, snapshots, documents = repositories
    document = documents.add(
        snapshot.id, "Биохимия.pdf", "/data/documents/1/a.pdf", datetime(2026, 9, 1)
    )
    snapshots.add_measurement(
        snapshot.id,
        analyte_id="срб",
        raw_name="С-реактивный белок",
        value=None,
        raw_value="<0.60",
        units="мг/л",
        taken_on=date(2026, 8, 20),
        source=SOURCE_PDF,
        document_id=document.id,
    )

    (stored,) = snapshots.measurements(snapshot.id)
    assert stored.value is None
    assert stored.raw_value == "<0.60"
    assert stored.source == SOURCE_PDF
    assert stored.document_id == document.id


def test_coach_can_fill_in_the_missing_number(repositories):
    snapshot, snapshots, _ = repositories
    stored = snapshots.add_measurement(
        snapshot.id,
        analyte_id="срб",
        raw_name="С-реактивный белок",
        value=None,
        raw_value="<0.60",
        units="мг/л",
        taken_on=date(2026, 8, 20),
    )

    assert snapshots.set_value(stored.id, snapshot.id, 0.3) is True
    (read_back,) = snapshots.measurements(snapshot.id)
    assert read_back.value == 0.3
    assert read_back.raw_value == "<0.60"


def test_filling_a_value_does_not_reach_another_snapshot(repositories):
    """Идентификатор среза в адресе обязан что-то значить."""
    snapshot, snapshots, _ = repositories
    other = snapshots.create(snapshot.client_code, date(2026, 10, 1))
    stored = snapshots.add_measurement(
        other.id,
        analyte_id="срб",
        raw_name="С-реактивный белок",
        value=None,
        raw_value="<0.60",
        units="мг/л",
        taken_on=date(2026, 8, 20),
    )

    assert snapshots.set_value(stored.id, snapshot.id, 0.3) is False
    (untouched,) = snapshots.measurements(other.id)
    assert untouched.value is None


def test_set_value_does_not_overwrite_a_value_the_coach_already_has(repositories):
    """set_value заполняет пропуск, а не переписывает уже подтверждённое число."""
    snapshot, snapshots, _ = repositories
    stored = snapshots.add_measurement(
        snapshot.id,
        analyte_id="ферритин",
        raw_name="Ферритин",
        value=18.0,
        raw_value="18.0",
        units="нг/мл",
        taken_on=date(2026, 8, 20),
    )

    assert snapshots.set_value(stored.id, snapshot.id, 999.0) is False
    (untouched,) = snapshots.measurements(snapshot.id)
    assert untouched.value == 18.0
    assert untouched.raw_value == "18.0"


def test_set_value_reports_failure_for_a_measurement_that_does_not_exist(repositories):
    """Молчаливый успех на несуществующий идентификатор скрывал бы опечатку."""
    snapshot, snapshots, _ = repositories
    assert snapshots.set_value(99999, snapshot.id, 0.3) is False
