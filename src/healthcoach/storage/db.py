"""Открытие базы и применение схемы."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from healthcoach.storage.schema import MIGRATIONS, SCHEMA, SCHEMA_VERSION


class StorageError(Exception):
    """База непригодна к использованию."""


def open_database(path: Path) -> sqlite3.Connection:
    """Открыть базу, создав её при отсутствии, и применить схему."""
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")

    (found,) = connection.execute("PRAGMA user_version").fetchone()
    if found > SCHEMA_VERSION:
        connection.close()
        raise StorageError(
            f"{path}: версия схемы {found} новее поддерживаемой {SCHEMA_VERSION}; "
            f"обновите приложение"
        )

    connection.executescript(SCHEMA)

    # Ноль означает пустой файл: executescript только что создал схему
    # текущей версии, доделывать в ней нечего. Всё остальное — база более
    # ранней версии, её надо провести по переходам.
    version = SCHEMA_VERSION if found == 0 else found
    while version < SCHEMA_VERSION:
        steps = MIGRATIONS.get(version)
        if steps is None:
            connection.close()
            raise StorageError(
                f"{path}: нет перехода со схемы версии {version} на {version + 1}"
            )
        for statement in steps:
            connection.execute(statement)
        version += 1

    if found != SCHEMA_VERSION:
        # PRAGMA user_version переписывает первую страницу файла и берёт
        # исключительную блокировку. Приложение открывает базу на каждый
        # запрос, включая чтения: безусловная запись превращала бы любой
        # GET в писателя и роняла бы его «database is locked» под нагрузкой.
        connection.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
    connection.commit()
    return connection
