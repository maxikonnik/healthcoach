"""Переход существующей базы на схему версии 2.

База коуча живёт у него на машине годами и переносится копированием.
Переход, который её ломает, хуже отсутствия перехода: данные есть, а
работать с ними нельзя.
"""

import sqlite3
from datetime import date
from pathlib import Path

from healthcoach.storage.clients import ClientRepository
from healthcoach.storage.db import open_database
from healthcoach.storage.schema import SCHEMA_VERSION
from healthcoach.storage.snapshots import SnapshotRepository

SCHEMA_V1 = """
CREATE TABLE identities (
    code       TEXT PRIMARY KEY,
    full_name  TEXT NOT NULL,
    contacts   TEXT,
    note       TEXT
);

CREATE TABLE snapshots (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    client_code  TEXT NOT NULL REFERENCES identities(code) ON DELETE CASCADE,
    taken_on     TEXT NOT NULL,
    note         TEXT
);
"""


def _version_one_database(path: Path) -> None:
    connection = sqlite3.connect(path)
    connection.executescript(SCHEMA_V1)
    connection.execute(
        "INSERT INTO identities (code, full_name, contacts, note) VALUES (?, ?, ?, ?)",
        ("CL-0001", "Иванова Мария", "@masha", None),
    )
    connection.execute(
        "INSERT INTO snapshots (client_code, taken_on, note) VALUES (?, ?, ?)",
        ("CL-0001", "2026-09-01", None),
    )
    connection.execute("PRAGMA user_version = 1")
    connection.commit()
    connection.close()


def test_version_one_database_migrates_and_keeps_its_data(tmp_path):
    path = tmp_path / "db.sqlite"
    _version_one_database(path)

    with open_database(path) as connection:
        (version,) = connection.execute("PRAGMA user_version").fetchone()
        assert version == SCHEMA_VERSION
        client = ClientRepository(connection).get("CL-0001")

    assert client is not None
    assert client.full_name == "Иванова Мария"
    assert client.contacts == "@masha"


def test_client_from_a_migrated_database_is_readable_but_incomplete(tmp_path):
    """Пустые поля не подставляются: карточка честно говорит, что не готова."""
    path = tmp_path / "db.sqlite"
    _version_one_database(path)

    with open_database(path) as connection:
        client = ClientRepository(connection).get("CL-0001")

    assert client.sex == ""
    assert client.birth_date is None
    assert client.is_complete is False


def test_filling_the_card_makes_it_complete(tmp_path):
    path = tmp_path / "db.sqlite"
    _version_one_database(path)

    with open_database(path) as connection:
        clients = ClientRepository(connection)
        assert clients.update("CL-0001", "ж", date(1990, 5, 17)) is True
        client = clients.get("CL-0001")

    assert client.is_complete is True
    assert client.sex == "ж"
    assert client.age_on(date(2026, 9, 1)) == 36


def test_updating_a_client_that_does_not_exist_reports_failure(tmp_path):
    with open_database(tmp_path / "db.sqlite") as connection:
        assert (
            ClientRepository(connection).update("CL-9999", "ж", date(1990, 5, 17))
            is False
        )


def test_reopening_an_up_to_date_database_does_not_write_to_it(tmp_path):
    """Приложение открывает базу на каждый запрос, включая чтения.

    Безусловная запись PRAGMA user_version переписывала бы первую страницу
    файла и брала исключительную блокировку на каждом просмотре страницы.
    """
    path = tmp_path / "db.sqlite"
    open_database(path).close()
    before = path.read_bytes()

    open_database(path).close()

    assert path.read_bytes() == before


def test_migration_writes_the_new_version(tmp_path):
    path = tmp_path / "db.sqlite"
    _version_one_database(path)
    before = path.read_bytes()

    open_database(path).close()

    assert path.read_bytes() != before
    connection = sqlite3.connect(path)
    (version,) = connection.execute("PRAGMA user_version").fetchone()
    connection.close()
    assert version == SCHEMA_VERSION


SCHEMA_V2 = """
CREATE TABLE identities (
    code        TEXT PRIMARY KEY,
    full_name   TEXT NOT NULL,
    sex         TEXT NOT NULL,
    birth_date  TEXT NOT NULL,
    contacts    TEXT,
    note        TEXT
);

CREATE TABLE snapshots (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    client_code  TEXT NOT NULL REFERENCES identities(code) ON DELETE CASCADE,
    taken_on     TEXT NOT NULL,
    note         TEXT
);

CREATE TABLE documents (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    snapshot_id  INTEGER NOT NULL REFERENCES snapshots(id) ON DELETE CASCADE,
    filename     TEXT NOT NULL,
    stored_path  TEXT NOT NULL,
    added_at     TEXT NOT NULL
);

CREATE TABLE measurements (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    snapshot_id  INTEGER NOT NULL REFERENCES snapshots(id) ON DELETE CASCADE,
    analyte_id   TEXT NOT NULL,
    raw_name     TEXT NOT NULL,
    value        REAL NOT NULL,
    units        TEXT NOT NULL,
    taken_on     TEXT NOT NULL,
    document_id  INTEGER REFERENCES documents(id) ON DELETE SET NULL,
    confirmed    INTEGER NOT NULL DEFAULT 0
);
"""


def _version_two_database(path: Path) -> None:
    connection = sqlite3.connect(path)
    connection.executescript(SCHEMA_V2)
    connection.execute(
        "INSERT INTO identities VALUES (?, ?, ?, ?, ?, ?)",
        ("CL-0001", "Иванова Мария", "ж", "1990-05-17", "@masha", None),
    )
    connection.execute(
        "INSERT INTO snapshots (client_code, taken_on, note) VALUES (?, ?, ?)",
        ("CL-0001", "2026-09-01", None),
    )
    connection.execute(
        "INSERT INTO measurements "
        "(snapshot_id, analyte_id, raw_name, value, units, taken_on, confirmed) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (1, "ферритин", "Ферритин", 18.0, "нг/мл", "2026-08-20", 1),
    )
    connection.execute("PRAGMA user_version = 2")
    connection.commit()
    connection.close()


def test_version_two_database_keeps_its_measurements(tmp_path):
    """Пересборка таблицы не имеет права потерять подтверждённые измерения."""
    path = tmp_path / "db.sqlite"
    _version_two_database(path)

    with open_database(path) as connection:
        (version,) = connection.execute("PRAGMA user_version").fetchone()
        (stored,) = SnapshotRepository(connection).measurements(1)

    assert version == SCHEMA_VERSION
    assert stored.analyte_id == "ферритин"
    assert stored.value == 18.0
    assert stored.confirmed is True
    assert stored.source == "ручной ввод"
    assert stored.raw_value == "18.0"
