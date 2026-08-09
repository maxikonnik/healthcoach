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

    try:
        (found,) = connection.execute("PRAGMA user_version").fetchone()
        if found > SCHEMA_VERSION:
            raise StorageError(
                f"{path}: версия схемы {found} новее поддерживаемой {SCHEMA_VERSION}; "
                f"обновите приложение"
            )

        connection.executescript(SCHEMA)

        if found != SCHEMA_VERSION:
            # PRAGMA user_version переписывает первую страницу файла и берёт
            # исключительную блокировку. Приложение открывает базу на каждый
            # запрос, включая чтения: безусловная запись превращала бы любой
            # GET в писателя и роняла бы его «database is locked» под нагрузкой.
            # Поэтому в переход входим, только если версия файла и правда
            # не совпадает с целевой.
            _migrate(connection, path)

        connection.commit()
        return connection
    except BaseException:
        # Не закрыть соединение при сбое значит держать файл заблокированным
        # для всех остальных: приложение открывает новое соединение на
        # каждый запрос, и один утёкший объект не освобождает лок в SQLite.
        connection.close()
        raise


def _migrate(connection: sqlite3.Connection, path: Path) -> None:
    """Довести базу до SCHEMA_VERSION одной транзакцией.

    Каждый HTTP-запрос открывает своё соединение, поэтому несколько
    переходов на одном и том же файле — не гипотеза, а обычный день:
    два запроса могут одновременно застать базу версии N.

    Модуль sqlite3 по умолчанию открывает неявную транзакцию только перед
    DML (INSERT/UPDATE/DELETE), а не перед DDL — без явных границ
    `ALTER TABLE ... RENAME` фиксировался бы немедленно, и обрыв перед
    следующим `CREATE TABLE` оставлял бы файл наполовину переписанным:
    старые данные — в переименованной, никому не известной таблице,
    `user_version` — как будто ничего не произошло. Поэтому здесь границы
    транзакции расставлены явно, и SQLite откатывает DDL наравне с DML.

    Версия читается заново уже внутри этой транзакции — не та, что видел
    вызывающий код до входа сюда. Если базу тем временем уже провело
    другое соединение, вторая попытка не повторяет переход: он не просто
    не нужен, а разрушителен — например, `MIGRATIONS[2]`, запущенный по
    уже мигрировавшей таблице, переписывает `raw_value` обратно в
    `CAST(value AS TEXT)` и сбрасывает `source` на «ручной ввод» поверх
    строки, распознанной с фотографии.
    """
    previous_isolation_level = connection.isolation_level
    connection.isolation_level = None  # ручное управление транзакцией
    try:
        connection.execute("BEGIN IMMEDIATE")
        (version,) = connection.execute("PRAGMA user_version").fetchone()
        # 0 — пустой файл: executescript только что создал схему текущей
        # версии, доделывать в ней нечего вне зависимости от того, что
        # показывало PRAGMA user_version до входа в транзакцию.
        if version == 0:
            version = SCHEMA_VERSION
        while version < SCHEMA_VERSION:
            steps = MIGRATIONS.get(version)
            if steps is None:
                raise StorageError(
                    f"{path}: нет перехода со схемы версии {version} на {version + 1}"
                )
            for statement in steps:
                connection.execute(statement)
            version += 1
        connection.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
        connection.execute("COMMIT")
    except BaseException:
        connection.execute("ROLLBACK")
        raise
    finally:
        connection.isolation_level = previous_isolation_level
