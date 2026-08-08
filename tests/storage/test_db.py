import sqlite3

import pytest

from healthcoach.storage.db import StorageError, open_database
from healthcoach.storage.schema import SCHEMA_VERSION


def test_creates_file_and_applies_schema(tmp_path):
    path = tmp_path / "healthcoach.db"
    with open_database(path) as connection:
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }
    assert path.exists()
    assert {"identities", "snapshots", "measurements", "answers", "documents"} <= tables


def test_records_schema_version(tmp_path):
    with open_database(tmp_path / "db.sqlite") as connection:
        (version,) = connection.execute("PRAGMA user_version").fetchone()
    assert version == SCHEMA_VERSION


def test_reopening_keeps_data(tmp_path):
    path = tmp_path / "db.sqlite"
    with open_database(path) as connection:
        connection.execute(
            "INSERT INTO identities (code, full_name, contacts, note) VALUES (?, ?, ?, ?)",
            ("CL-0001", "Иванова Мария", "@masha", None),
        )
        connection.commit()
    with open_database(path) as connection:
        (name,) = connection.execute(
            "SELECT full_name FROM identities WHERE code = ?", ("CL-0001",)
        ).fetchone()
    assert name == "Иванова Мария"


def test_foreign_keys_are_enforced(tmp_path):
    with open_database(tmp_path / "db.sqlite") as connection:
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                "INSERT INTO snapshots (client_code, taken_on, note) VALUES (?, ?, ?)",
                ("НЕТ-ТАКОГО", "2026-08-09", None),
            )
            connection.commit()


def test_newer_schema_version_is_refused(tmp_path):
    path = tmp_path / "db.sqlite"
    with open_database(path) as connection:
        connection.execute(f"PRAGMA user_version = {SCHEMA_VERSION + 1}")
        connection.commit()
    with pytest.raises(StorageError, match="новее"):
        open_database(path)
