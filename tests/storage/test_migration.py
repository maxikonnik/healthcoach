"""Переход существующей базы на схему версии 2.

База коуча живёт у него на машине годами и переносится копированием.
Переход, который её ломает, хуже отсутствия перехода: данные есть, а
работать с ними нельзя.
"""

import sqlite3
from datetime import date
from pathlib import Path

import pytest

from healthcoach.storage.clients import ClientRepository
from healthcoach.storage.db import _migrate, open_database
from healthcoach.storage.schema import MIGRATIONS, SCHEMA_VERSION
from healthcoach.storage.snapshots import SOURCE_PHOTO, SnapshotRepository

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
    """База версии 2 с двумя срезами и намеренно неаккуратными данными.

    Единственная строка с id 1, снимком 1 и NULL-документом не поймала бы
    ни перенумерацию id при переносе, ни потерю ссылки на документ, ни
    снятые внешние ключи или индексы — со всем этим полный набор тестов
    прошёл бы и с испорченным переходом. Поэтому здесь: два среза,
    неподряд идущие id измерений, непустой document_id, разные confirmed
    и дробные значения.
    """
    connection = sqlite3.connect(path)
    connection.executescript(SCHEMA_V2)
    connection.execute(
        "INSERT INTO identities VALUES (?, ?, ?, ?, ?, ?)",
        ("CL-0001", "Иванова Мария", "ж", "1990-05-17", "@masha", None),
    )
    connection.execute(
        "INSERT INTO snapshots (id, client_code, taken_on, note) VALUES (?, ?, ?, ?)",
        (1, "CL-0001", "2026-09-01", None),
    )
    connection.execute(
        "INSERT INTO snapshots (id, client_code, taken_on, note) VALUES (?, ?, ?, ?)",
        (2, "CL-0001", "2026-01-15", None),
    )
    connection.execute(
        "INSERT INTO documents (id, snapshot_id, filename, stored_path, added_at) "
        "VALUES (?, ?, ?, ?, ?)",
        (1, 1, "Биохимия.pdf", "/data/documents/1/a.pdf", "2026-09-01T00:00:00"),
    )
    connection.execute(
        "INSERT INTO measurements "
        "(id, snapshot_id, analyte_id, raw_name, value, units, taken_on, "
        " document_id, confirmed) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (1, 1, "ферритин", "Ферритин", 18.0, "нг/мл", "2026-08-20", None, 1),
    )
    connection.execute(
        "INSERT INTO measurements "
        "(id, snapshot_id, analyte_id, raw_name, value, units, taken_on, "
        " document_id, confirmed) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (5, 1, "срб", "С-реактивный белок", 0.35, "мг/л", "2026-08-20", 1, 0),
    )
    connection.execute(
        "INSERT INTO measurements "
        "(id, snapshot_id, analyte_id, raw_name, value, units, taken_on, "
        " document_id, confirmed) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (9, 2, "ферритин", "Ферритин", 22.7, "нг/мл", "2026-01-10", None, 1),
    )
    connection.execute("PRAGMA user_version = 2")
    connection.commit()
    connection.close()


def test_version_two_database_keeps_its_measurements(tmp_path):
    """Пересборка таблицы не имеет права потерять измерения, перенумеровать
    их id, оторвать от документа или снять внешние ключи и индексы."""
    path = tmp_path / "db.sqlite"
    _version_two_database(path)

    with open_database(path) as connection:
        (version,) = connection.execute("PRAGMA user_version").fetchone()
        repo = SnapshotRepository(connection)
        by_id = {m.id: m for m in repo.measurements(1)} | {
            m.id: m for m in repo.measurements(2)
        }
        foreign_keys = connection.execute(
            "PRAGMA foreign_key_list(measurements)"
        ).fetchall()
        indexes = connection.execute("PRAGMA index_list(measurements)").fetchall()

    assert version == SCHEMA_VERSION

    # id не перенумерованы: coach мог сослаться на id 9 из адреса
    # /snapshots/2/measurements/9/confirm, и этот id обязан выжить.
    assert set(by_id) == {1, 5, 9}

    ferritin = by_id[1]
    assert ferritin.analyte_id == "ферритин"
    assert ferritin.value == 18.0
    assert ferritin.raw_value == "18.0"
    assert ferritin.units == "нг/мл"
    assert ferritin.taken_on == date(2026, 8, 20)
    assert ferritin.confirmed is True
    assert ferritin.source == "ручной ввод"
    assert ferritin.document_id is None

    crp = by_id[5]
    assert crp.analyte_id == "срб"
    assert crp.value == 0.35
    assert crp.raw_value == "0.35"
    assert crp.confirmed is False
    assert crp.document_id == 1  # ссылка на документ не должна теряться

    other_snapshot_ferritin = by_id[9]
    assert other_snapshot_ferritin.value == 22.7
    assert other_snapshot_ferritin.confirmed is True
    assert other_snapshot_ferritin.document_id is None

    # Внешние ключи таблицы пересобраны, а не потеряны при CREATE TABLE.
    on_delete = {row["table"]: row["on_delete"] for row in foreign_keys}
    assert on_delete == {"snapshots": "CASCADE", "documents": "SET NULL"}

    # Оба индекса, созданных переходом, на месте.
    index_names = {row["name"] for row in indexes}
    assert {"measurements_by_snapshot", "measurements_by_analyte"} <= index_names


def test_reentering_the_migration_on_an_already_migrated_database_is_a_noop(tmp_path):
    """Второе соединение, догнавшее файл уже после перехода, не должно
    повторно прогонять MIGRATIONS[2] и портить перенесённые данные.

    Каждый HTTP-запрос открывает своё соединение к одному файлу: если два
    запроса одновременно застали базу версии 2, оба войдут в переход, но
    выполнить его должен только тот, кто первым получит блокировку —
    другой обязан увидеть, что версия уже целевая, и ничего не делать.
    Повторный прогон переписал бы raw_value строки, распознанной с
    фотографии, обратно в CAST(value AS TEXT) и сбросил бы её источник на
    «ручной ввод» — именно то, ради чего эта задача существует.
    """
    path = tmp_path / "db.sqlite"
    _version_two_database(path)

    connection = open_database(path)
    snapshots = SnapshotRepository(connection)
    photo_row = snapshots.add_measurement(
        1,
        analyte_id="д3",
        raw_name="Витамин D3",
        value=18.5,
        raw_value="18,5",
        units="нг/мл",
        taken_on=date(2026, 8, 21),
        source=SOURCE_PHOTO,
    )

    # Симулируем застрявшее соединение: оно уже провело базу до версии 3,
    # но повторный вход в переход должен остаться безвредным no-op'ом.
    _migrate(connection, path)

    (reread,) = [
        m for m in snapshots.measurements(1) if m.id == photo_row.id
    ]
    assert reread.raw_value == "18,5"
    assert reread.source == SOURCE_PHOTO
    assert reread.value == 18.5

    (version,) = connection.execute("PRAGMA user_version").fetchone()
    assert version == SCHEMA_VERSION
    connection.close()


def test_interrupted_migration_leaves_no_half_applied_state(tmp_path, monkeypatch):
    """Обрыв посреди перехода не должен оставлять файл, который второй раз
    не открыть — ни переименованной measurements_v2, ни пустой measurements.
    """
    path = tmp_path / "db.sqlite"
    _version_two_database(path)

    # Ломаем переход после RENAME и CREATE (первые два шага), но до
    # переноса строк — ровно там, где реальный обрыв причинил бы самый
    # большой ущерб.
    broken = MIGRATIONS[2][:2] + ("ЭТО НЕ SQL СОВСЕМ",) + MIGRATIONS[2][2:]
    with monkeypatch.context() as patched:
        patched.setitem(MIGRATIONS, 2, broken)
        with pytest.raises(sqlite3.OperationalError):
            open_database(path)

    # Файл не испорчен: RENAME и CREATE, уже выполненные к моменту сбоя,
    # обязаны быть откачены вместе со всей транзакцией.
    raw = sqlite3.connect(path)
    raw.row_factory = sqlite3.Row
    tables = {
        row["name"]
        for row in raw.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        ).fetchall()
    }
    assert "measurements_v2" not in tables
    (count,) = raw.execute("SELECT COUNT(*) FROM measurements").fetchone()
    assert count == 3
    (version,) = raw.execute("PRAGMA user_version").fetchone()
    assert version == 2
    raw.close()

    # После починки обычный переход проходит и переносит данные как обычно.
    with open_database(path) as connection:
        (version,) = connection.execute("PRAGMA user_version").fetchone()
        by_id = {m.id: m for m in SnapshotRepository(connection).measurements(1)}

    assert version == SCHEMA_VERSION
    assert by_id[1].value == 18.0
    assert by_id[5].value == 0.35
