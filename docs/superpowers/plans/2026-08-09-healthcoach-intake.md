# Health Coaching MVP — план 2: приём и хранение данных

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Довести систему до состояния, в котором коуч может провести клиента от анкеты до списка находок: хранилище на диске, автономный HTML-опросник для клиента, импорт его ответов, ручной ввод показателей с конвертацией единиц и распознаванием названий, и локальное веб-приложение поверх всего этого.

**Architecture:** Поверх готового детерминированного ядра (план 1) добавляются три слоя: `storage` — SQLite и файлы документов; `intake` — генерация опросника и разбор ответов; `app` — FastAPI и серверные HTML-страницы на `localhost`. Ядро остаётся чистым: `storage` и `app` зависят от `scoring` и `knowledge`, обратной зависимости нет.

**Tech Stack:** Python 3.12, uv, FastAPI, Jinja2, sqlite3 (стандартная библиотека), PyYAML, pytest.

## Global Constraints

- Python 3.12 или новее. Всё запускается через `uv run`; голые `python` и `pip` не использовать.
- **Пакеты `knowledge` и `scoring` не изменяются этим планом**, кроме одного явно оговорённого случая: задача 3 добавляет в файлы референсов необязательные ключи `синонимы_единиц` и `пересчёт`. Обратная зависимость запрещена: `knowledge` и `scoring` не импортируют `storage`, `intake` и `app`.
- **Данные клиентов не попадают в репозиторий никогда.** `.gitignore` уже закрывает `data/`, `clients/`, `*.db`, `registry.json`. Не ослаблять.
- **Реестр соответствий «код клиента ↔ ФИО» доступен только через `ClientRepository`.** Ни один модуль вне него не читает таблицу `identities`. Это та же граница, что `public_view()` у справочника специалистов, и проверяется тестом.
- Никаких молчаливых допущений: неизвестные единицы, нераспознанное название показателя, ответ вне шкалы — всё это явная ошибка или явная пометка, но не догадка и не тихий пропуск.
- Идентификаторы, названия и содержимое базы знаний — на русском; имена в коде — на английском.
- Каждая задача завершается запуском `uv run pytest` и коммитом.
- Набор тестов на момент начала плана: **138 проходящих**.

## Что этот план сознательно не делает

Чтение PDF и распознавание фото отложены в план 3: у нас нет ни одной настоящей выгрузки лаборатории, а разбор форматов вслепую — это гадание. Вместо этого задача 8 даёт коучу ручной ввод показателей, и после этого плана система работает от анкеты до находок целиком. Чтение PDF станет ускорителем поверх той же формы, а не условием её работы.

## Структура файлов

| Файл | Ответственность |
|---|---|
| `src/healthcoach/storage/schema.py` | DDL и версия схемы |
| `src/healthcoach/storage/db.py` | Открытие базы, применение схемы, транзакции |
| `src/healthcoach/storage/clients.py` | `ClientRepository` — коды, ФИО, контакты. **Единственный держатель реестра** |
| `src/healthcoach/storage/snapshots.py` | `SnapshotRepository` — срезы, измерения, ответы. Работает только с кодами |
| `src/healthcoach/knowledge/units.py` | Конвертация единиц по объявлениям коуча |
| `src/healthcoach/intake/resolve.py` | Распознавание показателя по строке из бланка |
| `src/healthcoach/intake/questionnaire_html.py` | Генератор автономного HTML-опросника |
| `src/healthcoach/intake/answers.py` | Разбор и валидация присланных ответов |
| `src/healthcoach/app/main.py` | Сборка приложения FastAPI |
| `src/healthcoach/app/deps.py` | Загрузка базы знаний и репозиториев |
| `src/healthcoach/app/routes_clients.py` | Список клиентов, карточка |
| `src/healthcoach/app/routes_snapshots.py` | Срез: анкета, показатели, находки |
| `src/healthcoach/app/templates/*.html` | Шаблоны Jinja2 |

---

### Task 1: Хранилище — схема и подключение

**Files:**
- Create: `src/healthcoach/storage/__init__.py`
- Create: `src/healthcoach/storage/schema.py`
- Create: `src/healthcoach/storage/db.py`
- Create: `tests/storage/test_db.py`

**Interfaces:**
- Consumes: ничего
- Produces:
  - `SCHEMA_VERSION: int`
  - `SCHEMA: str` — весь DDL одной строкой
  - `open_database(path: Path) -> sqlite3.Connection` — создаёт файл при отсутствии, применяет схему, включает внешние ключи
  - `StorageError(Exception)`

**Почему схема применяется при открытии.** База живёт одним файлом на машине коуча, обновлений по сети нет. Пересоздавать таблицы при каждом открытии через `CREATE TABLE IF NOT EXISTS` проще и надёжнее миграций, а версия схемы пишется в `PRAGMA user_version`, чтобы несовместимость обнаруживалась явно, а не порчей данных.

- [ ] **Step 1: Написать падающие тесты**

Файл `tests/storage/test_db.py`:

```python
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
```

- [ ] **Step 2: Запустить тесты и убедиться, что они падают**

```bash
uv run pytest tests/storage/test_db.py -v
```

Ожидается: FAIL с `ModuleNotFoundError: No module named 'healthcoach.storage'`.

- [ ] **Step 3: Реализовать схему и подключение**

Файл `src/healthcoach/storage/__init__.py`:

```python
"""Хранилище: SQLite и исходные документы клиентов."""
```

Файл `src/healthcoach/storage/schema.py`:

```python
"""Схема базы данных.

Один файл SQLite на машине коуча: копируется и переносится целиком.
Обновлений по сети нет, поэтому схема применяется идемпотентно при
открытии, а версия пишется в PRAGMA user_version — несовместимость
должна обнаруживаться явно, а не порчей данных.
"""

from __future__ import annotations

SCHEMA_VERSION = 1

SCHEMA = """
CREATE TABLE IF NOT EXISTS identities (
    code       TEXT PRIMARY KEY,
    full_name  TEXT NOT NULL,
    contacts   TEXT,
    note       TEXT
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
    value        REAL NOT NULL,
    units        TEXT NOT NULL,
    taken_on     TEXT NOT NULL,
    document_id  INTEGER REFERENCES documents(id) ON DELETE SET NULL,
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
```

Файл `src/healthcoach/storage/db.py`:

```python
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
    connection.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
    connection.commit()
    return connection
```

- [ ] **Step 4: Запустить тесты**

```bash
uv run pytest tests/storage/test_db.py -v
```

Ожидается: 5 PASS.

- [ ] **Step 5: Коммит**

```bash
git add src/healthcoach/storage tests/storage
git commit -m "feat: схема базы и открытие с проверкой версии"
```

---

### Task 2: Репозитории клиентов и срезов

**Files:**
- Create: `src/healthcoach/storage/clients.py`
- Create: `src/healthcoach/storage/snapshots.py`
- Create: `tests/storage/test_clients.py`
- Create: `tests/storage/test_snapshots.py`

**Interfaces:**
- Consumes: `open_database`, `StorageError` из задачи 1. **Больше ничего:** `storage` не импортирует `scoring` — это соседние слои, а не надстройка. Свой `Answers = dict[str, int]` объявляется локально; структурно он совпадает с одноимённым псевдонимом в `scoring`, поэтому словарь передаётся в `collect_findings` напрямую.
- Produces:
  - `Client(code: str, full_name: str, contacts: str | None, note: str | None)`
  - `ClientRepository(connection)` с методами `add(full_name, contacts=None, note=None) -> Client`, `get(code) -> Client | None`, `all() -> list[Client]`, `next_code() -> str`
  - `Snapshot(id: int, client_code: str, taken_on: date, note: str | None)`
  - `StoredMeasurement(id: int, analyte_id: str, raw_name: str, value: float, units: str, taken_on: date, confirmed: bool)`
  - `SnapshotRepository(connection)` с методами `create(client_code, taken_on, note=None) -> Snapshot`, `get(snapshot_id) -> Snapshot | None`, `for_client(client_code) -> list[Snapshot]`, `add_measurement(...) -> StoredMeasurement`, `measurements(snapshot_id) -> list[StoredMeasurement]`, `confirm_measurement(measurement_id) -> None`, `history(client_code, analyte_id) -> list[StoredMeasurement]`, `save_answers(snapshot_id, answers) -> None`, `answers(snapshot_id) -> Answers`

**Граница реестра.** `SnapshotRepository` не имеет доступа к таблице `identities` и оперирует только кодами клиентов. `ClientRepository` — единственное место, где ФИО и контакты покидают базу. Это та же граница, что `public_view()` у справочника специалистов; тест проверяет, что в модуле срезов слово `identities` не встречается.

- [ ] **Step 1: Написать падающие тесты для клиентов**

Файл `tests/storage/test_clients.py`:

```python
import pytest

from healthcoach.storage.clients import ClientRepository
from healthcoach.storage.db import open_database


@pytest.fixture
def repository(tmp_path):
    with open_database(tmp_path / "db.sqlite") as connection:
        yield ClientRepository(connection)


def test_adds_client_with_generated_code(repository):
    client = repository.add("Иванова Мария Петровна", contacts="@masha")
    assert client.code == "CL-0001"
    assert client.full_name == "Иванова Мария Петровна"
    assert client.contacts == "@masha"


def test_codes_increment(repository):
    first = repository.add("Первая")
    second = repository.add("Вторая")
    assert (first.code, second.code) == ("CL-0001", "CL-0002")


def test_get_returns_none_for_unknown_code(repository):
    assert repository.get("CL-9999") is None


def test_all_is_sorted_by_code(repository):
    repository.add("Вторая")
    repository.add("Первая")
    assert [c.code for c in repository.all()] == ["CL-0001", "CL-0002"]


def test_full_name_is_required(repository):
    with pytest.raises(ValueError, match="ФИО"):
        repository.add("   ")
```

- [ ] **Step 2: Написать падающие тесты для срезов**

Файл `tests/storage/test_snapshots.py`:

```python
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
```

- [ ] **Step 3: Запустить тесты и убедиться, что они падают**

```bash
uv run pytest tests/storage/ -v
```

Ожидается: FAIL с `ModuleNotFoundError: No module named 'healthcoach.storage.clients'`.

- [ ] **Step 4: Реализовать репозиторий клиентов**

Файл `src/healthcoach/storage/clients.py`:

```python
"""Реестр клиентов.

Единственное место, где ФИО и контакты покидают базу. Всё остальное
приложение оперирует кодом клиента: обезличивание в плане 3 опирается
на то, что реестр не читается ниоткуда больше.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass

CODE_PREFIX = "CL-"
CODE_DIGITS = 4


@dataclass(frozen=True)
class Client:
    code: str
    full_name: str
    contacts: str | None
    note: str | None


def _client(row: sqlite3.Row) -> Client:
    return Client(
        code=row["code"],
        full_name=row["full_name"],
        contacts=row["contacts"],
        note=row["note"],
    )


class ClientRepository:
    """Клиенты и соответствие кода реальному имени."""

    def __init__(self, connection: sqlite3.Connection) -> None:
        self._connection = connection

    def next_code(self) -> str:
        """Следующий свободный код вида CL-0007."""
        rows = self._connection.execute("SELECT code FROM identities").fetchall()
        used = {
            int(row["code"][len(CODE_PREFIX) :])
            for row in rows
            if row["code"].startswith(CODE_PREFIX)
            and row["code"][len(CODE_PREFIX) :].isdigit()
        }
        return f"{CODE_PREFIX}{max(used, default=0) + 1:0{CODE_DIGITS}d}"

    def add(
        self, full_name: str, contacts: str | None = None, note: str | None = None
    ) -> Client:
        if not full_name.strip():
            raise ValueError("ФИО клиента не может быть пустым")
        code = self.next_code()
        self._connection.execute(
            "INSERT INTO identities (code, full_name, contacts, note) VALUES (?, ?, ?, ?)",
            (code, full_name.strip(), contacts, note),
        )
        self._connection.commit()
        return Client(code=code, full_name=full_name.strip(), contacts=contacts, note=note)

    def get(self, code: str) -> Client | None:
        row = self._connection.execute(
            "SELECT * FROM identities WHERE code = ?", (code,)
        ).fetchone()
        return _client(row) if row is not None else None

    def all(self) -> list[Client]:
        rows = self._connection.execute(
            "SELECT * FROM identities ORDER BY code"
        ).fetchall()
        return [_client(row) for row in rows]
```

- [ ] **Step 5: Реализовать репозиторий срезов**

Файл `src/healthcoach/storage/snapshots.py`:

```python
"""Срезы клиента: измерения и ответы опросника.

Модуль оперирует только кодом клиента и не имеет доступа к его имени.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import date

Answers = dict[str, int]


@dataclass(frozen=True)
class Snapshot:
    id: int
    client_code: str
    taken_on: date
    note: str | None


@dataclass(frozen=True)
class StoredMeasurement:
    id: int
    analyte_id: str
    raw_name: str
    value: float
    units: str
    taken_on: date
    confirmed: bool


def _snapshot(row: sqlite3.Row) -> Snapshot:
    return Snapshot(
        id=row["id"],
        client_code=row["client_code"],
        taken_on=date.fromisoformat(row["taken_on"]),
        note=row["note"],
    )


def _measurement(row: sqlite3.Row) -> StoredMeasurement:
    return StoredMeasurement(
        id=row["id"],
        analyte_id=row["analyte_id"],
        raw_name=row["raw_name"],
        value=row["value"],
        units=row["units"],
        taken_on=date.fromisoformat(row["taken_on"]),
        confirmed=bool(row["confirmed"]),
    )


class SnapshotRepository:
    """Срезы, измерения и ответы. Имён клиентов не видит."""

    def __init__(self, connection: sqlite3.Connection) -> None:
        self._connection = connection

    def create(
        self, client_code: str, taken_on: date, note: str | None = None
    ) -> Snapshot:
        cursor = self._connection.execute(
            "INSERT INTO snapshots (client_code, taken_on, note) VALUES (?, ?, ?)",
            (client_code, taken_on.isoformat(), note),
        )
        self._connection.commit()
        return Snapshot(
            id=cursor.lastrowid, client_code=client_code, taken_on=taken_on, note=note
        )

    def get(self, snapshot_id: int) -> Snapshot | None:
        row = self._connection.execute(
            "SELECT * FROM snapshots WHERE id = ?", (snapshot_id,)
        ).fetchone()
        return _snapshot(row) if row is not None else None

    def for_client(self, client_code: str) -> list[Snapshot]:
        rows = self._connection.execute(
            "SELECT * FROM snapshots WHERE client_code = ? ORDER BY taken_on, id",
            (client_code,),
        ).fetchall()
        return [_snapshot(row) for row in rows]

    def add_measurement(
        self,
        snapshot_id: int,
        analyte_id: str,
        raw_name: str,
        value: float,
        units: str,
        taken_on: date,
        document_id: int | None = None,
    ) -> StoredMeasurement:
        cursor = self._connection.execute(
            "INSERT INTO measurements "
            "(snapshot_id, analyte_id, raw_name, value, units, taken_on, document_id, confirmed) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, 0)",
            (
                snapshot_id,
                analyte_id,
                raw_name,
                value,
                units,
                taken_on.isoformat(),
                document_id,
            ),
        )
        self._connection.commit()
        return StoredMeasurement(
            id=cursor.lastrowid,
            analyte_id=analyte_id,
            raw_name=raw_name,
            value=value,
            units=units,
            taken_on=taken_on,
            confirmed=False,
        )

    def measurements(self, snapshot_id: int) -> list[StoredMeasurement]:
        rows = self._connection.execute(
            "SELECT * FROM measurements WHERE snapshot_id = ? ORDER BY id",
            (snapshot_id,),
        ).fetchall()
        return [_measurement(row) for row in rows]

    def confirm_measurement(self, measurement_id: int) -> None:
        self._connection.execute(
            "UPDATE measurements SET confirmed = 1 WHERE id = ?", (measurement_id,)
        )
        self._connection.commit()

    def history(self, client_code: str, analyte_id: str) -> list[StoredMeasurement]:
        """Все измерения показателя по клиенту, по дате забора."""
        rows = self._connection.execute(
            "SELECT m.* FROM measurements m "
            "JOIN snapshots s ON s.id = m.snapshot_id "
            "WHERE s.client_code = ? AND m.analyte_id = ? "
            "ORDER BY m.taken_on, m.id",
            (client_code, analyte_id),
        ).fetchall()
        return [_measurement(row) for row in rows]

    def save_answers(self, snapshot_id: int, answers: Answers) -> None:
        """Заменить ответы среза целиком."""
        with self._connection:
            self._connection.execute(
                "DELETE FROM answers WHERE snapshot_id = ?", (snapshot_id,)
            )
            self._connection.executemany(
                "INSERT INTO answers (snapshot_id, question_id, score) VALUES (?, ?, ?)",
                [(snapshot_id, qid, score) for qid, score in answers.items()],
            )

    def answers(self, snapshot_id: int) -> Answers:
        rows = self._connection.execute(
            "SELECT question_id, score FROM answers WHERE snapshot_id = ?",
            (snapshot_id,),
        ).fetchall()
        return {row["question_id"]: row["score"] for row in rows}
```

- [ ] **Step 6: Запустить тесты**

```bash
uv run pytest tests/storage/ -v
```

Ожидается: 14 PASS (5 по клиентам, 9 по срезам).

- [ ] **Step 7: Прогнать весь набор**

```bash
uv run pytest -q
```

Ожидается: 157 проходящих.

- [ ] **Step 8: Коммит**

```bash
git add src/healthcoach/storage tests/storage
git commit -m "feat: репозитории клиентов и срезов с границей реестра имён"
```

---

### Task 3: Конвертация единиц

**Files:**
- Create: `src/healthcoach/knowledge/units.py`
- Modify: `src/healthcoach/knowledge/references.py` — читать `синонимы_единиц` и `пересчёт`
- Modify: `knowledge/references/ferritin.yaml` — добавить синонимы единиц
- Create: `tests/knowledge/test_units.py`
- Modify: `tests/knowledge/test_references_model.py` — тест на разбор новых ключей

**Interfaces:**
- Consumes: `Analyte`, `References`, `ReferenceError` из `healthcoach.knowledge.references`
- Produces:
  - `Conversion(from_units: str, factor: float)` — поле `пересчёт` в YAML
  - `Analyte.unit_aliases: tuple[str, ...]`, `Analyte.conversions: tuple[Conversion, ...]`
  - `UnitError(Exception)`
  - `normalize_units(units: str) -> str`
  - `convert_to_reference(analyte: Analyte, value: float, units: str) -> float` — поднимает `UnitError`, если пересчёт неизвестен

**Почему коуч объявляет пересчёт, а не система вычисляет.** Пересчёт между массовыми и молярными единицами требует молярной массы и различается по показателям; таблица «на все случаи» была бы источником тихих ошибок. Здесь два механизма, оба явные: **синонимы единиц** — разные написания одного и того же (`нг/мл`, `мкг/л`, `ng/mL`), арифметики нет вовсе; и **пересчёт** — множитель, который коуч выписывает сам. Всё, чего нет ни там, ни там, даёт `UnitError`, а вызывающий код превращает её в статус «единицы не сопоставлены».

- [ ] **Step 1: Написать падающие тесты**

Файл `tests/knowledge/test_units.py`:

```python
from pathlib import Path

import pytest

from healthcoach.knowledge.references import load_references
from healthcoach.knowledge.units import UnitError, convert_to_reference, normalize_units

REFS = Path(__file__).parents[2] / "knowledge" / "references"


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("нг/мл", "нг/мл"),
        ("  НГ/МЛ  ", "нг/мл"),
        ("нг / мл", "нг/мл"),
        ("ng/mL", "ng/ml"),
        ("мкг/л", "мкг/л"),
    ],
)
def test_normalize_units(raw, expected):
    assert normalize_units(raw) == expected


def test_same_units_pass_through():
    ferritin = load_references(REFS).analyte("ферритин")
    assert convert_to_reference(ferritin, 18.0, "нг/мл") == 18.0


def test_alias_needs_no_arithmetic():
    """мкг/л и нг/мл — одно и то же число, пересчитывать нечего."""
    ferritin = load_references(REFS).analyte("ферритин")
    assert convert_to_reference(ferritin, 18.0, "мкг/л") == 18.0
    assert convert_to_reference(ferritin, 18.0, "ng/mL") == 18.0


def test_alias_matching_ignores_case_and_spaces():
    ferritin = load_references(REFS).analyte("ферритин")
    assert convert_to_reference(ferritin, 18.0, " МКГ / Л ") == 18.0


def test_unknown_units_raise_naming_both():
    ferritin = load_references(REFS).analyte("ферритин")
    with pytest.raises(UnitError) as excinfo:
        convert_to_reference(ferritin, 18.0, "пмоль/л")
    message = str(excinfo.value)
    assert "ферритин" in message
    assert "пмоль/л" in message
    assert "нг/мл" in message


def test_declared_conversion_is_applied(tmp_path):
    (tmp_path / "glucose.yaml").write_text(
        "показатели:\n"
        "  - id: глюкоза\n"
        "    название: Глюкоза\n"
        "    единицы: ммоль/л\n"
        "    пересчёт:\n"
        "      - из: мг/дл\n"
        "        множитель: 0.0555\n"
        "    целевые:\n"
        "      - оптимум: [4.1, 5.3]\n",
        encoding="utf-8",
    )
    glucose = load_references(tmp_path).analyte("глюкоза")
    assert convert_to_reference(glucose, 90.0, "мг/дл") == pytest.approx(4.995)


def test_conversion_without_multiplier_is_refused(tmp_path):
    (tmp_path / "bad.yaml").write_text(
        "показатели:\n"
        "  - id: x\n"
        "    название: Икс\n"
        "    единицы: ед\n"
        "    пересчёт:\n"
        "      - из: другие\n"
        "    целевые:\n"
        "      - оптимум: [1, 2]\n",
        encoding="utf-8",
    )
    from healthcoach.knowledge.references import ReferenceError

    with pytest.raises(ReferenceError, match="множитель"):
        load_references(tmp_path)
```

- [ ] **Step 2: Запустить тесты и убедиться, что они падают**

```bash
uv run pytest tests/knowledge/test_units.py -v
```

Ожидается: FAIL с `ModuleNotFoundError: No module named 'healthcoach.knowledge.units'`.

- [ ] **Step 3: Расширить модель референсов**

В `src/healthcoach/knowledge/references.py` добавить датакласс рядом с `Interval`:

```python
@dataclass(frozen=True)
class Conversion:
    """Объявленный коучем пересчёт в единицы референса."""

    from_units: str
    factor: float
```

Добавить два поля в `Analyte`, после `units`:

```python
    unit_aliases: tuple[str, ...]
    conversions: tuple[Conversion, ...]
```

Добавить разбор перед функцией `_analyte`:

```python
def _conversion(raw: dict, where: str) -> Conversion:
    if "множитель" not in raw:
        raise ReferenceError(f"{where}: у пересчёта нет ключа 'множитель'")
    if "из" not in raw:
        raise ReferenceError(f"{where}: у пересчёта нет ключа 'из'")
    try:
        factor = float(raw["множитель"])
    except (TypeError, ValueError) as exc:
        raise ReferenceError(
            f"{where}: множитель должен быть числом, получено {raw['множитель']!r}"
        ) from exc
    return Conversion(from_units=str(raw["из"]), factor=factor)
```

И заполнить новые поля в теле `_analyte`, в конструкторе `Analyte(...)`:

```python
        unit_aliases=tuple(str(u) for u in raw.get("синонимы_единиц", ())),
        conversions=tuple(_conversion(c, where) for c in raw.get("пересчёт", ())),
```

- [ ] **Step 4: Реализовать конвертацию**

Файл `src/healthcoach/knowledge/units.py`:

```python
"""Единицы измерения показателей.

Два механизма, оба объявляет коуч. Синонимы — разные написания одной и той
же единицы (нг/мл, мкг/л, ng/mL), арифметики нет вовсе. Пересчёт — множитель,
выписанный коучем для конкретного показателя. Всё остальное — ошибка:
таблица пересчётов «на все случаи» была бы источником тихих ошибок, потому
что перевод между массовыми и молярными единицами зависит от молярной массы.
"""

from __future__ import annotations

import re

from healthcoach.knowledge.references import Analyte

_SPACES = re.compile(r"\s+")


class UnitError(Exception):
    """Единицы измерения не сопоставлены с единицами референса."""


def normalize_units(units: str) -> str:
    """Привести запись единиц к виду, в котором они сравниваются."""
    return _SPACES.sub("", units).strip().casefold()


def convert_to_reference(analyte: Analyte, value: float, units: str) -> float:
    """Перевести значение в единицы референса показателя."""
    given = normalize_units(units)

    if given == normalize_units(analyte.units):
        return value

    for alias in analyte.unit_aliases:
        if given == normalize_units(alias):
            return value

    for conversion in analyte.conversions:
        if given == normalize_units(conversion.from_units):
            return value * conversion.factor

    known = [analyte.units, *analyte.unit_aliases, *(c.from_units for c in analyte.conversions)]
    raise UnitError(
        f"показатель {analyte.id!r}: единицы {units!r} не сопоставлены; "
        f"референс задан в {analyte.units!r}, известны также {known[1:]!r}"
    )
```

- [ ] **Step 5: Добавить синонимы единиц ферритину**

В `knowledge/references/ferritin.yaml`, сразу после строки `единицы: нг/мл`:

```yaml
    синонимы_единиц: [мкг/л, ug/L, ng/mL, ug/l, ng/ml]
```

- [ ] **Step 6: Добавить тест на разбор новых ключей**

Дописать в `tests/knowledge/test_references_model.py`:

```python
def test_unit_aliases_and_conversions_are_parsed(tmp_path):
    (tmp_path / "x.yaml").write_text(
        "показатели:\n"
        "  - id: глюкоза\n"
        "    название: Глюкоза\n"
        "    единицы: ммоль/л\n"
        "    синонимы_единиц: [mmol/L]\n"
        "    пересчёт:\n"
        "      - из: мг/дл\n"
        "        множитель: 0.0555\n"
        "    целевые:\n"
        "      - оптимум: [4.1, 5.3]\n",
        encoding="utf-8",
    )
    glucose = load_references(tmp_path).analyte("глюкоза")
    assert glucose.unit_aliases == ("mmol/L",)
    assert glucose.conversions[0].from_units == "мг/дл"
    assert glucose.conversions[0].factor == 0.0555


def test_analytes_without_the_new_keys_still_load(tmp_path):
    (tmp_path / "x.yaml").write_text(
        "показатели:\n"
        "  - id: x\n"
        "    название: Икс\n"
        "    единицы: ед\n"
        "    целевые:\n"
        "      - оптимум: [1, 2]\n",
        encoding="utf-8",
    )
    analyte = load_references(tmp_path).analyte("x")
    assert analyte.unit_aliases == ()
    assert analyte.conversions == ()
```

- [ ] **Step 7: Запустить тесты**

```bash
uv run pytest tests/knowledge/ -v
```

Ожидается: все проходят, включая 12 новых (10 в `test_units.py`, 2 в `test_references_model.py`).

- [ ] **Step 8: Прогнать весь набор**

```bash
uv run pytest -q
```

Ожидается: 163 проходящих.

- [ ] **Step 9: Коммит**

```bash
git add src/healthcoach/knowledge/units.py src/healthcoach/knowledge/references.py \
        knowledge/references/ferritin.yaml \
        tests/knowledge/test_units.py tests/knowledge/test_references_model.py
git commit -m "feat: синонимы единиц и объявленный коучем пересчёт"
```

---

### Task 4: Распознавание показателя из строки бланка

**Files:**
- Create: `src/healthcoach/intake/__init__.py`
- Create: `src/healthcoach/intake/resolve.py`
- Create: `tests/intake/test_resolve.py`

**Interfaces:**
- Consumes: `References`, `Analyte` из `healthcoach.knowledge.references`
- Produces:
  - `Resolution(analyte: Analyte | None, candidates: tuple[Analyte, ...], raw_name: str)`
  - `Resolution.is_certain: bool`, `Resolution.is_unknown: bool`, `Resolution.is_ambiguous: bool`
  - `resolve_analyte(references: References, raw_name: str) -> Resolution`

**Правило.** Строка из бланка приходит в живом виде: `«Ферритин (S-Ferritin)»`, `«ФЕРРИТИН, нг/мл»`, `«Ферритин*»`. Распознавание чистит строку и ищет точное совпадение среди идентификаторов, названий и синонимов. Неоднозначность — когда подходит больше одного показателя — **не разрешается угадыванием**: возвращаются все кандидаты, а выбор делает коуч на экране сверки. Ничего не найдено — `analyte is None`, и коуч видит строку как нераспознанную.

- [ ] **Step 1: Написать падающие тесты**

Файл `tests/intake/test_resolve.py`:

```python
from pathlib import Path

import pytest

from healthcoach.intake.resolve import resolve_analyte
from healthcoach.knowledge.references import load_references

REFS = Path(__file__).parents[2] / "knowledge" / "references"


@pytest.fixture
def references():
    return load_references(REFS)


@pytest.mark.parametrize(
    "raw",
    [
        "Ферритин",
        "ферритин",
        "ФЕРРИТИН",
        "  Ферритин  ",
        "Ферритин (S-Ferritin)",
        "Ферритин, нг/мл",
        "Ферритин*",
        "Ferritin",
        "S-Ferritin",
    ],
)
def test_recognises_ferritin_in_its_many_spellings(references, raw):
    resolution = resolve_analyte(references, raw)
    assert resolution.is_certain
    assert resolution.analyte.id == "ферритин"
    assert resolution.raw_name == raw


def test_unknown_name_is_reported_not_guessed(references):
    resolution = resolve_analyte(references, "Гомоцистеин")
    assert resolution.is_unknown
    assert resolution.analyte is None
    assert resolution.candidates == ()


def test_ambiguous_name_returns_all_candidates(tmp_path):
    (tmp_path / "two.yaml").write_text(
        "показатели:\n"
        "  - id: витамин_д_25oh\n"
        "    название: Витамин D\n"
        "    синонимы: [Витамин D]\n"
        "    единицы: нг/мл\n"
        "    целевые:\n"
        "      - оптимум: [50, 80]\n"
        "  - id: витамин_д_125oh\n"
        "    название: Витамин D активный\n"
        "    синонимы: [Витамин D]\n"
        "    единицы: пг/мл\n"
        "    целевые:\n"
        "      - оптимум: [20, 60]\n",
        encoding="utf-8",
    )
    references = load_references(tmp_path)
    resolution = resolve_analyte(references, "Витамин D")
    assert resolution.is_ambiguous
    assert resolution.analyte is None
    assert {a.id for a in resolution.candidates} == {
        "витамин_д_25oh",
        "витамин_д_125oh",
    }


def test_empty_name_is_unknown(references):
    assert resolve_analyte(references, "   ").is_unknown


def test_certainty_flags_are_mutually_exclusive(references):
    for raw in ("Ферритин", "Гомоцистеин", ""):
        resolution = resolve_analyte(references, raw)
        flags = [
            resolution.is_certain,
            resolution.is_unknown,
            resolution.is_ambiguous,
        ]
        assert sum(flags) == 1
```

- [ ] **Step 2: Запустить тесты и убедиться, что они падают**

```bash
uv run pytest tests/intake/test_resolve.py -v
```

Ожидается: FAIL с `ModuleNotFoundError: No module named 'healthcoach.intake'`.

- [ ] **Step 3: Реализовать распознавание**

Файл `src/healthcoach/intake/__init__.py`:

```python
"""Приём данных: опросник, ответы клиента, распознавание показателей."""
```

Файл `src/healthcoach/intake/resolve.py`:

```python
"""Распознавание показателя по строке из бланка анализов.

Строка приходит в живом виде: «Ферритин (S-Ferritin)», «ФЕРРИТИН, нг/мл»,
«Ферритин*». Совпадение ищется точное, по очищенной строке; неоднозначность
не разрешается угадыванием — кандидаты возвращаются коучу на сверку.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from healthcoach.knowledge.references import Analyte, References

_NOISE = re.compile(r"[*†‡]|\(.*?\)|\[.*?\]")
_TRAILING = re.compile(r"[\s,;:.\-–—]+$")
_SPACES = re.compile(r"\s+")


@dataclass(frozen=True)
class Resolution:
    """Итог распознавания одной строки бланка."""

    analyte: Analyte | None
    candidates: tuple[Analyte, ...]
    raw_name: str

    @property
    def is_certain(self) -> bool:
        return self.analyte is not None

    @property
    def is_ambiguous(self) -> bool:
        return self.analyte is None and len(self.candidates) > 1

    @property
    def is_unknown(self) -> bool:
        return self.analyte is None and not self.candidates


def _clean(raw_name: str) -> str:
    """Убрать сноски, скобочные уточнения и хвостовые единицы."""
    text = _NOISE.sub(" ", raw_name)
    text = text.split(",")[0]
    text = _TRAILING.sub("", text)
    return _SPACES.sub(" ", text).strip().casefold()


def _keys(analyte: Analyte) -> set[str]:
    return {
        _clean(name) for name in (analyte.id, analyte.name, *analyte.synonyms) if name
    }


def resolve_analyte(references: References, raw_name: str) -> Resolution:
    """Найти показатель по строке бланка."""
    cleaned = _clean(raw_name)
    if not cleaned:
        return Resolution(analyte=None, candidates=(), raw_name=raw_name)

    matched = tuple(
        analyte for analyte in references.analytes if cleaned in _keys(analyte)
    )
    if len(matched) == 1:
        return Resolution(analyte=matched[0], candidates=matched, raw_name=raw_name)
    return Resolution(analyte=None, candidates=matched, raw_name=raw_name)
```

- [ ] **Step 4: Запустить тесты**

```bash
uv run pytest tests/intake/test_resolve.py -v
```

Ожидается: 15 PASS (9 параметризованных плюс 6 обычных).

- [ ] **Step 5: Коммит**

```bash
git add src/healthcoach/intake tests/intake
git commit -m "feat: распознавание показателя по строке бланка без угадывания"
```

---

### Task 5: Генератор автономного HTML-опросника

**Files:**
- Create: `src/healthcoach/intake/questionnaire_html.py`
- Create: `tests/intake/test_questionnaire_html.py`

**Interfaces:**
- Consumes: `Questionnaire`, `Block`, `Question` из `healthcoach.knowledge.questionnaire`
- Produces:
  - `render_questionnaire(questionnaire: Questionnaire, client_code: str, extra_block_ids: Sequence[str] = ()) -> str`
  - `QuestionnaireHtmlError(Exception)`

**Требования к файлу.** Один HTML без внешних ссылок: клиент открывает его в браузере, в том числе на телефоне. Ядро (организационная и клиническая части) включено всегда; дополнительные опросники — только те, что коуч перечислил в `extra_block_ids`. Прогресс сохраняется в `localStorage` под ключом с кодом клиента, чтобы можно было закрыть и вернуться. Кнопка «Скачать ответы» отдаёт JSON.

- [ ] **Step 1: Написать падающие тесты**

Файл `tests/intake/test_questionnaire_html.py`:

```python
import json
import re
from pathlib import Path

import pytest

from healthcoach.intake.questionnaire_html import (
    QuestionnaireHtmlError,
    render_questionnaire,
)
from healthcoach.knowledge.questionnaire import load_questionnaire

SPEC = Path(__file__).parents[2] / "knowledge" / "questionnaire.yaml"


@pytest.fixture(scope="module")
def questionnaire():
    return load_questionnaire(SPEC)


def test_core_blocks_are_always_included(questionnaire):
    html = render_questionnaire(questionnaire, "CL-0001")
    for block in questionnaire.blocks:
        if block.core:
            assert block.title in html


def test_extra_blocks_are_excluded_by_default(questionnaire):
    html = render_questionnaire(questionnaire, "CL-0001")
    candida = questionnaire.block("oprosnik_candida")
    assert candida.title not in html


def test_requested_extra_block_is_included(questionnaire):
    html = render_questionnaire(
        questionnaire, "CL-0001", extra_block_ids=["oprosnik_candida"]
    )
    assert questionnaire.block("oprosnik_candida").title in html


def test_unknown_extra_block_is_refused(questionnaire):
    with pytest.raises(QuestionnaireHtmlError, match="нет блока"):
        render_questionnaire(questionnaire, "CL-0001", extra_block_ids=["выдуманный"])


def test_requesting_a_core_block_as_extra_is_refused(questionnaire):
    with pytest.raises(QuestionnaireHtmlError, match="входит в ядро"):
        render_questionnaire(questionnaire, "CL-0001", extra_block_ids=["pitanie"])


def test_file_is_self_contained(questionnaire):
    """Клиент открывает файл из мессенджера — внешних загрузок быть не должно."""
    html = render_questionnaire(questionnaire, "CL-0001")
    assert "<script src=" not in html
    assert "<link " not in html
    assert "http://" not in html
    assert "https://" not in html


def test_client_code_is_embedded_for_the_storage_key(questionnaire):
    html = render_questionnaire(questionnaire, "CL-0417")
    assert "CL-0417" in html
    assert "localStorage" in html


def test_every_option_of_every_included_question_is_rendered(questionnaire):
    html = render_questionnaire(questionnaire, "CL-0001")
    block = questionnaire.block("obraz_zizni")
    for question in block.questions:
        for option in question.options():
            expected = f'value="{option.score}"'
            assert expected in html
            assert option.label in html


def test_question_ids_are_present_as_input_names(questionnaire):
    html = render_questionnaire(questionnaire, "CL-0001")
    block = questionnaire.block("obraz_zizni")
    for question in block.questions:
        assert f'name="{question.id}"' in html


def test_answers_payload_shape_is_documented_in_the_page(questionnaire):
    """Файл сам объявляет формат, который потом разбирает импорт."""
    html = render_questionnaire(questionnaire, "CL-0417")
    assert '"версия"' in html
    assert '"клиент"' in html
    assert '"ответы"' in html


def test_html_escapes_question_text(questionnaire):
    """В тексте вопросов встречаются кавычки и угловые скобки."""
    html = render_questionnaire(questionnaire, "CL-0001")
    assert "<script>alert" not in html
    assert re.search(r"<body|<main", html)
```

- [ ] **Step 2: Запустить тесты и убедиться, что они падают**

```bash
uv run pytest tests/intake/test_questionnaire_html.py -v
```

Ожидается: FAIL с `ModuleNotFoundError`.

- [ ] **Step 3: Реализовать генератор**

Файл `src/healthcoach/intake/questionnaire_html.py`:

```python
"""Генератор автономного HTML-опросника для клиента.

Один файл без внешних ссылок: коуч отправляет его в мессенджере, клиент
открывает в браузере, в том числе на телефоне. Прогресс держится в
localStorage, чтобы можно было закрыть и вернуться. По завершении клиент
скачивает JSON и присылает его обратно.
"""

from __future__ import annotations

import html
import json
from collections.abc import Sequence

from healthcoach.knowledge.questionnaire import Block, Questionnaire

PAYLOAD_VERSION = "1.0"


class QuestionnaireHtmlError(Exception):
    """Опросник под клиента собрать нельзя."""


_STYLE = """
:root { color-scheme: light dark; }
* { box-sizing: border-box; }
body { font: 16px/1.5 system-ui, sans-serif; margin: 0; padding: 0 1rem 6rem;
       max-width: 44rem; margin-inline: auto; }
h1 { font-size: 1.4rem; }
h2 { font-size: 1.1rem; margin-top: 2.5rem; border-bottom: 1px solid;
     padding-bottom: .3rem; }
h3 { font-size: .95rem; font-weight: 600; opacity: .75; margin: 1.5rem 0 .5rem; }
.q { margin: 1.25rem 0; }
.q p { margin: 0 0 .4rem; }
.opts { display: grid; gap: .35rem; }
label { display: flex; gap: .5rem; align-items: flex-start; cursor: pointer; }
.bar { position: fixed; inset: auto 0 0 0; padding: .75rem 1rem;
       background: Canvas; border-top: 1px solid; display: flex; gap: 1rem;
       align-items: center; justify-content: space-between; }
button { font: inherit; padding: .5rem 1rem; cursor: pointer; }
.done { opacity: .55; }
"""

_SCRIPT = """
const KEY = 'healthcoach-' + CLIENT_CODE;
const form = document.getElementById('form');

function collect() {
  const data = {};
  for (const el of form.querySelectorAll('input[type=radio]:checked')) {
    data[el.name] = Number(el.value);
  }
  return data;
}

function total() {
  return new Set(
    [...form.querySelectorAll('input[type=radio]')].map((el) => el.name)
  ).size;
}

function refresh() {
  const answered = Object.keys(collect()).length;
  document.getElementById('progress').textContent =
    'Отвечено ' + answered + ' из ' + total();
  for (const q of form.querySelectorAll('.q')) {
    const name = q.dataset.q;
    q.classList.toggle('done', form.querySelector(
      'input[name="' + name + '"]:checked') !== null);
  }
}

function save() {
  localStorage.setItem(KEY, JSON.stringify(collect()));
  refresh();
}

function restore() {
  const raw = localStorage.getItem(KEY);
  if (!raw) return refresh();
  const data = JSON.parse(raw);
  for (const [name, score] of Object.entries(data)) {
    const el = form.querySelector(
      'input[name="' + name + '"][value="' + score + '"]');
    if (el) el.checked = true;
  }
  refresh();
}

function download() {
  const payload = {
    'версия': PAYLOAD_VERSION,
    'клиент': CLIENT_CODE,
    'спецификация': SPEC_VERSION,
    'ответы': collect(),
  };
  const blob = new Blob([JSON.stringify(payload, null, 2)],
                        { type: 'application/json' });
  const a = document.createElement('a');
  a.href = URL.createObjectURL(blob);
  a.download = 'ответы-' + CLIENT_CODE + '.json';
  a.click();
  URL.revokeObjectURL(a.href);
}

form.addEventListener('change', save);
document.getElementById('download').addEventListener('click', download);
restore();
"""


def _selected_blocks(
    questionnaire: Questionnaire, extra_block_ids: Sequence[str]
) -> list[Block]:
    by_id = {block.id: block for block in questionnaire.blocks}
    for block_id in extra_block_ids:
        if block_id not in by_id:
            raise QuestionnaireHtmlError(f"в спецификации нет блока {block_id!r}")
        if by_id[block_id].core:
            raise QuestionnaireHtmlError(
                f"блок {block_id!r} входит в ядро и включается всегда"
            )
    wanted = set(extra_block_ids)
    return [b for b in questionnaire.blocks if b.core or b.id in wanted]


def _render_question(question, subscale_title: str | None) -> str:
    options = "\n".join(
        f'<label><input type="radio" name="{html.escape(question.id)}" '
        f'value="{option.score}"><span>{html.escape(option.label)}</span></label>'
        for option in question.options()
    )
    return (
        f'<div class="q" data-q="{html.escape(question.id)}">'
        f"<p>{question.number}. {html.escape(question.text)}</p>"
        f'<div class="opts">{options}</div></div>'
    )


def render_questionnaire(
    questionnaire: Questionnaire,
    client_code: str,
    extra_block_ids: Sequence[str] = (),
) -> str:
    """Собрать автономный HTML-опросник под конкретного клиента."""
    blocks = _selected_blocks(questionnaire, extra_block_ids)

    sections: list[str] = []
    for block in blocks:
        parts = [f"<h2>{html.escape(block.title)}</h2>"]
        multi = len(block.subscales) > 1
        for subscale in block.subscales:
            ids = set(subscale.question_ids)
            questions = [q for q in block.questions if q.id in ids]
            if not questions:
                continue
            if multi:
                parts.append(f"<h3>{html.escape(subscale.title)}</h3>")
            parts.extend(_render_question(q, subscale.title) for q in questions)
        sections.append("\n".join(parts))

    script = (
        f"const CLIENT_CODE = {json.dumps(client_code, ensure_ascii=False)};\n"
        f"const SPEC_VERSION = {json.dumps(questionnaire.version)};\n"
        f"const PAYLOAD_VERSION = {json.dumps(PAYLOAD_VERSION)};\n"
        f"{_SCRIPT}"
    )

    return (
        "<!doctype html>\n"
        '<html lang="ru"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        f"<title>Опросник — {html.escape(client_code)}</title>"
        f"<style>{_STYLE}</style></head><body>"
        "<main>"
        "<h1>Большой интегральный опросник</h1>"
        "<p>Отвечайте по своему состоянию за последний месяц. "
        "Прогресс сохраняется в браузере — можно закрыть страницу и вернуться. "
        "Когда закончите, нажмите «Скачать ответы» и пришлите файл специалисту.</p>"
        f'<form id="form">{"".join(sections)}</form>'
        "</main>"
        '<div class="bar"><span id="progress"></span>'
        '<button type="button" id="download">Скачать ответы</button></div>'
        f"<script>{script}</script>"
        "</body></html>"
    )
```

- [ ] **Step 4: Запустить тесты**

```bash
uv run pytest tests/intake/test_questionnaire_html.py -v
```

Ожидается: 11 PASS.

- [ ] **Step 5: Посмотреть результат глазами**

```bash
uv run python -c "
from pathlib import Path
from healthcoach.knowledge.questionnaire import load_questionnaire
from healthcoach.intake.questionnaire_html import render_questionnaire
q = load_questionnaire(Path('knowledge/questionnaire.yaml'))
html = render_questionnaire(q, 'CL-0001', extra_block_ids=['oprosnik_candida'])
Path('/tmp/опросник.html').write_text(html, encoding='utf-8')
print(f'{len(html)} символов → /tmp/опросник.html')
"
open /tmp/опросник.html
```

Проверить руками: вопросы читаются, варианты выбираются, счётчик внизу растёт, после перезагрузки страницы ответы на месте, кнопка отдаёт JSON.

- [ ] **Step 6: Коммит**

```bash
git add src/healthcoach/intake/questionnaire_html.py tests/intake/test_questionnaire_html.py
git commit -m "feat: автономный HTML-опросник с сохранением прогресса"
```

---

### Task 6: Импорт присланных ответов

**Files:**
- Create: `src/healthcoach/intake/answers.py`
- Create: `tests/intake/test_answers.py`

**Interfaces:**
- Consumes: `Questionnaire` из `healthcoach.knowledge.questionnaire`; `PAYLOAD_VERSION` из `healthcoach.intake.questionnaire_html`
- Produces:
  - `ImportedAnswers(client_code: str, answers: dict[str, int], skipped: tuple[str, ...])`
  - `parse_answers(questionnaire: Questionnaire, payload: str | bytes) -> ImportedAnswers`
  - `AnswersError(Exception)`

**Правило.** Ответ вне шкалы вопроса — ошибка, а не обрезка. Ответ на вопрос, которого нет в спецификации, — тоже ошибка, но с пояснением: скорее всего опросник собран на другой версии спецификации, и это надо увидеть, а не проглотить. Пропущенные вопросы — нормально, они просто не попадают в результат, и их список возвращается для сведения.

- [ ] **Step 1: Написать падающие тесты**

Файл `tests/intake/test_answers.py`:

```python
import json
from pathlib import Path

import pytest

from healthcoach.intake.answers import AnswersError, parse_answers
from healthcoach.knowledge.questionnaire import load_questionnaire

SPEC = Path(__file__).parents[2] / "knowledge" / "questionnaire.yaml"


@pytest.fixture(scope="module")
def questionnaire():
    return load_questionnaire(SPEC)


def _payload(questionnaire, answers, **overrides):
    body = {
        "версия": "1.0",
        "клиент": "CL-0417",
        "спецификация": questionnaire.version,
        "ответы": answers,
    }
    body.update(overrides)
    return json.dumps(body, ensure_ascii=False)


def test_parses_valid_payload(questionnaire):
    block = questionnaire.block("obraz_zizni")
    answers = {q.id: min(o.score for o in q.options()) for q in block.questions}
    result = parse_answers(questionnaire, _payload(questionnaire, answers))
    assert result.client_code == "CL-0417"
    assert result.answers == answers


def test_accepts_bytes(questionnaire):
    block = questionnaire.block("obraz_zizni")
    answers = {block.questions[0].id: 0}
    payload = _payload(questionnaire, answers).encode("utf-8")
    assert parse_answers(questionnaire, payload).answers == answers


def test_unanswered_questions_are_listed_not_invented(questionnaire):
    block = questionnaire.block("obraz_zizni")
    answered = {block.questions[0].id: 0}
    result = parse_answers(questionnaire, _payload(questionnaire, answered))
    assert block.questions[1].id in result.skipped
    assert block.questions[0].id not in result.skipped


def test_score_outside_the_scale_is_refused(questionnaire):
    block = questionnaire.block("obraz_zizni")
    question = block.questions[0]
    top = max(o.score for o in question.options())
    with pytest.raises(AnswersError, match=question.id):
        parse_answers(questionnaire, _payload(questionnaire, {question.id: top + 1}))


def test_unknown_question_names_the_version_mismatch(questionnaire):
    with pytest.raises(AnswersError) as excinfo:
        parse_answers(questionnaire, _payload(questionnaire, {"выдуманный.1": 0}))
    message = str(excinfo.value)
    assert "выдуманный.1" in message
    assert "версии" in message


def test_broken_json_is_refused(questionnaire):
    with pytest.raises(AnswersError, match="не разобран"):
        parse_answers(questionnaire, "{не json")


def test_missing_answers_key_is_refused(questionnaire):
    with pytest.raises(AnswersError, match="ответы"):
        parse_answers(
            questionnaire,
            json.dumps({"версия": "1.0", "клиент": "CL-0001"}, ensure_ascii=False),
        )


def test_unknown_payload_version_is_refused(questionnaire):
    with pytest.raises(AnswersError, match="версия файла"):
        parse_answers(questionnaire, _payload(questionnaire, {}, **{"версия": "9.9"}))


def test_specification_version_mismatch_is_refused(questionnaire):
    with pytest.raises(AnswersError, match="спецификаци"):
        parse_answers(
            questionnaire, _payload(questionnaire, {}, **{"спецификация": "0.1"})
        )


def test_non_integer_score_is_refused(questionnaire):
    block = questionnaire.block("obraz_zizni")
    payload = _payload(questionnaire, {block.questions[0].id: "два"})
    with pytest.raises(AnswersError, match="целым числом"):
        parse_answers(questionnaire, payload)
```

- [ ] **Step 2: Запустить тесты и убедиться, что они падают**

```bash
uv run pytest tests/intake/test_answers.py -v
```

Ожидается: FAIL с `ModuleNotFoundError`.

- [ ] **Step 3: Реализовать импорт**

Файл `src/healthcoach/intake/answers.py`:

```python
"""Разбор файла с ответами, присланного клиентом."""

from __future__ import annotations

import json
from dataclasses import dataclass

from healthcoach.intake.questionnaire_html import PAYLOAD_VERSION
from healthcoach.knowledge.questionnaire import Questionnaire


class AnswersError(Exception):
    """Файл ответов непригоден."""


@dataclass(frozen=True)
class ImportedAnswers:
    client_code: str
    answers: dict[str, int]
    skipped: tuple[str, ...]


def parse_answers(questionnaire: Questionnaire, payload: str | bytes) -> ImportedAnswers:
    """Разобрать и проверить файл ответов.

    Пропущенные вопросы — нормально: они перечисляются отдельно. Балл вне
    шкалы или вопрос вне спецификации — ошибка: это расхождение версий,
    и увидеть его надо сразу, а не после подсчёта.
    """
    if isinstance(payload, bytes):
        payload = payload.decode("utf-8")

    try:
        body = json.loads(payload)
    except json.JSONDecodeError as exc:
        raise AnswersError(f"файл ответов не разобран как JSON: {exc}") from exc

    if not isinstance(body, dict):
        raise AnswersError("файл ответов должен содержать объект")

    version = body.get("версия")
    if version != PAYLOAD_VERSION:
        raise AnswersError(
            f"версия файла ответов {version!r} не поддерживается, "
            f"ожидается {PAYLOAD_VERSION!r}"
        )

    spec_version = body.get("спецификация")
    if spec_version != questionnaire.version:
        raise AnswersError(
            f"файл собран по спецификации {spec_version!r}, "
            f"а загружена {questionnaire.version!r}"
        )

    raw_answers = body.get("ответы")
    if not isinstance(raw_answers, dict):
        raise AnswersError("в файле ответов нет объекта 'ответы'")

    scales: dict[str, set[int]] = {}
    for block in questionnaire.blocks:
        for question in block.questions:
            scales[question.id] = {o.score for o in question.options()}

    answers: dict[str, int] = {}
    for question_id, score in raw_answers.items():
        if question_id not in scales:
            raise AnswersError(
                f"вопроса {question_id!r} нет в спецификации; "
                f"вероятно, опросник собран по другой версии"
            )
        if not isinstance(score, int) or isinstance(score, bool):
            raise AnswersError(
                f"вопрос {question_id!r}: балл должен быть целым числом, "
                f"получено {score!r}"
            )
        if score not in scales[question_id]:
            raise AnswersError(
                f"вопрос {question_id!r}: балл {score} вне шкалы "
                f"{sorted(scales[question_id])}"
            )
        answers[question_id] = score

    skipped = tuple(qid for qid in scales if qid not in answers)
    return ImportedAnswers(
        client_code=str(body.get("клиент", "")),
        answers=answers,
        skipped=skipped,
    )
```

- [ ] **Step 4: Запустить тесты**

```bash
uv run pytest tests/intake/test_answers.py -v
```

Ожидается: 10 PASS.

- [ ] **Step 5: Проверить сквозной путь генератор → импорт**

Дописать в `tests/intake/test_answers.py`:

```python
def test_round_trip_through_the_generated_page(questionnaire):
    """Формат, который объявляет страница, обязан разбираться импортом."""
    from healthcoach.intake.questionnaire_html import render_questionnaire

    html = render_questionnaire(questionnaire, "CL-0417")
    assert '"версия"' in html and '"спецификация"' in html

    block = questionnaire.block("obraz_zizni")
    answers = {q.id: min(o.score for o in q.options()) for q in block.questions}
    payload = json.dumps(
        {
            "версия": "1.0",
            "клиент": "CL-0417",
            "спецификация": questionnaire.version,
            "ответы": answers,
        },
        ensure_ascii=False,
    )
    assert parse_answers(questionnaire, payload).answers == answers
```

```bash
uv run pytest tests/intake/ -q
```

Ожидается: все проходят.

- [ ] **Step 6: Прогнать весь набор**

```bash
uv run pytest -q
```

Ожидается: 200 проходящих.

- [ ] **Step 7: Коммит**

```bash
git add src/healthcoach/intake/answers.py tests/intake/test_answers.py
git commit -m "feat: импорт ответов клиента с проверкой версий и шкал"
```

---

### Task 7: Каркас приложения и карточка клиента

**Files:**
- Create: `src/healthcoach/app/__init__.py`
- Create: `src/healthcoach/app/deps.py`
- Create: `src/healthcoach/app/main.py`
- Create: `src/healthcoach/app/routes_clients.py`
- Create: `src/healthcoach/app/templates/base.html`
- Create: `src/healthcoach/app/templates/clients.html`
- Create: `src/healthcoach/app/templates/client.html`
- Modify: `pyproject.toml` — добавить `fastapi`, `jinja2`, `python-multipart`, `httpx` в dev
- Create: `tests/app/test_clients_routes.py`

**Interfaces:**
- Consumes: `ClientRepository`, `SnapshotRepository`, `open_database`; `load_questionnaire`, `load_references`, `load_specialists`
- Produces:
  - `Context(questionnaire, references, specialists, clients, snapshots)` — собранное состояние приложения
  - `build_context(data_dir: Path, knowledge_dir: Path) -> Context`
  - `create_app(context: Context) -> FastAPI`
  - Маршруты: `GET /` (список клиентов), `POST /clients` (добавить), `GET /clients/{code}` (карточка), `POST /clients/{code}/snapshots` (новый срез), `GET /clients/{code}/questionnaire` (скачать HTML-опросник)

**Почему приложение собирается из контекста.** База знаний и база данных загружаются один раз при запуске и передаются явно, а не берутся из глобалей. Тесты создают приложение поверх временной базы одной строкой, без монкипатчинга.

- [ ] **Step 1: Добавить зависимости**

В `pyproject.toml`, в `dependencies`:

```toml
    "fastapi>=0.115",
    "jinja2>=3.1",
    "python-multipart>=0.0.9",
    "uvicorn>=0.32",
```

В `[dependency-groups]` → `dev`:

```toml
    "httpx>=0.27",
```

- [ ] **Step 2: Написать падающие тесты**

Файл `tests/app/test_clients_routes.py`:

```python
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from healthcoach.app.deps import build_context
from healthcoach.app.main import create_app

KNOWLEDGE = Path(__file__).parents[2] / "knowledge"


@pytest.fixture
def client(tmp_path):
    context = build_context(data_dir=tmp_path, knowledge_dir=KNOWLEDGE)
    with TestClient(create_app(context)) as test_client:
        yield test_client


def test_empty_client_list_renders(client):
    response = client.get("/")
    assert response.status_code == 200
    assert "Клиенты" in response.text


def test_adding_a_client_shows_it_in_the_list(client):
    client.post("/clients", data={"full_name": "Иванова Мария", "contacts": "@masha"})
    response = client.get("/")
    assert "Иванова Мария" in response.text
    assert "CL-0001" in response.text


def test_client_card_shows_code_and_name(client):
    client.post("/clients", data={"full_name": "Иванова Мария"})
    response = client.get("/clients/CL-0001")
    assert response.status_code == 200
    assert "CL-0001" in response.text
    assert "Иванова Мария" in response.text


def test_unknown_client_is_404(client):
    assert client.get("/clients/CL-9999").status_code == 404


def test_creating_a_snapshot_lists_it_on_the_card(client):
    client.post("/clients", data={"full_name": "Иванова Мария"})
    client.post("/clients/CL-0001/snapshots", data={"taken_on": "2026-09-01"})
    response = client.get("/clients/CL-0001")
    assert "2026-09-01" in response.text


def test_empty_name_is_rejected(client):
    response = client.post("/clients", data={"full_name": "   "})
    assert response.status_code == 400


def test_questionnaire_download_is_html(client):
    client.post("/clients", data={"full_name": "Иванова Мария"})
    response = client.get("/clients/CL-0001/questionnaire")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert "CL-0001" in response.text
    assert "attachment" in response.headers.get("content-disposition", "")


def test_questionnaire_can_include_extra_blocks(client):
    client.post("/clients", data={"full_name": "Иванова Мария"})
    response = client.get(
        "/clients/CL-0001/questionnaire", params={"extra": "oprosnik_candida"}
    )
    assert "ОПРОСНИК CANDIDA" in response.text
```

- [ ] **Step 3: Запустить тесты и убедиться, что они падают**

```bash
uv run pytest tests/app/test_clients_routes.py -v
```

Ожидается: FAIL с `ModuleNotFoundError: No module named 'healthcoach.app'`.

- [ ] **Step 4: Реализовать контекст**

Файл `src/healthcoach/app/__init__.py`:

```python
"""Локальное веб-приложение коуча."""
```

Файл `src/healthcoach/app/deps.py`:

```python
"""Состояние приложения: база знаний и база данных.

Загружается один раз при запуске и передаётся явно, чтобы тесты могли
поднять приложение поверх временной базы без монкипатчинга.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from healthcoach.knowledge.questionnaire import Questionnaire, load_questionnaire
from healthcoach.knowledge.references import References, load_references
from healthcoach.knowledge.specialists import Specialists, load_specialists
from healthcoach.storage.clients import ClientRepository
from healthcoach.storage.db import open_database
from healthcoach.storage.snapshots import SnapshotRepository


@dataclass(frozen=True)
class Context:
    questionnaire: Questionnaire
    references: References
    specialists: Specialists
    clients: ClientRepository
    snapshots: SnapshotRepository
    documents_dir: Path


def build_context(data_dir: Path, knowledge_dir: Path) -> Context:
    """Собрать состояние приложения из папок с данными и базой знаний."""
    documents_dir = data_dir / "documents"
    documents_dir.mkdir(parents=True, exist_ok=True)
    connection = open_database(data_dir / "healthcoach.db")
    return Context(
        questionnaire=load_questionnaire(knowledge_dir / "questionnaire.yaml"),
        references=load_references(knowledge_dir / "references"),
        specialists=load_specialists(knowledge_dir / "specialists.yaml"),
        clients=ClientRepository(connection),
        snapshots=SnapshotRepository(connection),
        documents_dir=documents_dir,
    )
```

- [ ] **Step 5: Реализовать шаблоны**

Файл `src/healthcoach/app/templates/base.html`:

```html
<!doctype html>
<html lang="ru">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{% block title %}Health Coaching{% endblock %}</title>
  <style>
    :root { color-scheme: light dark; }
    * { box-sizing: border-box; }
    body { font: 16px/1.5 system-ui, sans-serif; max-width: 60rem;
           margin-inline: auto; padding: 1rem 1rem 4rem; }
    a { color: inherit; }
    h1 { font-size: 1.4rem; }
    h2 { font-size: 1.1rem; margin-top: 2rem; }
    table { border-collapse: collapse; width: 100%; margin: 1rem 0; }
    th, td { text-align: left; padding: .4rem .6rem; border-bottom: 1px solid; }
    th { font-weight: 600; opacity: .7; font-size: .85rem; }
    form { margin: 1rem 0; display: flex; gap: .5rem; flex-wrap: wrap;
           align-items: end; }
    label { display: grid; gap: .2rem; font-size: .85rem; opacity: .8; }
    input, select, button { font: inherit; padding: .4rem .5rem; }
    nav { margin-bottom: 1.5rem; font-size: .9rem; }
    .muted { opacity: .6; }
    .warn { color: #b45309; }
    .bad { color: #b91c1c; font-weight: 600; }
  </style>
</head>
<body>
  <nav><a href="/">← Клиенты</a></nav>
  {% block body %}{% endblock %}
</body>
</html>
```

Файл `src/healthcoach/app/templates/clients.html`:

```html
{% extends "base.html" %}
{% block title %}Клиенты{% endblock %}
{% block body %}
<h1>Клиенты</h1>

<form method="post" action="/clients">
  <label>ФИО<input name="full_name" required></label>
  <label>Контакты<input name="contacts" placeholder="@nickname"></label>
  <button type="submit">Добавить</button>
</form>

{% if clients %}
<table>
  <tr><th>Код</th><th>ФИО</th><th>Контакты</th></tr>
  {% for client in clients %}
  <tr>
    <td><a href="/clients/{{ client.code }}">{{ client.code }}</a></td>
    <td>{{ client.full_name }}</td>
    <td class="muted">{{ client.contacts or "—" }}</td>
  </tr>
  {% endfor %}
</table>
{% else %}
<p class="muted">Пока никого нет.</p>
{% endif %}
{% endblock %}
```

Файл `src/healthcoach/app/templates/client.html`:

```html
{% extends "base.html" %}
{% block title %}{{ client.code }}{% endblock %}
{% block body %}
<h1>{{ client.full_name }} <span class="muted">{{ client.code }}</span></h1>
{% if client.contacts %}<p class="muted">{{ client.contacts }}</p>{% endif %}

<h2>Опросник для клиента</h2>
<form method="get" action="/clients/{{ client.code }}/questionnaire">
  <label>Дополнительные блоки
    <select name="extra" multiple size="5">
      {% for block in extra_blocks %}
      <option value="{{ block.id }}">{{ block.title }}</option>
      {% endfor %}
    </select>
  </label>
  <button type="submit">Скачать файл</button>
</form>
<p class="muted">Ядро включено всегда. Отправьте файл клиенту в мессенджере.</p>

<h2>Срезы</h2>
<form method="post" action="/clients/{{ client.code }}/snapshots">
  <label>Дата среза<input type="date" name="taken_on" required></label>
  <label>Заметка<input name="note"></label>
  <button type="submit">Создать</button>
</form>

{% if snapshots %}
<table>
  <tr><th>Дата</th><th>Заметка</th><th></th></tr>
  {% for snapshot in snapshots %}
  <tr>
    <td>{{ snapshot.taken_on }}</td>
    <td class="muted">{{ snapshot.note or "—" }}</td>
    <td><a href="/snapshots/{{ snapshot.id }}">открыть</a></td>
  </tr>
  {% endfor %}
</table>
{% else %}
<p class="muted">Срезов пока нет.</p>
{% endif %}
{% endblock %}
```

- [ ] **Step 6: Реализовать маршруты и сборку приложения**

Файл `src/healthcoach/app/routes_clients.py`:

```python
"""Список клиентов, карточка клиента, выдача опросника."""

from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Form, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from healthcoach.app.deps import Context
from healthcoach.intake.questionnaire_html import (
    QuestionnaireHtmlError,
    render_questionnaire,
)


def build_router(context: Context, templates) -> APIRouter:
    router = APIRouter()

    @router.get("/", response_class=HTMLResponse)
    def clients_page(request: Request):
        return templates.TemplateResponse(
            request, "clients.html", {"clients": context.clients.all()}
        )

    @router.post("/clients")
    def add_client(full_name: str = Form(...), contacts: str = Form("")):
        try:
            client = context.clients.add(full_name, contacts=contacts or None)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return RedirectResponse(f"/clients/{client.code}", status_code=303)

    @router.get("/clients/{code}", response_class=HTMLResponse)
    def client_page(request: Request, code: str):
        client = context.clients.get(code)
        if client is None:
            raise HTTPException(status_code=404, detail=f"нет клиента {code}")
        return templates.TemplateResponse(
            request,
            "client.html",
            {
                "client": client,
                "snapshots": context.snapshots.for_client(code),
                "extra_blocks": [
                    b for b in context.questionnaire.blocks if not b.core
                ],
            },
        )

    @router.post("/clients/{code}/snapshots")
    def add_snapshot(code: str, taken_on: str = Form(...), note: str = Form("")):
        if context.clients.get(code) is None:
            raise HTTPException(status_code=404, detail=f"нет клиента {code}")
        try:
            when = date.fromisoformat(taken_on)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="дата в формате ГГГГ-ММ-ДД") from exc
        context.snapshots.create(code, when, note=note or None)
        return RedirectResponse(f"/clients/{code}", status_code=303)

    @router.get("/clients/{code}/questionnaire")
    def questionnaire_file(code: str, extra: list[str] = Query(default=[])):
        if context.clients.get(code) is None:
            raise HTTPException(status_code=404, detail=f"нет клиента {code}")
        try:
            html = render_questionnaire(context.questionnaire, code, extra_block_ids=extra)
        except QuestionnaireHtmlError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return HTMLResponse(
            html,
            headers={
                "content-disposition": f'attachment; filename="questionnaire-{code}.html"'
            },
        )

    return router
```

Файл `src/healthcoach/app/main.py`:

```python
"""Сборка приложения."""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.templating import Jinja2Templates

from healthcoach.app import routes_clients
from healthcoach.app.deps import Context, build_context

TEMPLATES_DIR = Path(__file__).parent / "templates"


def create_app(context: Context) -> FastAPI:
    """Собрать приложение поверх готового контекста."""
    app = FastAPI(title="Health Coaching")
    templates = Jinja2Templates(directory=str(TEMPLATES_DIR))
    app.include_router(routes_clients.build_router(context, templates))
    return app


def run() -> None:
    """Точка входа: uv run python -m healthcoach.app.main"""
    import uvicorn

    root = Path(__file__).resolve().parents[3]
    context = build_context(data_dir=root / "data", knowledge_dir=root / "knowledge")
    uvicorn.run(create_app(context), host="127.0.0.1", port=8765)


if __name__ == "__main__":
    run()
```

- [ ] **Step 7: Запустить тесты**

```bash
uv run pytest tests/app/ -v
```

Ожидается: 8 PASS.

- [ ] **Step 8: Поднять приложение и посмотреть**

```bash
uv run python -m healthcoach.app.main
```

Открыть `http://127.0.0.1:8765`, добавить клиента, создать срез, скачать опросник. Остановить `Ctrl+C`.

- [ ] **Step 9: Коммит**

```bash
git add pyproject.toml uv.lock src/healthcoach/app tests/app
git commit -m "feat: каркас приложения, карточка клиента и выдача опросника"
```

---

### Task 8: Экран среза — ответы, показатели, находки

**Files:**
- Create: `src/healthcoach/app/routes_snapshots.py`
- Create: `src/healthcoach/app/templates/snapshot.html`
- Modify: `src/healthcoach/app/main.py` — подключить маршрутизатор
- Create: `tests/app/test_snapshot_routes.py`

**Interfaces:**
- Consumes: `Context`; `parse_answers`, `AnswersError`; `resolve_analyte`; `convert_to_reference`, `UnitError`; `collect_findings`, `Subject`, `Measurement`
- Produces:
  - Маршруты: `GET /snapshots/{id}`, `POST /snapshots/{id}/answers` (загрузка файла), `POST /snapshots/{id}/measurements` (ручной ввод), `POST /snapshots/{id}/measurements/{mid}/confirm`, `GET /snapshots/{id}/findings`

**Как работает ввод показателя.** Коуч вводит название так, как оно написано в бланке, значение, единицы и дату забора. Система распознаёт показатель и пересчитывает единицы. Если название не распознано или единицы не сопоставлены — измерение **всё равно сохраняется**, но помечается, и на экране видно почему. Находки считаются только по подтверждённым измерениям: это те самые ворота сверки из спецификации.

- [ ] **Step 1: Написать падающие тесты**

Файл `tests/app/test_snapshot_routes.py`:

```python
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from healthcoach.app.deps import build_context
from healthcoach.app.main import create_app

KNOWLEDGE = Path(__file__).parents[2] / "knowledge"


@pytest.fixture
def client(tmp_path):
    context = build_context(data_dir=tmp_path, knowledge_dir=KNOWLEDGE)
    with TestClient(create_app(context)) as test_client:
        yield test_client, context


def _snapshot(test_client) -> int:
    test_client.post("/clients", data={"full_name": "Иванова Мария"})
    test_client.post("/clients/CL-0001/snapshots", data={"taken_on": "2026-09-01"})
    return 1


def test_snapshot_page_renders(client):
    test_client, _ = client
    snapshot_id = _snapshot(test_client)
    response = test_client.get(f"/snapshots/{snapshot_id}")
    assert response.status_code == 200
    assert "CL-0001" in response.text


def test_unknown_snapshot_is_404(client):
    test_client, _ = client
    assert test_client.get("/snapshots/999").status_code == 404


def test_measurement_is_recognised_and_stored(client):
    test_client, context = client
    snapshot_id = _snapshot(test_client)
    test_client.post(
        f"/snapshots/{snapshot_id}/measurements",
        data={
            "raw_name": "Ферритин (S-Ferritin)",
            "value": "18",
            "units": "нг/мл",
            "taken_on": "2026-08-20",
        },
    )
    (stored,) = context.snapshots.measurements(snapshot_id)
    assert stored.analyte_id == "ферритин"
    assert stored.value == 18.0
    assert stored.confirmed is False


def test_alias_units_are_converted_on_entry(client):
    test_client, context = client
    snapshot_id = _snapshot(test_client)
    test_client.post(
        f"/snapshots/{snapshot_id}/measurements",
        data={
            "raw_name": "Ферритин",
            "value": "18",
            "units": "мкг/л",
            "taken_on": "2026-08-20",
        },
    )
    (stored,) = context.snapshots.measurements(snapshot_id)
    assert stored.units == "нг/мл"
    assert stored.value == 18.0


def test_unknown_analyte_is_stored_and_flagged(client):
    test_client, context = client
    snapshot_id = _snapshot(test_client)
    test_client.post(
        f"/snapshots/{snapshot_id}/measurements",
        data={
            "raw_name": "Гомоцистеин",
            "value": "12",
            "units": "мкмоль/л",
            "taken_on": "2026-08-20",
        },
    )
    (stored,) = context.snapshots.measurements(snapshot_id)
    assert stored.analyte_id == ""
    assert stored.raw_name == "Гомоцистеин"

    page = test_client.get(f"/snapshots/{snapshot_id}").text
    assert "не распознан" in page


def test_unmatched_units_are_stored_and_flagged(client):
    test_client, context = client
    snapshot_id = _snapshot(test_client)
    test_client.post(
        f"/snapshots/{snapshot_id}/measurements",
        data={
            "raw_name": "Ферритин",
            "value": "18",
            "units": "пмоль/л",
            "taken_on": "2026-08-20",
        },
    )
    (stored,) = context.snapshots.measurements(snapshot_id)
    assert stored.units == "пмоль/л"
    page = test_client.get(f"/snapshots/{snapshot_id}").text
    assert "единицы" in page


def test_confirming_a_measurement_shows_it_as_confirmed(client):
    test_client, context = client
    snapshot_id = _snapshot(test_client)
    test_client.post(
        f"/snapshots/{snapshot_id}/measurements",
        data={
            "raw_name": "Ферритин",
            "value": "18",
            "units": "нг/мл",
            "taken_on": "2026-08-20",
        },
    )
    (stored,) = context.snapshots.measurements(snapshot_id)
    test_client.post(f"/snapshots/{snapshot_id}/measurements/{stored.id}/confirm")
    (again,) = context.snapshots.measurements(snapshot_id)
    assert again.confirmed is True


def test_answers_upload_is_stored(client):
    test_client, context = client
    snapshot_id = _snapshot(test_client)
    questionnaire = context.questionnaire
    block = questionnaire.block("obraz_zizni")
    answers = {q.id: min(o.score for o in q.options()) for q in block.questions}
    payload = json.dumps(
        {
            "версия": "1.0",
            "клиент": "CL-0001",
            "спецификация": questionnaire.version,
            "ответы": answers,
        },
        ensure_ascii=False,
    ).encode("utf-8")

    response = test_client.post(
        f"/snapshots/{snapshot_id}/answers",
        files={"file": ("ответы.json", payload, "application/json")},
    )
    assert response.status_code in (200, 303)
    assert context.snapshots.answers(snapshot_id) == answers


def test_broken_answers_upload_is_reported(client):
    test_client, _ = client
    snapshot_id = _snapshot(test_client)
    response = test_client.post(
        f"/snapshots/{snapshot_id}/answers",
        files={"file": ("плохо.json", b"{not json", "application/json")},
        follow_redirects=False,
    )
    assert response.status_code == 400


def test_findings_respect_the_sex_parameter(client):
    """Пол влияет на выбор целевого коридора: у мужчин ферритин выше."""
    test_client, context = client
    snapshot_id = _snapshot(test_client)
    test_client.post(
        f"/snapshots/{snapshot_id}/measurements",
        data={
            "raw_name": "Ферритин",
            "value": "70",
            "units": "нг/мл",
            "taken_on": "2026-08-20",
        },
    )
    (stored,) = context.snapshots.measurements(snapshot_id)
    test_client.post(f"/snapshots/{snapshot_id}/measurements/{stored.id}/confirm")

    female = test_client.get(
        f"/snapshots/{snapshot_id}/findings", params={"sex": "ж", "age": 32}
    ).text
    male = test_client.get(
        f"/snapshots/{snapshot_id}/findings", params={"sex": "м", "age": 32}
    ).text
    assert "в целевом" in female
    assert "ниже целевого" in male


def test_findings_use_only_confirmed_measurements(client):
    """Ворота сверки: неподтверждённое измерение в находки не идёт."""
    test_client, context = client
    snapshot_id = _snapshot(test_client)
    test_client.post(
        f"/snapshots/{snapshot_id}/measurements",
        data={
            "raw_name": "Ферритин",
            "value": "18",
            "units": "нг/мл",
            "taken_on": "2026-08-20",
        },
    )
    before = test_client.get(f"/snapshots/{snapshot_id}/findings").text
    assert "Ферритин" not in before

    (stored,) = context.snapshots.measurements(snapshot_id)
    test_client.post(f"/snapshots/{snapshot_id}/measurements/{stored.id}/confirm")
    after = test_client.get(f"/snapshots/{snapshot_id}/findings").text
    assert "Ферритин" in after
    assert "дефицит" in after
```

- [ ] **Step 2: Запустить тесты и убедиться, что они падают**

```bash
uv run pytest tests/app/test_snapshot_routes.py -v
```

Ожидается: FAIL — маршрутов ещё нет, страница отдаёт 404.

- [ ] **Step 3: Реализовать шаблон среза**

Файл `src/healthcoach/app/templates/snapshot.html`:

```html
{% extends "base.html" %}
{% block title %}Срез {{ snapshot.taken_on }}{% endblock %}
{% block body %}
<nav>
  <a href="/clients/{{ snapshot.client_code }}">← {{ snapshot.client_code }}</a>
</nav>
<h1>Срез {{ snapshot.taken_on }}
  <span class="muted">{{ snapshot.client_code }}</span></h1>

<h2>Анкета</h2>
{% if answers_count %}
<p>Загружено ответов: {{ answers_count }}.</p>
{% else %}
<p class="muted">Ответы не загружены.</p>
{% endif %}
<form method="post" action="/snapshots/{{ snapshot.id }}/answers"
      enctype="multipart/form-data">
  <label>Файл ответов<input type="file" name="file" accept=".json" required></label>
  <button type="submit">Загрузить</button>
</form>

<h2>Показатели</h2>
<form method="post" action="/snapshots/{{ snapshot.id }}/measurements">
  <label>Название из бланка<input name="raw_name" required
         placeholder="Ферритин (S-Ferritin)"></label>
  <label>Значение<input name="value" required inputmode="decimal"></label>
  <label>Единицы<input name="units" required placeholder="нг/мл"></label>
  <label>Дата забора<input type="date" name="taken_on" required></label>
  <button type="submit">Добавить</button>
</form>

{% if rows %}
<table>
  <tr>
    <th>Из бланка</th><th>Показатель</th><th>Значение</th>
    <th>Дата забора</th><th>Статус</th><th></th>
  </tr>
  {% for row in rows %}
  <tr>
    <td>{{ row.measurement.raw_name }}</td>
    <td>
      {% if row.problem %}<span class="warn">{{ row.problem }}</span>
      {% else %}{{ row.title }}{% endif %}
    </td>
    <td>{{ row.measurement.value }} {{ row.measurement.units }}</td>
    <td>{{ row.measurement.taken_on }}</td>
    <td>
      {% if row.measurement.confirmed %}подтверждено
      {% else %}<span class="muted">не сверено</span>{% endif %}
    </td>
    <td>
      {% if not row.measurement.confirmed %}
      <form method="post"
            action="/snapshots/{{ snapshot.id }}/measurements/{{ row.measurement.id }}/confirm">
        <button type="submit">Подтвердить</button>
      </form>
      {% endif %}
    </td>
  </tr>
  {% endfor %}
</table>
{% else %}
<p class="muted">Показателей пока нет.</p>
{% endif %}

<h2>Находки</h2>
<p><a href="/snapshots/{{ snapshot.id }}/findings">Открыть находки</a></p>
<p class="muted">В находки идут только подтверждённые показатели.</p>
{% endblock %}
```

- [ ] **Step 4: Реализовать маршруты среза**

Файл `src/healthcoach/app/routes_snapshots.py`:

```python
"""Экран среза: ответы анкеты, ввод показателей, находки."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, PlainTextResponse, RedirectResponse

from healthcoach.app.deps import Context
from healthcoach.intake.answers import AnswersError, parse_answers
from healthcoach.intake.resolve import resolve_analyte
from healthcoach.knowledge.units import UnitError, convert_to_reference
from healthcoach.scoring.findings import collect_findings
from healthcoach.scoring.references import Measurement, Subject

UNRESOLVED = ""
"""analyte_id нераспознанного показателя: он хранится, но не трактуется."""


@dataclass(frozen=True)
class Row:
    measurement: object
    title: str
    problem: str | None


def build_router(context: Context, templates) -> APIRouter:
    router = APIRouter()

    def _snapshot_or_404(snapshot_id: int):
        snapshot = context.snapshots.get(snapshot_id)
        if snapshot is None:
            raise HTTPException(status_code=404, detail=f"нет среза {snapshot_id}")
        return snapshot

    def _rows(snapshot_id: int) -> list[Row]:
        rows: list[Row] = []
        for measurement in context.snapshots.measurements(snapshot_id):
            if not measurement.analyte_id:
                rows.append(
                    Row(measurement, measurement.raw_name, "показатель не распознан")
                )
                continue
            analyte = context.references.analyte(measurement.analyte_id)
            if analyte is None:
                rows.append(
                    Row(measurement, measurement.analyte_id, "показатель не распознан")
                )
                continue
            problem = None
            if measurement.units.strip().casefold() != analyte.units.strip().casefold():
                problem = f"единицы не сопоставлены: {measurement.units}"
            rows.append(Row(measurement, analyte.name, problem))
        return rows

    @router.get("/snapshots/{snapshot_id}", response_class=HTMLResponse)
    def snapshot_page(request: Request, snapshot_id: int):
        snapshot = _snapshot_or_404(snapshot_id)
        return templates.TemplateResponse(
            request,
            "snapshot.html",
            {
                "snapshot": snapshot,
                "rows": _rows(snapshot_id),
                "answers_count": len(context.snapshots.answers(snapshot_id)),
            },
        )

    @router.post("/snapshots/{snapshot_id}/answers")
    async def upload_answers(snapshot_id: int, file: UploadFile = File(...)):
        _snapshot_or_404(snapshot_id)
        payload = await file.read()
        try:
            imported = parse_answers(context.questionnaire, payload)
        except AnswersError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        context.snapshots.save_answers(snapshot_id, imported.answers)
        return RedirectResponse(f"/snapshots/{snapshot_id}", status_code=303)

    @router.post("/snapshots/{snapshot_id}/measurements")
    def add_measurement(
        snapshot_id: int,
        raw_name: str = Form(...),
        value: str = Form(...),
        units: str = Form(...),
        taken_on: str = Form(...),
    ):
        _snapshot_or_404(snapshot_id)
        try:
            number = float(value.replace(",", "."))
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="значение должно быть числом") from exc
        try:
            when = date.fromisoformat(taken_on)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="дата в формате ГГГГ-ММ-ДД") from exc

        resolution = resolve_analyte(context.references, raw_name)
        analyte_id, stored_value, stored_units = UNRESOLVED, number, units
        if resolution.is_certain:
            analyte_id = resolution.analyte.id
            try:
                stored_value = convert_to_reference(resolution.analyte, number, units)
                stored_units = resolution.analyte.units
            except UnitError:
                stored_value, stored_units = number, units

        context.snapshots.add_measurement(
            snapshot_id,
            analyte_id=analyte_id,
            raw_name=raw_name,
            value=stored_value,
            units=stored_units,
            taken_on=when,
        )
        return RedirectResponse(f"/snapshots/{snapshot_id}", status_code=303)

    @router.post("/snapshots/{snapshot_id}/measurements/{measurement_id}/confirm")
    def confirm(snapshot_id: int, measurement_id: int):
        _snapshot_or_404(snapshot_id)
        context.snapshots.confirm_measurement(measurement_id)
        return RedirectResponse(f"/snapshots/{snapshot_id}", status_code=303)

    @router.get("/snapshots/{snapshot_id}/findings", response_class=PlainTextResponse)
    def findings(snapshot_id: int, sex: str = "ж", age: int = 35):
        """Находки текстом: полноценный отчёт собирает план 4.

        Пол и возраст пока приходят параметрами запроса со значениями по
        умолчанию: их место в карточке клиента, но туда они попадут вместе
        с обезличиванием, которому нужны те же поля. Так они хотя бы
        задаются снаружи, а не зашиты в код.
        """
        snapshot = _snapshot_or_404(snapshot_id)
        measurements = [
            Measurement(m.analyte_id, m.value, m.units)
            for m in context.snapshots.measurements(snapshot_id)
            if m.confirmed and m.analyte_id
        ]
        found = collect_findings(
            context.questionnaire,
            context.references,
            context.snapshots.answers(snapshot_id),
            measurements,
            Subject(sex=sex, age=age),
        )
        lines = [f"Срез {snapshot.taken_on}, клиент {snapshot.client_code}", ""]
        for finding in found:
            value = "—" if finding.value is None else finding.value
            lines.append(
                f"[{finding.kind}] {finding.title}: {value} {finding.units} "
                f"— {finding.status}"
                + (f" ({finding.note})" if finding.note else "")
            )
        return "\n".join(lines)

    return router
```

- [ ] **Step 5: Подключить маршрутизатор**

В `src/healthcoach/app/main.py` добавить импорт и строку подключения:

```python
from healthcoach.app import routes_clients, routes_snapshots
```

```python
    app.include_router(routes_snapshots.build_router(context, templates))
```

- [ ] **Step 6: Запустить тесты**

```bash
uv run pytest tests/app/ -v
```

Ожидается: 19 PASS.

- [ ] **Step 7: Прогнать весь набор**

```bash
uv run pytest -q
```

Ожидается: 219 проходящих.

- [ ] **Step 8: Пройти сквозной путь руками**

```bash
uv run python -m healthcoach.app.main
```

1. Добавить клиента, создать срез.
2. Скачать опросник, заполнить в браузере несколько блоков, скачать ответы.
3. Загрузить файл ответов в срез.
4. Ввести ферритин 18 нг/мл, подтвердить.
5. Открыть находки — дефицит ферритина и степени по заполненным блокам.

- [ ] **Step 9: Коммит**

```bash
git add src/healthcoach/app tests/app
git commit -m "feat: экран среза с ручным вводом показателей и воротами сверки"
```

---

## Что дальше

**План 3 — документы.** Чтение PDF через pdfplumber, адаптер `OCREngine` поверх распознавания изображений, автозаполнение формы показателей из выгрузки лаборатории. Требует реальных выгрузок в `samples/`: без них разбор форматов — гадание. Экран сверки из задачи 8 остаётся тем же, меняется только источник строк.

**План 4 — интерпретация и отчёт.** Обезличивание с обязательным тестом на утечку, адаптер `LLMProvider` поверх `claude -p`, сборка черновика с привязкой к находкам, экран правки и утверждения, PDF через WeasyPrint, графики динамики, портфолио с подсветкой врачей.

**Отложено сознательно и записано:** пол и возраст клиента жёстко заданы в маршруте находок (`Subject(sex="ж", age=35)`) — их место в карточке клиента, и они добавляются планом 4 вместе с обезличиванием, которому эти же поля нужны. Пока это видно в коде явной строкой, а не спрятано.
