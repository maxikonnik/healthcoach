"""Открытие базы и применение схемы."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from healthcoach.storage.schema import SCHEMA, SCHEMA_VERSION


class StorageError(Exception):
    """База непригодна к использованию."""


def open_database(path: Path) -> sqlite3.Connection:
    """Открыть базу, создав её при отсутствии, и применить схему."""
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")

    (version,) = connection.execute("PRAGMA user_version").fetchone()
    if version > SCHEMA_VERSION:
        connection.close()
        raise StorageError(
            f"{path}: версия схемы {version} новее поддерживаемой {SCHEMA_VERSION}; "
            f"обновите приложение"
        )

    connection.executescript(SCHEMA)
    if version != SCHEMA_VERSION:
        # PRAGMA user_version переписывает первую страницу файла и берёт
        # исключительную блокировку. Приложение открывает базу на каждый
        # запрос, включая чтения: безусловная запись превращала бы любой
        # GET в писателя и роняла бы его «database is locked» под нагрузкой.
        connection.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
    connection.commit()
    return connection
