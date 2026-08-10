from datetime import date

import pytest

from healthcoach.storage.clients import ClientRepository
from healthcoach.storage.db import open_database
from healthcoach.storage.scopes import ReportScopeRepository
from healthcoach.storage.snapshots import SnapshotRepository


@pytest.fixture
def repositories(tmp_path):
    with open_database(tmp_path / "db.sqlite") as connection:
        clients = ClientRepository(connection)
        client = clients.add("Иванова Мария", "ж", date(1990, 5, 17))
        snapshots = SnapshotRepository(connection)
        scopes = ReportScopeRepository(connection)
        yield client.code, snapshots, scopes, connection


def test_set_members_round_trips(repositories):
    code, snapshots, scopes, _connection = repositories
    primary = snapshots.create(code, date(2026, 9, 1))
    earlier = snapshots.create(code, date(2026, 1, 15))

    scopes.set_members(primary.id, [primary.id, earlier.id])

    assert scopes.members(primary.id) == sorted([primary.id, earlier.id])


def test_snapshot_without_recorded_scope_falls_back_to_itself(repositories):
    code, snapshots, scopes, _connection = repositories
    snapshot = snapshots.create(code, date(2026, 9, 1))

    assert scopes.members(snapshot.id) == [snapshot.id]


def test_set_members_replaces_rather_than_adds(repositories):
    code, snapshots, scopes, _connection = repositories
    primary = snapshots.create(code, date(2026, 9, 1))
    first = snapshots.create(code, date(2026, 1, 15))
    second = snapshots.create(code, date(2026, 3, 1))

    scopes.set_members(primary.id, [primary.id, first.id])
    scopes.set_members(primary.id, [primary.id, second.id])

    assert scopes.members(primary.id) == sorted([primary.id, second.id])


def test_set_members_rejects_empty_set(repositories):
    code, snapshots, scopes, _connection = repositories
    primary = snapshots.create(code, date(2026, 9, 1))

    with pytest.raises(ValueError):
        scopes.set_members(primary.id, [])


def test_scopes_of_different_snapshots_do_not_mix(repositories):
    code, snapshots, scopes, _connection = repositories
    first_primary = snapshots.create(code, date(2026, 9, 1))
    second_primary = snapshots.create(code, date(2026, 6, 1))
    member = snapshots.create(code, date(2026, 1, 15))

    scopes.set_members(first_primary.id, [first_primary.id, member.id])
    scopes.set_members(second_primary.id, [second_primary.id])

    assert scopes.members(first_primary.id) == sorted([first_primary.id, member.id])
    assert scopes.members(second_primary.id) == [second_primary.id]


def test_deleting_owning_snapshot_drops_its_scope_rows(repositories):
    code, snapshots, scopes, connection = repositories
    primary = snapshots.create(code, date(2026, 9, 1))
    member = snapshots.create(code, date(2026, 1, 15))
    scopes.set_members(primary.id, [primary.id, member.id])

    connection.execute("DELETE FROM snapshots WHERE id = ?", (primary.id,))
    connection.commit()

    rows = connection.execute(
        "SELECT * FROM report_snapshots WHERE snapshot_id = ?", (primary.id,)
    ).fetchall()
    assert rows == []


def test_deleting_member_snapshot_drops_its_scope_row(repositories):
    code, snapshots, scopes, connection = repositories
    primary = snapshots.create(code, date(2026, 9, 1))
    member = snapshots.create(code, date(2026, 1, 15))
    scopes.set_members(primary.id, [primary.id, member.id])

    connection.execute("DELETE FROM snapshots WHERE id = ?", (member.id,))
    connection.commit()

    assert scopes.members(primary.id) == [primary.id]
