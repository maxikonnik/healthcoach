"""Схема базы данных.

Один файл SQLite на машине коуча: копируется и переносится целиком.
Обновлений по сети нет, поэтому схема применяется идемпотентно при
открытии, а версия пишется в PRAGMA user_version — несовместимость
должна обнаруживаться явно, а не порчей данных.
"""

from __future__ import annotations

SCHEMA_VERSION = 3

SCHEMA = """
CREATE TABLE IF NOT EXISTS identities (
    code        TEXT PRIMARY KEY,
    full_name   TEXT NOT NULL,
    sex         TEXT NOT NULL,
    birth_date  TEXT NOT NULL,
    contacts    TEXT,
    note        TEXT
);

CREATE TABLE IF NOT EXISTS snapshots (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    client_code  TEXT NOT NULL REFERENCES identities(code) ON DELETE CASCADE,
    taken_on     TEXT NOT NULL,
    note         TEXT
);

CREATE INDEX IF NOT EXISTS snapshots_by_client
    ON snapshots (client_code, taken_on);

CREATE TABLE IF NOT EXISTS documents (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    snapshot_id  INTEGER NOT NULL REFERENCES snapshots(id) ON DELETE CASCADE,
    filename     TEXT NOT NULL,
    stored_path  TEXT NOT NULL,
    added_at     TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS measurements (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    snapshot_id  INTEGER NOT NULL REFERENCES snapshots(id) ON DELETE CASCADE,
    analyte_id   TEXT NOT NULL,
    raw_name     TEXT NOT NULL,
    value        REAL,
    raw_value    TEXT NOT NULL DEFAULT '',
    units        TEXT NOT NULL,
    taken_on     TEXT NOT NULL,
    document_id  INTEGER REFERENCES documents(id) ON DELETE SET NULL,
    source       TEXT NOT NULL DEFAULT 'ручной ввод',
    confirmed    INTEGER NOT NULL DEFAULT 0
);

CREATE INDEX IF NOT EXISTS measurements_by_snapshot
    ON measurements (snapshot_id);

CREATE INDEX IF NOT EXISTS measurements_by_analyte
    ON measurements (analyte_id, taken_on);

CREATE TABLE IF NOT EXISTS answers (
    snapshot_id  INTEGER NOT NULL REFERENCES snapshots(id) ON DELETE CASCADE,
    question_id  TEXT NOT NULL,
    score        INTEGER NOT NULL,
    PRIMARY KEY (snapshot_id, question_id)
);
"""

MIGRATIONS: dict[int, tuple[str, ...]] = {
    1: (
        "ALTER TABLE identities ADD COLUMN sex TEXT NOT NULL DEFAULT ''",
        "ALTER TABLE identities ADD COLUMN birth_date TEXT NOT NULL DEFAULT ''",
    ),
    2: (
        # SQLite не умеет снимать NOT NULL через ALTER TABLE: значение
        # измерения должно уметь отсутствовать, поэтому таблица
        # пересобирается, а строки переносятся.
        "ALTER TABLE measurements RENAME TO measurements_v2",
        """
        CREATE TABLE measurements (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            snapshot_id  INTEGER NOT NULL REFERENCES snapshots(id) ON DELETE CASCADE,
            analyte_id   TEXT NOT NULL,
            raw_name     TEXT NOT NULL,
            value        REAL,
            raw_value    TEXT NOT NULL DEFAULT '',
            units        TEXT NOT NULL,
            taken_on     TEXT NOT NULL,
            document_id  INTEGER REFERENCES documents(id) ON DELETE SET NULL,
            source       TEXT NOT NULL DEFAULT 'ручной ввод',
            confirmed    INTEGER NOT NULL DEFAULT 0
        )
        """,
        """
        INSERT INTO measurements
            (id, snapshot_id, analyte_id, raw_name, value, raw_value,
             units, taken_on, document_id, source, confirmed)
        SELECT id, snapshot_id, analyte_id, raw_name, value, CAST(value AS TEXT),
               units, taken_on, document_id, 'ручной ввод', confirmed
        FROM measurements_v2
        """,
        "DROP TABLE measurements_v2",
        "CREATE INDEX IF NOT EXISTS measurements_by_snapshot ON measurements (snapshot_id)",
        "CREATE INDEX IF NOT EXISTS measurements_by_analyte ON measurements (analyte_id, taken_on)",
    ),
}
"""Что доделать в базе версии N, чтобы она стала версией N+1.

Пустые значения у прежних клиентов не подставляют пол и возраст молча:
карточка без них не даёт считать находки и просит заполнить.
"""
