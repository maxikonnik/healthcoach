from datetime import date
from pathlib import Path

import pytest

from healthcoach.storage.clients import ClientRepository
from healthcoach.storage.db import open_database
from healthcoach.storage.snapshots import SnapshotRepository


@pytest.fixture
def repositories(tmp_path):
    with open_database(tmp_path / "db.sqlite") as connection:
        clients = ClientRepository(connection)
        client = clients.add("Иванова Мария")
        yield client.code, SnapshotRepository(connection)


def test_creates_and_reads_snapshot(repositories):
    code, snapshots = repositories
    created = snapshots.create(code, date(2026, 9, 1), note="первичный")
    fetched = snapshots.get(created.id)
    assert fetched.client_code == code
    assert fetched.taken_on == date(2026, 9, 1)
    assert fetched.note == "первичный"


def test_snapshots_for_client_are_sorted_by_date(repositories):
    code, snapshots = repositories
    snapshots.create(code, date(2026, 9, 1))
    snapshots.create(code, date(2026, 1, 15))
    assert [s.taken_on for s in snapshots.for_client(code)] == [
        date(2026, 1, 15),
        date(2026, 9, 1),
    ]


def test_measurement_round_trip(repositories):
    code, snapshots = repositories
    snapshot = snapshots.create(code, date(2026, 9, 1))
    stored = snapshots.add_measurement(
        snapshot.id,
        analyte_id="ферритин",
        raw_name="Ферритин (S-Ferritin)",
        value=18.0,
        units="нг/мл",
        taken_on=date(2026, 8, 20),
    )
    assert stored.confirmed is False
    (read_back,) = snapshots.measurements(snapshot.id)
    assert read_back.analyte_id == "ферритин"
    assert read_back.value == 18.0
    assert read_back.taken_on == date(2026, 8, 20)


def test_confirming_a_measurement_sticks(repositories):
    code, snapshots = repositories
    snapshot = snapshots.create(code, date(2026, 9, 1))
    stored = snapshots.add_measurement(
        snapshot.id, "ферритин", "Ферритин", 18.0, "нг/мл", date(2026, 8, 20)
    )
    snapshots.confirm_measurement(stored.id)
    (read_back,) = snapshots.measurements(snapshot.id)
    assert read_back.confirmed is True


def test_history_spans_snapshots_and_sorts_by_sampling_date(repositories):
    """Динамика строится по дате забора, а не по дате загрузки."""
    code, snapshots = repositories
    later = snapshots.create(code, date(2026, 9, 1))
    earlier = snapshots.create(code, date(2026, 1, 15))
    snapshots.add_measurement(
        later.id, "ферритин", "Ферритин", 45.0, "нг/мл", date(2026, 8, 20)
    )
    snapshots.add_measurement(
        earlier.id, "ферритин", "Ферритин", 18.0, "нг/мл", date(2026, 1, 10)
    )
    assert [m.value for m in snapshots.history(code, "ферритин")] == [18.0, 45.0]


def test_answers_round_trip(repositories):
    code, snapshots = repositories
    snapshot = snapshots.create(code, date(2026, 9, 1))
    snapshots.save_answers(snapshot.id, {"pitanie.а.1": 2, "pitanie.а.2": 0})
    assert snapshots.answers(snapshot.id) == {"pitanie.а.1": 2, "pitanie.а.2": 0}


def test_saving_answers_replaces_previous(repositories):
    code, snapshots = repositories
    snapshot = snapshots.create(code, date(2026, 9, 1))
    snapshots.save_answers(snapshot.id, {"pitanie.а.1": 2})
    snapshots.save_answers(snapshot.id, {"pitanie.а.1": 3})
    assert snapshots.answers(snapshot.id) == {"pitanie.а.1": 3}


def test_snapshot_module_never_touches_the_identity_table():
    """Реестр ФИО читает только ClientRepository — граница закреплена тестом."""
    source = Path("src/healthcoach/storage/snapshots.py").read_text(encoding="utf-8")
    assert "identities" not in source
    assert "full_name" not in source


def test_snapshot_module_does_not_delegate_to_the_client_repository():
    """Вторая дорога к именам — импорт репозитория клиентов; она тоже закрыта.

    Проверка по дереву импортов, а не по строкам: делегирование не содержало бы
    ни слова 'identities', ни 'full_name', и текстовый страж его пропустил бы.
    """
    import ast

    source = Path("src/healthcoach/storage/snapshots.py").read_text(encoding="utf-8")
    imported: set[str] = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)
        elif isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)

    leaking = {name for name in imported if "storage.clients" in name}
    assert not leaking, f"модуль срезов импортирует {sorted(leaking)}"
