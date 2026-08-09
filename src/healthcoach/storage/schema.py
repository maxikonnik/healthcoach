"""Схема базы данных.

Один файл SQLite на машине коуча: копируется и переносится целиком.
Обновлений по сети нет, поэтому схема применяется идемпотентно при
открытии, а версия пишется в PRAGMA user_version — несовместимость
должна обнаруживаться явно, а не порчей данных.
"""

from __future__ import annotations

SCHEMA_VERSION = 4

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
    added_at     TEXT NOT NULL,
    unparsed     TEXT NOT NULL DEFAULT ''
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
    3: (
        # Строки, которые разбор не смог превратить в запись бланка,
        # раньше не переживали редирект после загрузки. Они разбираются
        # один раз при импорте и с этого момента хранятся с документом,
        # а не только в ответе на POST.
        #
        # Не простой ALTER TABLE ADD COLUMN: unconditional CREATE TABLE IF
        # NOT EXISTS в SCHEMA лениво создаёт `documents` уже с колонкой
        # `unparsed`, если база настолько стара, что этой таблицы у неё
        # ещё не было (см. миграцию с версии 1 в тестах) — тогда ALTER на
        # уже свежесозданной таблице падает с «duplicate column name».
        #
        # Не переименование `documents` в сторону с последующим DROP, как
        # это (для measurements, у которой нет входящих внешних ключей)
        # делает переход 2 → 3: `documents` — родительская сторона внешнего
        # ключа measurements.document_id, и DROP TABLE documents с
        # PRAGMA foreign_keys = ON немедленно применяет ON DELETE SET NULL
        # ко всем строкам measurements, которые на неё ссылались, — какой
        # бы промежуточной ни была цепочка переименований. Пересборка
        # родительской таблицы обнуляла бы document_id у уже импортированных
        # измерений молча, без единой ошибки.
        #
        # Поэтому связи сохраняются вручную: id measurements, у которых
        # document_id не NULL, откладываются во временную таблицу, сама
        # колонка обнуляется (это не DELETE и каскад не запускает), старая
        # `documents` удаляется уже без единой ссылающейся на неё строки,
        # новая — с колонкой `unparsed` — занимает освободившееся имя, и
        # отложенные document_id прописываются обратно. Имя `documents`,
        # на которое ссылается measurements, не переименовывается ни разу.
        """
        CREATE TABLE documents_v3 (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            snapshot_id  INTEGER NOT NULL REFERENCES snapshots(id) ON DELETE CASCADE,
            filename     TEXT NOT NULL,
            stored_path  TEXT NOT NULL,
            added_at     TEXT NOT NULL,
            unparsed     TEXT NOT NULL DEFAULT ''
        )
        """,
        """
        INSERT INTO documents_v3 (id, snapshot_id, filename, stored_path, added_at, unparsed)
        SELECT id, snapshot_id, filename, stored_path, added_at, ''
        FROM documents
        """,
        """
        CREATE TABLE documents_v3_links AS
        SELECT id AS measurement_id, document_id
        FROM measurements
        WHERE document_id IS NOT NULL
        """,
        "UPDATE measurements SET document_id = NULL WHERE document_id IS NOT NULL",
        "DROP TABLE documents",
        "ALTER TABLE documents_v3 RENAME TO documents",
        """
        UPDATE measurements
        SET document_id = (
            SELECT document_id FROM documents_v3_links
            WHERE measurement_id = measurements.id
        )
        WHERE id IN (SELECT measurement_id FROM documents_v3_links)
        """,
        "DROP TABLE documents_v3_links",
    ),
}
"""Что доделать в базе версии N, чтобы она стала версией N+1.

Пустые значения у прежних клиентов не подставляют пол и возраст молча:
карточка без них не даёт считать находки и просит заполнить.
"""
