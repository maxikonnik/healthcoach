# План 3. Документы: чтение выгрузок и автозаполнение показателей

> **Для агентов:** ОБЯЗАТЕЛЬНЫЙ ПОДНАВЫК: используйте superpowers:subagent-driven-development (рекомендуется) или superpowers:executing-plans, чтобы выполнять этот план задача за задачей. Шаги помечены чекбоксами (`- [ ]`).

**Цель:** коуч прикладывает к срезу выгрузку лаборатории — PDF или фотографию — и получает заполненную форму показателей, которую остаётся сверить, а не набивать руками.

**Архитектура.** Три слоя, каждый проверяется отдельно. Первый читает документ и отдаёт строки текста: `pdfplumber` для PDF, распознавание macOS Vision для фотографий, оба за одним интерфейсом. Второй разбирает строки в записи бланка, определяя роли колонок по строке-шапке, а не по позиции. Третий превращает запись бланка в измерение среза: распознаёт название, пересчитывает единицы и складывает всё в те же ворота сверки, что и ручной ввод. Ни один слой ничего не додумывает: непонятая строка доходит до коуча текстом как есть.

**Технологии:** Python 3.12, `pdfplumber` для PDF, `pyobjc-framework-Vision` и `pyobjc-framework-Quartz` для распознавания фотографий, существующие `healthcoach.intake.resolve`, `healthcoach.knowledge.units`, `healthcoach.storage`.

## Что установлено разведкой образцов

Это не предположения — проверено на файлах в `samples/` до написания плана. Числа и форматы ниже взяты оттуда.

**Все четыре PDF имеют текстовый слой.** Распознавание изображений нужно только фотографиям. Извлечение таблиц (`extract_tables`) даёт чистый результат лишь у одной лаборатории из трёх — у СМ-Клиники, где таблицы разлинованы. У Гемотеста оно возвращает одну колонку со склеенной шапкой, у «Медицинского Менеджмента» — 39 колонок, из которых 38 пустые. Поэтому разбирать надо **строки текста**, а не таблицы.

**Порядок колонок различается.** Три лаборатории, три порядка:

| Лаборатория | Строка-шапка |
|---|---|
| Гемотест | `Исследование Значение Ед. изм. Нормальные значения` |
| Медицинский Менеджмент | `Параметр Результат Референсные значения Ед. изм.` |
| СМ-Клиника | `Показатель Результат Ед. изм. Референсные пределы` |

У второй единицы стоят **после** референса, у остальных — до. Читать по позиции нельзя.

**Что ещё встречается в живых выгрузках:**

- Служебный код в названии: `Общий белок A09.05.010 (Приказ МЗ РФ № 804н) 73.0 г/л 64 - 83`.
- Нечисловое значение: `С-реактивный белок … <0.60 мг/л < 5`.
- Референс словами: `Смотри текст`, после чего идёт абзац пояснений.
- Перенос строки посреди названия: у «Медицинского Менеджмента» `Средняя концентрация гемоглобина в эритроцитах` и следом `341.00 320.00-360.00 г/л`.
- Перенос посреди служебного кода, когда значение остаётся на первой строке: `Гликированный гемоглобин (HbA1c) A09.05.083 (Приказ МЗ РФ № 4.7 % Смотри текст` и следом `804н)`. Такую строку разобрать однозначно нельзя, и план этого не пытается.
- Между результатами вклиниваются `Дата исследования: 28.11.2023;` и абзацы врачебных пояснений.
- Единицы пишутся по-разному: `10*9/литр` у одной лаборатории и `10⁹/л` у другой.
- Распознавание фотографии возвращает наблюдения **без строк таблицы**: название показателя и его значение приходят отдельными наблюдениями, потому что колонки далеко друг от друга. Строка восстанавливается по вертикальной координате: на образце `2026-07-01 ОАК.jpg` из 117 наблюдений собирается 42 строки.
- Распознавание ошибается в единицах: `пг` прочиталось как `nr`. Десятичный разделитель на фотографиях — запятая (`7,93`), в PDF — точка.

**В каждом документе — полные ФИО пациента, дата рождения, адрес, номер полиса.** Это настоящие персональные данные. Отсюда два следствия для этого плана: документы кладутся в `data/documents/`, который закрыт `.gitignore`, а тесты **не имеют права опираться на `samples/`** — они работают на обезличенных образцах в `tests/intake/fixtures/`, повторяющих структуру, но не содержимое.

## Решения партнёра

Приняты до написания плана, менять их реализацией нельзя.

1. **В срез попадают все строки документа, а не только известные базе знаний.** В одной выгрузке Гемотеста 21 показатель, в базе референсов сегодня три. Отбрасывать остальные значило бы терять данные безвозвратно: добавив показатель в референсы позже, коуч уже не увидит его в старых срезах. Нераспознанные показываются свёрнутым списком, чтобы не топить важные строки в прочих.
2. **Нечисловые значения сохраняются как есть.** `<0.60` не превращается в `0.60`: настоящее значение меньше, а насколько — неизвестно, и в динамике это дало бы ложный график. Строка попадает в срез с исходным текстом и пометкой, что число не извлечено; коуч вписывает число сам или оставляет без трактовки.
3. **Распознавание фотографий — встроенное в macOS Vision.** Работает оффлайн и бесплатно, медицинские данные не покидают машину коуча, устанавливать ничего не надо.

## Global Constraints

- Python 3.12, всё через `uv run`. Никаких голых `python` и `pip`.
- **Данные клиентов не попадают в репозиторий никогда.** `.gitignore` закрывает `data/`, `clients/`, `*.db`, `registry.json`, `samples/`. Тесты пишут базы в `tmp_path` pytest и читают только обезличенные образцы из `tests/intake/fixtures/`.
- **`samples/` — источник только для чтения глазами.** Ни один тест не читает оттуда без явной пометки `pytest.mark.samples` и пропуска, если папки нет.
- **Реестр «код клиента ↔ ФИО» доступен только через `ClientRepository`.** Ни один модуль этого плана не читает таблицу `identities` и не импортирует `storage/clients.py`.
- **Никаких молчаливых допущений.** Непонятая строка бланка доходит до коуча текстом как есть. Нераспознанное название не подменяется похожим. Несопоставленные единицы не считаются эквивалентными. Нечисловое значение не превращается в число.
- **Ничего не попадает в находки без подтверждения коуча.** Измерение из документа сохраняется неподтверждённым, ровно как ручной ввод.
- Формулы базы знаний — данные, а не код: только разбор по белому списку, никогда `eval`/`exec`.
- Каждая задача заканчивается запуском `uv run pytest` и коммитом.
- Набор тестов на старте: **268 проходящих**.

## Файловая структура

| Файл | Ответственность |
|---|---|
| `src/healthcoach/storage/schema.py` | схема версии 3: значение измерения может отсутствовать, добавлены исходный текст значения и источник строки |
| `src/healthcoach/storage/documents.py` | `DocumentRepository`: файл документа привязан к срезу |
| `src/healthcoach/intake/lab_table.py` | разбор строк выгрузки в записи бланка; роли колонок по шапке |
| `src/healthcoach/intake/pdf.py` | чтение строк текста из PDF |
| `src/healthcoach/intake/ocr.py` | интерфейс распознавания и реализация поверх macOS Vision; сборка строк по координатам |
| `src/healthcoach/intake/documents.py` | единый вход: файл → строки → записи бланка |
| `src/healthcoach/intake/measurements.py` | запись бланка → измерение среза: название, единицы, значение |
| `src/healthcoach/app/routes_documents.py` | загрузка документа к срезу и разбор в измерения |
| `tests/intake/fixtures/` | обезличенные образцы выгрузок трёх лабораторий |

---

### Task 1: Схема версии 3 и хранилище документов

**Files:**
- Modify: `src/healthcoach/storage/schema.py`
- Modify: `src/healthcoach/storage/snapshots.py`
- Create: `src/healthcoach/storage/documents.py`
- Modify: `src/healthcoach/app/routes_snapshots.py` — у `add_measurement` появился `raw_value`
- Modify: `tests/storage/test_snapshots.py` — там же
- Test: `tests/storage/test_documents.py`
- Test: `tests/storage/test_migration.py` (дополнить)

**Interfaces:**
- Consumes: `open_database(path) -> sqlite3.Connection`, `MIGRATIONS`, `SCHEMA`, `SCHEMA_VERSION` из `healthcoach.storage.schema`
- Produces:
  - `SOURCE_MANUAL = "ручной ввод"`, `SOURCE_PDF = "pdf"`, `SOURCE_PHOTO = "фото"` в `healthcoach.storage.snapshots`
  - `StoredMeasurement(id, analyte_id, raw_name, value: float | None, raw_value: str, units, taken_on, confirmed, source, document_id)`
  - `SnapshotRepository.add_measurement(snapshot_id, analyte_id, raw_name, value: float | None, raw_value: str, units, taken_on, source=SOURCE_MANUAL, document_id=None) -> StoredMeasurement`
  - `SnapshotRepository.set_value(measurement_id, snapshot_id, value: float) -> bool`
  - `Document(id, snapshot_id, filename, stored_path, added_at)`
  - `DocumentRepository(connection)` с `add(snapshot_id, filename, stored_path, added_at) -> Document`, `get(document_id) -> Document | None`, `for_snapshot(snapshot_id) -> list[Document]`

**Почему значение стало необязательным.** Решение партнёра: `<0.60` сохраняется как есть. Ноль вместо отсутствующего числа — молчаливая ложь, а именно её проект запрещает. SQLite не умеет менять обязательность колонки через `ALTER TABLE`, поэтому переход пересобирает таблицу и переносит строки.

**Почему у измерения появился источник.** На экране сверки коуч должен видеть, откуда строка: набранное руками и вытащенное из фотографии заслуживают разного внимания. Распознавание путает единицы — на образце `пг` прочиталось как `nr`.

- [ ] **Step 1: Написать падающие тесты хранилища документов**

Файл `tests/storage/test_documents.py`:

```python
from datetime import date, datetime

import pytest

from healthcoach.storage.clients import ClientRepository
from healthcoach.storage.db import open_database
from healthcoach.storage.documents import DocumentRepository
from healthcoach.storage.snapshots import SOURCE_PDF, SnapshotRepository


@pytest.fixture
def repositories(tmp_path):
    connection = open_database(tmp_path / "db.sqlite")
    clients = ClientRepository(connection)
    client = clients.add("Иванова Мария", "ж", date(1990, 5, 17))
    snapshots = SnapshotRepository(connection)
    snapshot = snapshots.create(client.code, date(2026, 9, 1))
    yield snapshot, snapshots, DocumentRepository(connection)
    connection.close()


def test_document_is_stored_and_read_back(repositories):
    snapshot, _, documents = repositories
    added = datetime(2026, 9, 1, 12, 30)
    stored = documents.add(snapshot.id, "Биохимия.pdf", "/data/documents/1/a.pdf", added)

    (read_back,) = documents.for_snapshot(snapshot.id)
    assert read_back.id == stored.id
    assert read_back.filename == "Биохимия.pdf"
    assert read_back.stored_path == "/data/documents/1/a.pdf"
    assert read_back.added_at == added


def test_documents_of_another_snapshot_are_not_returned(repositories):
    snapshot, snapshots, documents = repositories
    other = snapshots.create(snapshot.client_code, date(2026, 10, 1))
    documents.add(other.id, "Чужой.pdf", "/data/documents/2/b.pdf", datetime(2026, 10, 1))

    assert documents.for_snapshot(snapshot.id) == []


def test_unknown_document_is_none(repositories):
    _, _, documents = repositories
    assert documents.get(99999) is None


def test_measurement_without_a_number_keeps_the_original_text(repositories):
    """«<0.60» — ниже порога чувствительности метода, а не 0.60."""
    snapshot, snapshots, documents = repositories
    document = documents.add(
        snapshot.id, "Биохимия.pdf", "/data/documents/1/a.pdf", datetime(2026, 9, 1)
    )
    snapshots.add_measurement(
        snapshot.id,
        analyte_id="срб",
        raw_name="С-реактивный белок",
        value=None,
        raw_value="<0.60",
        units="мг/л",
        taken_on=date(2026, 8, 20),
        source=SOURCE_PDF,
        document_id=document.id,
    )

    (stored,) = snapshots.measurements(snapshot.id)
    assert stored.value is None
    assert stored.raw_value == "<0.60"
    assert stored.source == SOURCE_PDF
    assert stored.document_id == document.id


def test_coach_can_fill_in_the_missing_number(repositories):
    snapshot, snapshots, _ = repositories
    stored = snapshots.add_measurement(
        snapshot.id,
        analyte_id="срб",
        raw_name="С-реактивный белок",
        value=None,
        raw_value="<0.60",
        units="мг/л",
        taken_on=date(2026, 8, 20),
    )

    assert snapshots.set_value(stored.id, snapshot.id, 0.3) is True
    (read_back,) = snapshots.measurements(snapshot.id)
    assert read_back.value == 0.3
    assert read_back.raw_value == "<0.60"


def test_filling_a_value_does_not_reach_another_snapshot(repositories):
    """Идентификатор среза в адресе обязан что-то значить."""
    snapshot, snapshots, _ = repositories
    other = snapshots.create(snapshot.client_code, date(2026, 10, 1))
    stored = snapshots.add_measurement(
        other.id,
        analyte_id="срб",
        raw_name="С-реактивный белок",
        value=None,
        raw_value="<0.60",
        units="мг/л",
        taken_on=date(2026, 8, 20),
    )

    assert snapshots.set_value(stored.id, snapshot.id, 0.3) is False
    (untouched,) = snapshots.measurements(other.id)
    assert untouched.value is None
```

- [ ] **Step 2: Запустить тесты и убедиться, что они падают**

```bash
uv run pytest tests/storage/test_documents.py -v
```

Ожидается: ошибка импорта `healthcoach.storage.documents`.

- [ ] **Step 3: Поднять схему до версии 3**

В `src/healthcoach/storage/schema.py` заменить `SCHEMA_VERSION = 2` на `SCHEMA_VERSION = 3`, определение таблицы `measurements` — на новое, и дописать переход.

Новое определение таблицы:

```sql
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
```

Переход добавить в словарь `MIGRATIONS`:

```python
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
```

- [ ] **Step 4: Расширить хранилище срезов**

В `src/healthcoach/storage/snapshots.py` дописать константы источников сразу после импортов:

```python
SOURCE_MANUAL = "ручной ввод"
SOURCE_PDF = "pdf"
SOURCE_PHOTO = "фото"
```

Заменить `StoredMeasurement` на:

```python
@dataclass(frozen=True)
class StoredMeasurement:
    id: int
    analyte_id: str
    raw_name: str
    value: float | None
    """None, если в бланке было не число: «<0.60» не равно 0.60."""
    raw_value: str
    units: str
    taken_on: date
    confirmed: bool
    source: str
    document_id: int | None
```

Заменить сборку из строки базы:

```python
def _measurement(row: sqlite3.Row) -> StoredMeasurement:
    return StoredMeasurement(
        id=row["id"],
        analyte_id=row["analyte_id"],
        raw_name=row["raw_name"],
        value=row["value"],
        raw_value=row["raw_value"],
        units=row["units"],
        taken_on=date.fromisoformat(row["taken_on"]),
        confirmed=bool(row["confirmed"]),
        source=row["source"],
        document_id=row["document_id"],
    )
```

Заменить `add_measurement` на:

```python
    def add_measurement(
        self,
        snapshot_id: int,
        analyte_id: str,
        raw_name: str,
        value: float | None,
        raw_value: str,
        units: str,
        taken_on: date,
        source: str = SOURCE_MANUAL,
        document_id: int | None = None,
    ) -> StoredMeasurement:
        cursor = self._connection.execute(
            "INSERT INTO measurements "
            "(snapshot_id, analyte_id, raw_name, value, raw_value, units, "
            " taken_on, document_id, source, confirmed) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 0)",
            (
                snapshot_id,
                analyte_id,
                raw_name,
                value,
                raw_value,
                units,
                taken_on.isoformat(),
                document_id,
                source,
            ),
        )
        self._connection.commit()
        return StoredMeasurement(
            id=cursor.lastrowid,
            analyte_id=analyte_id,
            raw_name=raw_name,
            value=value,
            raw_value=raw_value,
            units=units,
            taken_on=taken_on,
            confirmed=False,
            source=source,
            document_id=document_id,
        )
```

Дописать метод сразу после `confirm_measurement`:

```python
    def set_value(self, measurement_id: int, snapshot_id: int, value: float) -> bool:
        """Вписать число там, где в бланке его не было. False — строки нет.

        Срез обязателен по той же причине, что и у подтверждения: без него
        правка по одному идентификатору затрагивала бы измерение любого
        другого клиента.
        """
        cursor = self._connection.execute(
            "UPDATE measurements SET value = ? WHERE id = ? AND snapshot_id = ?",
            (value, measurement_id, snapshot_id),
        )
        self._connection.commit()
        return cursor.rowcount == 1
```

- [ ] **Step 5: Реализовать хранилище документов**

Файл `src/healthcoach/storage/documents.py`:

```python
"""Файлы выгрузок, приложенные к срезу.

В базе лежит только путь: сами файлы остаются на диске в папке данных,
которую закрывает .gitignore. Внутри выгрузки — ФИО пациента, дата
рождения, адрес и номер полиса, и попасть в репозиторий они не должны.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class Document:
    id: int
    snapshot_id: int
    filename: str
    stored_path: str
    added_at: datetime


def _document(row: sqlite3.Row) -> Document:
    return Document(
        id=row["id"],
        snapshot_id=row["snapshot_id"],
        filename=row["filename"],
        stored_path=row["stored_path"],
        added_at=datetime.fromisoformat(row["added_at"]),
    )


class DocumentRepository:
    """Выгрузки лабораторий, приложенные к срезам."""

    def __init__(self, connection: sqlite3.Connection) -> None:
        self._connection = connection

    def add(
        self, snapshot_id: int, filename: str, stored_path: str, added_at: datetime
    ) -> Document:
        cursor = self._connection.execute(
            "INSERT INTO documents (snapshot_id, filename, stored_path, added_at) "
            "VALUES (?, ?, ?, ?)",
            (snapshot_id, filename, stored_path, added_at.isoformat()),
        )
        self._connection.commit()
        return Document(
            id=cursor.lastrowid,
            snapshot_id=snapshot_id,
            filename=filename,
            stored_path=stored_path,
            added_at=added_at,
        )

    def get(self, document_id: int) -> Document | None:
        row = self._connection.execute(
            "SELECT * FROM documents WHERE id = ?", (document_id,)
        ).fetchone()
        return _document(row) if row is not None else None

    def for_snapshot(self, snapshot_id: int) -> list[Document]:
        rows = self._connection.execute(
            "SELECT * FROM documents WHERE snapshot_id = ? ORDER BY id",
            (snapshot_id,),
        ).fetchall()
        return [_document(row) for row in rows]
```

- [ ] **Step 6: Дописать тест перехода на настоящей базе версии 2**

В `tests/storage/test_migration.py` заменить `SCHEMA_V1` на пару констант и дописать тест. Существующие тесты не трогать.

```python
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
```

Добавить в начало файла импорт `from healthcoach.storage.snapshots import SnapshotRepository`.

- [ ] **Step 7: Починить существующие обращения к add_measurement**

Появился обязательный `raw_value`. Обновить вызовы в `tests/storage/test_snapshots.py` и в `src/healthcoach/app/routes_snapshots.py`, добавив `raw_value=value.strip()` там, где число пришло от коуча строкой, и `raw_value=str(...)` в тестах.

В `routes_snapshots.py` в обработчике `add_measurement` заменить вызов на:

```python
            repo.snapshots.add_measurement(
                snapshot_id,
                analyte_id=analyte_id,
                raw_name=raw_name,
                value=stored_value,
                raw_value=value.strip(),
                units=stored_units,
                taken_on=when,
            )
```

- [ ] **Step 8: Запустить весь набор**

```bash
uv run pytest -q
```

Ожидается: 275 проходящих.

- [ ] **Step 9: Коммит**

```bash
git add src/healthcoach/storage tests/storage src/healthcoach/app/routes_snapshots.py
git commit -m "feat: схема версии 3 — документы, исходный текст значения и источник строки"
```

---

### Task 2: Разбор строк выгрузки

**Files:**
- Create: `src/healthcoach/intake/lab_table.py`
- Create: `tests/intake/fixtures/gemotest.txt`
- Create: `tests/intake/fixtures/medmenedzhment.txt`
- Create: `tests/intake/fixtures/smclinic.txt`
- Test: `tests/intake/test_lab_table.py`

**Interfaces:**
- Consumes: ничего из проекта, чистые функции над списком строк
- Produces:
  - `LabRow(name: str, value_text: str, units: str, reference_text: str, line: str)`
  - `LabTable(rows: tuple[LabRow, ...], unparsed: tuple[str, ...])`
  - `parse_lab_lines(lines: Sequence[str]) -> LabTable`
  - `parse_number(text: str) -> float | None`
  - `LabTableError` — шапка не найдена

**Как определяются колонки.** Разбор ищет строку-шапку: строку, в которой встречается слово роли «название» и слово роли «значение». Порядок ролей берётся из порядка слов в этой строке. Если шапки нет, разбирать нечего: поднимается `LabTableError`, и весь документ уходит коучу текстом.

**Как разбирается строка результата.** Служебный код лаборатории (`A09.05.010` и следующая за ним скобка вида `(Приказ …)`) вырезается первым делом. Дальше строка делится на название и хвост по первому числу: всё до него — название, оно и остальное — поля в порядке из шапки. Строка, начинающаяся с числа, считается продолжением предыдущей строки-названия. Строка, в которой не набирается нужного числа полей, попадает в `unparsed` целиком.

**Что происходит со строкой, которая не стала записью.** Если в ней есть хоть одна цифра, она может оказаться результатом, который разбор не осилил, — такая строка уходит в `unparsed` и доходит до коуча текстом. Если цифр нет вовсе, результатом она быть не может: это либо перенесённое название, либо проза бланка, и она ждёт следующую строку как начало названия. Отличить прозу от перенесённого названия по одному тексту нельзя, но потерять при этом нечего — числа в ней не было.

Строка вроде `Биохимия 21 показатель (расширенная)` наоборот может стать записью с бессмысленным значением: она дойдёт до коуча в свёрнутом списке нераспознанных и будет там видна. Это шум, а не молчаливая ошибка, и потому допустим.

**Чего разбор не делает.** Не пытается разобрать строку с разорванным служебным кодом, где значение оказалось внутри незакрытой скобки (`Гликированный гемоглобин (HbA1c) A09.05.083 (Приказ МЗ РФ № 4.7 % Смотри текст`). Однозначно она не читается, и догадка тут стоила бы неверного числа в анализе живого человека. Такая строка уходит в `unparsed`.

- [ ] **Step 1: Создать обезличенные образцы**

Файл `tests/intake/fixtures/gemotest.txt` — структура Гемотеста, данные вымышлены:

```
Исследование Значение Ед. изм. Нормальные
значения
Биохимия 21 показатель (расширенная)
Общий белок A09.05.010 (Приказ МЗ РФ № 804н) 73.0 г/л 64 - 83
Дата исследования: 28.11.2023;
Альбумин A09.05.011 (Приказ МЗ РФ № 804н) 47 г/л 35 - 52
Дата исследования: 28.11.2023;
С-реактивный белок A09.05.009 (Приказ МЗ РФ № 804н) <0.60 мг/л < 5
Дата исследования: 28.11.2023;
Триглицериды A09.05.025 (Приказ МЗ РФ № 804н) 0.98 ммоль/л Смотри текст
Дата исследования: 28.11.2023;
Нормальный уровень <1,70
Умеренно-повышенный 1,70-2,25
Гликированный гемоглобин (HbA1c) A09.05.083 (Приказ МЗ РФ № 4.7 % Смотри текст
804н)
```

Файл `tests/intake/fixtures/medmenedzhment.txt` — единицы стоят последними:

```
Параметр Результат Референсные значения Ед. изм.
Общее количество лейкоцитов (WBC) 6.07 4.50-11.00 10⁹/л
Гемоглобин (Hb) 134.00 117.00-155.00 г/л
Гематокрит (Ht) 39.30 35.00-45.00 %
Средняя концентрация гемоглобина в эритроцитах
341.00 320.00-360.00 г/л
```

Файл `tests/intake/fixtures/smclinic.txt`:

```
Показатель Результат Ед. изм. Референсные пределы
C-реактивный белок (СРБ) 0.7 мг/л 0 - 5
Ревматоидный фактор 7.40 Ед./мл 0 - 14
Антистрептолизин-О (АСЛО) 106.00 Ед./мл 0 - 200
Результат лабораторного исследования не является единственным параметром для постановки диагноза.
```

- [ ] **Step 2: Написать падающие тесты**

Файл `tests/intake/test_lab_table.py`:

```python
from pathlib import Path

import pytest

from healthcoach.intake.lab_table import (
    LabTableError,
    parse_lab_lines,
    parse_number,
)

FIXTURES = Path(__file__).parent / "fixtures"


def _lines(name: str) -> list[str]:
    return (FIXTURES / f"{name}.txt").read_text(encoding="utf-8").splitlines()


def test_units_before_reference(): 
    """У СМ-Клиники шапка: Показатель, Результат, Ед. изм., Референсные пределы."""
    table = parse_lab_lines(_lines("smclinic"))
    row = next(r for r in table.rows if "реактивный" in r.name)
    assert row.value_text == "0.7"
    assert row.units == "мг/л"
    assert row.reference_text == "0 - 5"


def test_units_after_reference():
    """У Медицинского Менеджмента единицы стоят последними — читать по шапке."""
    table = parse_lab_lines(_lines("medmenedzhment"))
    row = next(r for r in table.rows if "лейкоцитов" in r.name)
    assert row.value_text == "6.07"
    assert row.units == "10⁹/л"
    assert row.reference_text == "4.50-11.00"


def test_laboratory_code_is_stripped_from_the_name():
    table = parse_lab_lines(_lines("gemotest"))
    row = next(r for r in table.rows if r.name.startswith("Общий белок"))
    assert row.name == "Общий белок"
    assert row.value_text == "73.0"
    assert row.units == "г/л"


def test_non_numeric_value_is_kept_as_text():
    """«<0.60» — ниже порога чувствительности метода, а не 0.60."""
    table = parse_lab_lines(_lines("gemotest"))
    row = next(r for r in table.rows if "реактивный" in r.name)
    assert row.value_text == "<0.60"
    assert parse_number(row.value_text) is None


def test_wrapped_name_is_joined_with_the_next_line():
    table = parse_lab_lines(_lines("medmenedzhment"))
    row = next(r for r in table.rows if r.value_text == "341.00")
    assert row.name == "Средняя концентрация гемоглобина в эритроцитах"
    assert row.units == "г/л"


def test_line_with_a_broken_laboratory_code_is_reported_not_guessed():
    """Значение внутри незакрытой скобки читается неоднозначно.

    Угадать здесь — значит поставить в анализ живого человека число,
    которого в бланке не было.
    """
    table = parse_lab_lines(_lines("gemotest"))
    assert not any("Гликированный" in r.name for r in table.rows)
    assert any("Гликированный" in line for line in table.unparsed)


def test_service_lines_are_not_taken_for_results():
    table = parse_lab_lines(_lines("gemotest"))
    assert not any("Дата исследования" in r.name for r in table.rows)


def test_line_with_a_number_that_did_not_parse_reaches_the_coach():
    """Строка с числом может быть результатом — молча выбросить её нельзя."""
    table = parse_lab_lines(_lines("gemotest"))
    assert any("Нормальный уровень" in line for line in table.unparsed)
    assert not any("Нормальный уровень" in r.name for r in table.rows)


def test_document_without_a_header_is_refused():
    with pytest.raises(LabTableError, match="шапк"):
        parse_lab_lines(["просто текст", "и ещё строка"])


def test_parse_number_accepts_both_decimal_separators():
    """В PDF разделитель — точка, на фотографиях — запятая."""
    assert parse_number("7.93") == 7.93
    assert parse_number("7,93") == 7.93
    assert parse_number("341") == 341.0
    assert parse_number("Смотри текст") is None
    assert parse_number("") is None
```

- [ ] **Step 3: Запустить тесты и убедиться, что они падают**

```bash
uv run pytest tests/intake/test_lab_table.py -v
```

Ожидается: ошибка импорта `healthcoach.intake.lab_table`.

- [ ] **Step 4: Реализовать разбор**

Файл `src/healthcoach/intake/lab_table.py`:

```python
"""Разбор строк выгрузки лаборатории в записи бланка.

Роли колонок берутся из строки-шапки, а не из позиции: у одной
лаборатории единицы стоят до референса, у другой — после. Строка,
которая однозначно не читается, не разбирается по частям, а доходит
до коуча целиком: догадка здесь стоила бы неверного числа в анализе.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass

ROLE_NAME = "название"
ROLE_VALUE = "значение"
ROLE_UNITS = "единицы"
ROLE_REFERENCE = "референс"

_HEADER_WORDS = {
    "исследование": ROLE_NAME,
    "показатель": ROLE_NAME,
    "параметр": ROLE_NAME,
    "значение": ROLE_VALUE,
    "результат": ROLE_VALUE,
    "ед": ROLE_UNITS,
    "нормальные": ROLE_REFERENCE,
    "референсные": ROLE_REFERENCE,
}

_LAB_CODE = re.compile(r"\bA\d{2}\.\d{2}\.\d{3}\b\s*(\([^()]*\))?")
_NUMBER = re.compile(r"^[<>]?\d+(?:[.,]\d+)?$")
_STARTS_WITH_NUMBER = re.compile(r"^\s*[<>]?\d")
_HAS_DIGIT = re.compile(r"\d")
_SERVICE = re.compile(r"^\s*(Дата исследования|Штрихкод|Материал|Вн\.№)")
_SPACES = re.compile(r"\s+")


class LabTableError(Exception):
    """Выгрузку разобрать нельзя."""


@dataclass(frozen=True)
class LabRow:
    name: str
    value_text: str
    units: str
    reference_text: str
    line: str


@dataclass(frozen=True)
class LabTable:
    rows: tuple[LabRow, ...]
    unparsed: tuple[str, ...]
    """Строки, которые не читаются однозначно. Показываются коучу как есть."""


def parse_number(text: str) -> float | None:
    """Число из ячейки бланка. None, если числа там нет.

    «<0.60» числом не считается: настоящее значение меньше, а насколько —
    неизвестно, и подстановка 0.60 исказила бы динамику.
    """
    cleaned = text.strip().replace(",", ".")
    try:
        return float(cleaned)
    except ValueError:
        return None


def _header_roles(line: str) -> list[str] | None:
    """Порядок ролей колонок, если строка похожа на шапку."""
    roles: list[str] = []
    for word in _SPACES.split(line.strip().casefold()):
        role = _HEADER_WORDS.get(word.strip(".:"))
        if role is not None and role not in roles:
            roles.append(role)
    if ROLE_NAME in roles and ROLE_VALUE in roles:
        return roles
    return None


def _strip_lab_code(line: str) -> str:
    return _SPACES.sub(" ", _LAB_CODE.sub("", line)).strip()


def _split_row(line: str, roles: Sequence[str]) -> LabRow | None:
    """Разобрать строку результата или вернуть None, если не читается."""
    tokens = _SPACES.split(line.strip())
    first = next(
        (i for i, token in enumerate(tokens) if _NUMBER.match(token)), None
    )
    if first is None or first == 0:
        return None

    name = " ".join(tokens[:first])
    rest = tokens[first:]
    fields: dict[str, str] = {ROLE_NAME: name}

    # Референс бывает из трёх слов («0 - 5»), единицы — всегда из одного.
    # Последняя колонка забирает весь остаток: референс бывает из трёх
    # слов («0 - 5»), а единицы — всегда из одного.
    tail_roles = [role for role in roles if role != ROLE_NAME]
    for index, role in enumerate(tail_roles):
        if not rest:
            return None
        if index == len(tail_roles) - 1:
            fields[role] = " ".join(rest)
            rest = []
        else:
            fields[role] = rest.pop(0)

    if not _NUMBER.match(fields.get(ROLE_VALUE, "")):
        return None
    return LabRow(
        name=fields[ROLE_NAME],
        value_text=fields[ROLE_VALUE],
        units=fields.get(ROLE_UNITS, ""),
        reference_text=fields.get(ROLE_REFERENCE, ""),
        line=line,
    )


def parse_lab_lines(lines: Sequence[str]) -> LabTable:
    """Разобрать строки выгрузки в записи бланка."""
    roles: list[str] | None = None
    for line in lines:
        roles = _header_roles(line)
        if roles is not None:
            break
    if roles is None:
        raise LabTableError(
            "в выгрузке не найдена шапка таблицы: неизвестно, где значение, "
            "а где единицы"
        )

    rows: list[LabRow] = []
    unparsed: list[str] = []
    pending_name = ""

    for line in lines:
        stripped = line.strip()
        if not stripped or _header_roles(line) is not None or _SERVICE.match(stripped):
            continue

        if pending_name and _STARTS_WITH_NUMBER.match(stripped):
            candidate = f"{pending_name} {stripped}"
            pending_name = ""
        else:
            candidate = stripped

        cleaned = _strip_lab_code(candidate)
        if "(" in cleaned and cleaned.count("(") != cleaned.count(")"):
            unparsed.append(line)
            pending_name = ""
            continue

        row = _split_row(cleaned, roles)
        if row is not None:
            rows.append(row)
            pending_name = ""
        elif _HAS_DIGIT.search(cleaned):
            # В строке есть число, а записи не вышло: это может быть
            # результат, который разбор не осилил. Молча выбросить его
            # нельзя — он доходит до коуча текстом.
            unparsed.append(line)
            pending_name = ""
        elif cleaned:
            # Числа нет вовсе, значит это не результат: либо перенесённое
            # название, либо проза бланка. Ждём следующую строку.
            pending_name = cleaned

    return LabTable(rows=tuple(rows), unparsed=tuple(unparsed))
```

- [ ] **Step 5: Запустить тесты**

```bash
uv run pytest tests/intake/test_lab_table.py -v
```

Ожидается: 10 PASS. Если `_split_row` не сходится на образцах — править реализацию, не тесты: тесты списаны со структуры настоящих выгрузок.

- [ ] **Step 6: Прогнать весь набор и закоммитить**

```bash
uv run pytest -q
git add src/healthcoach/intake/lab_table.py tests/intake
git commit -m "feat: разбор строк выгрузки лаборатории по шапке таблицы"
```

Ожидается: 285 проходящих.

---

### Task 3: Чтение PDF

**Files:**
- Create: `src/healthcoach/intake/pdf.py`
- Modify: `pyproject.toml` — добавить `pdfplumber>=0.11`
- Test: `tests/intake/test_pdf.py`
- Test: `tests/conftest.py` — пометка `samples`

**Interfaces:**
- Consumes: ничего из проекта
- Produces: `read_pdf_lines(path: Path) -> list[str]`, `PdfError`

**Почему строки, а не таблицы.** Извлечение таблиц даёт чистый результат только у одной лаборатории из трёх. У Гемотеста оно возвращает одну колонку со склеенной шапкой, у «Медицинского Менеджмента» — 39 колонок, из которых 38 пустые. Текстовые строки чисты у всех трёх, и разбор из задачи 2 работает поверх них.

**Почему тесты не читают `samples/`.** Там настоящие медицинские данные: ФИО, дата рождения, адрес, номер полиса. Папка закрыта `.gitignore`, на машине другого разработчика её нет. Тест на живых выгрузках существует, но помечен `samples` и пропускается, если папки нет.

- [ ] **Step 1: Добавить зависимость**

В `pyproject.toml` в `dependencies` добавить строку `"pdfplumber>=0.11",`.

- [ ] **Step 2: Объявить пометку для тестов на живых образцах**

Файл `tests/conftest.py`:

```python
from pathlib import Path

import pytest

SAMPLES = Path(__file__).parents[1] / "samples"


def pytest_configure(config):
    config.addinivalue_line(
        "markers",
        "samples: работает на настоящих выгрузках из samples/ (пропускается, "
        "если папки нет — там персональные данные, в репозиторий они не попадают)",
    )


@pytest.fixture
def samples_dir() -> Path:
    if not SAMPLES.is_dir():
        pytest.skip("папки samples/ нет — тест на живых выгрузках пропущен")
    return SAMPLES
```

- [ ] **Step 3: Написать падающие тесты**

Файл `tests/intake/test_pdf.py`:

```python
import pytest

from healthcoach.intake.lab_table import parse_lab_lines
from healthcoach.intake.pdf import PdfError, read_pdf_lines


def test_missing_file_is_refused(tmp_path):
    with pytest.raises(PdfError, match="не прочитан"):
        read_pdf_lines(tmp_path / "нет.pdf")


def test_not_a_pdf_is_refused(tmp_path):
    path = tmp_path / "текст.pdf"
    path.write_text("это не pdf", encoding="utf-8")
    with pytest.raises(PdfError, match="не прочитан"):
        read_pdf_lines(path)


@pytest.mark.samples
def test_every_sample_pdf_has_a_text_layer(samples_dir):
    """Если текстового слоя нет, разбирать нечего и нужен другой путь."""
    pdfs = sorted(samples_dir.glob("*.pdf"))
    assert pdfs, "в samples/ нет ни одного PDF"
    for path in pdfs:
        lines = read_pdf_lines(path)
        assert len(lines) > 20, f"{path.name}: текстового слоя почти нет"


@pytest.mark.samples
def test_every_sample_pdf_yields_rows(samples_dir):
    for path in sorted(samples_dir.glob("*.pdf")):
        table = parse_lab_lines(read_pdf_lines(path))
        assert table.rows, f"{path.name}: не разобрано ни одной строки результата"
```

- [ ] **Step 4: Запустить тесты и убедиться, что они падают**

```bash
uv run pytest tests/intake/test_pdf.py -v
```

Ожидается: ошибка импорта `healthcoach.intake.pdf`.

- [ ] **Step 5: Реализовать чтение**

Файл `src/healthcoach/intake/pdf.py`:

```python
"""Чтение строк текста из PDF-выгрузки.

Извлекаются строки, а не таблицы: разлинованные таблицы есть лишь у
части лабораторий, а у остальных извлечение таблиц даёт мусор — одну
склеенную колонку или три десятка пустых. Текстовые строки чисты у всех.
"""

from __future__ import annotations

from pathlib import Path

import pdfplumber


class PdfError(Exception):
    """PDF не прочитан."""


def read_pdf_lines(path: Path) -> list[str]:
    """Все строки текста документа, страница за страницей."""
    lines: list[str] = []
    try:
        with pdfplumber.open(path) as pdf:
            for page in pdf.pages:
                lines.extend((page.extract_text() or "").splitlines())
    except Exception as exc:  # pdfplumber поднимает разные типы
        raise PdfError(f"{path.name}: файл не прочитан как PDF ({exc})") from exc
    return lines
```

- [ ] **Step 6: Запустить тесты**

```bash
uv run pytest tests/intake/test_pdf.py -v
```

Ожидается: 4 PASS на машине партнёра (папка `samples/` есть), 2 PASS и 2 SKIP там, где её нет.

- [ ] **Step 7: Прогнать весь набор и закоммитить**

```bash
uv run pytest -q
git add pyproject.toml uv.lock src/healthcoach/intake/pdf.py tests/intake/test_pdf.py tests/conftest.py
git commit -m "feat: чтение строк текста из PDF-выгрузки"
```

Ожидается: 289 проходящих.

---

### Task 4: Распознавание фотографий

**Files:**
- Create: `src/healthcoach/intake/ocr.py`
- Modify: `pyproject.toml` — добавить `pyobjc-framework-Vision>=10.3` и `pyobjc-framework-Quartz>=10.3`
- Test: `tests/intake/test_ocr.py`

**Interfaces:**
- Consumes: ничего из проекта
- Produces:
  - `TextLine(text: str, x: float, y: float)` — наблюдение с координатами центра, доли от размера изображения
  - `OCREngine` — протокол с `read(path: Path) -> list[TextLine]`
  - `AppleVisionEngine` — реализация поверх macOS Vision
  - `rows_from_observations(observations: Sequence[TextLine], tolerance: float = 0.006) -> list[str]`
  - `OCRError`

**Почему адаптер, а не прямой вызов.** Решение партнёра — встроенное в macOS распознавание: оффлайн, бесплатно, медицинские данные не покидают машину. Но привязывать к нему разбор нельзя: движок меняется, а разбор строк — нет. `OCREngine` — единственная точка, которую придётся переписать при смене движка.

**Почему строки собираются по координатам.** Распознавание возвращает наблюдения, а не строки таблицы: название показателя и его значение приходят отдельными наблюдениями, потому что колонки далеко друг от друга. На образце из 117 наблюдений собирается 42 строки. Без этой сборки разбор из задачи 2 не найдёт в строке ни значения, ни единиц.

- [ ] **Step 1: Добавить зависимости**

В `pyproject.toml` в `dependencies` добавить:

```toml
    "pyobjc-framework-Vision>=10.3; sys_platform == 'darwin'",
    "pyobjc-framework-Quartz>=10.3; sys_platform == 'darwin'",
```

- [ ] **Step 2: Написать падающие тесты**

Файл `tests/intake/test_ocr.py`:

```python
import sys

import pytest

from healthcoach.intake.ocr import (
    OCRError,
    TextLine,
    rows_from_observations,
)


def test_observations_on_the_same_height_become_one_row():
    """Название и значение приходят разными наблюдениями: колонки далеко."""
    observations = [
        TextLine("Гемоглобин (Hb)", x=0.10, y=0.500),
        TextLine("103", x=0.55, y=0.501),
        TextLine("г/л", x=0.80, y=0.499),
        TextLine("Гематокрит (Ht)", x=0.10, y=0.470),
        TextLine("31,4", x=0.55, y=0.470),
    ]
    assert rows_from_observations(observations) == [
        "Гемоглобин (Hb) 103 г/л",
        "Гематокрит (Ht) 31,4",
    ]


def test_row_keeps_left_to_right_order():
    observations = [
        TextLine("г/л", x=0.80, y=0.5),
        TextLine("103", x=0.55, y=0.5),
        TextLine("Гемоглобин", x=0.10, y=0.5),
    ]
    assert rows_from_observations(observations) == ["Гемоглобин 103 г/л"]


def test_rows_go_from_top_to_bottom():
    observations = [
        TextLine("нижняя", x=0.1, y=0.10),
        TextLine("верхняя", x=0.1, y=0.90),
    ]
    assert rows_from_observations(observations) == ["верхняя", "нижняя"]


def test_observations_further_apart_than_the_tolerance_are_separate_rows():
    observations = [
        TextLine("первая", x=0.1, y=0.500),
        TextLine("вторая", x=0.1, y=0.480),
    ]
    assert len(rows_from_observations(observations, tolerance=0.006)) == 2


def test_no_observations_gives_no_rows():
    assert rows_from_observations([]) == []


@pytest.mark.skipif(sys.platform != "darwin", reason="Vision есть только в macOS")
def test_engine_refuses_a_file_that_is_not_an_image(tmp_path):
    from healthcoach.intake.ocr import AppleVisionEngine

    path = tmp_path / "не картинка.jpg"
    path.write_text("просто текст", encoding="utf-8")
    with pytest.raises(OCRError, match="не распознан"):
        AppleVisionEngine().read(path)


@pytest.mark.samples
@pytest.mark.skipif(sys.platform != "darwin", reason="Vision есть только в macOS")
def test_sample_photo_yields_readable_rows(samples_dir):
    from healthcoach.intake.ocr import AppleVisionEngine

    photos = sorted(samples_dir.glob("*.jpg"))
    assert photos, "в samples/ нет ни одной фотографии"
    rows = rows_from_observations(AppleVisionEngine().read(photos[0]))
    assert len(rows) > 20
    assert any("Гемоглобин" in row for row in rows)
```

- [ ] **Step 3: Запустить тесты и убедиться, что они падают**

```bash
uv run pytest tests/intake/test_ocr.py -v
```

Ожидается: ошибка импорта `healthcoach.intake.ocr`.

- [ ] **Step 4: Реализовать адаптер**

Файл `src/healthcoach/intake/ocr.py`:

```python
"""Распознавание текста с фотографии бланка.

Движок вынесен за интерфейс: сегодня это встроенное в macOS
распознавание — оффлайн, бесплатно, медицинские данные не покидают
машину коуча. Разбор строк от движка не зависит.

Распознавание возвращает наблюдения, а не строки таблицы: название
показателя и его значение приходят отдельно, потому что колонки далеко
друг от друга. Строка собирается по вертикальной координате.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol


class OCRError(Exception):
    """Изображение не распознано."""


@dataclass(frozen=True)
class TextLine:
    """Наблюдение распознавания. Координаты — доли от размера изображения."""

    text: str
    x: float
    y: float


class OCREngine(Protocol):
    """Движок распознавания. Меняется целиком, не по частям."""

    def read(self, path: Path) -> list[TextLine]: ...


def rows_from_observations(
    observations: Sequence[TextLine], tolerance: float = 0.006
) -> list[str]:
    """Собрать наблюдения в строки таблицы по вертикальной координате."""
    if not observations:
        return []

    ordered = sorted(observations, key=lambda o: -o.y)
    rows: list[list[TextLine]] = [[ordered[0]]]
    for observation in ordered[1:]:
        if abs(rows[-1][0].y - observation.y) > tolerance:
            rows.append([])
        rows[-1].append(observation)

    return [
        " ".join(o.text for o in sorted(row, key=lambda o: o.x)) for row in rows
    ]


class AppleVisionEngine:
    """Распознавание средствами macOS."""

    def __init__(self, languages: Sequence[str] = ("ru-RU", "en-US")) -> None:
        self._languages = list(languages)

    def read(self, path: Path) -> list[TextLine]:
        try:
            import Quartz
            import Vision
            from Foundation import NSURL
        except ImportError as exc:
            raise OCRError(
                "распознавание доступно только в macOS: не найден Vision"
            ) from exc

        url = NSURL.fileURLWithPath_(str(path))
        source = Quartz.CGImageSourceCreateWithURL(url, None)
        image = (
            Quartz.CGImageSourceCreateImageAtIndex(source, 0, None)
            if source is not None
            else None
        )
        if image is None:
            raise OCRError(f"{path.name}: файл не распознан как изображение")

        request = Vision.VNRecognizeTextRequest.alloc().init()
        request.setRecognitionLevel_(Vision.VNRequestTextRecognitionLevelAccurate)
        request.setRecognitionLanguages_(self._languages)
        request.setUsesLanguageCorrection_(True)

        handler = Vision.VNImageRequestHandler.alloc().initWithCGImage_options_(
            image, None
        )
        handler.performRequests_error_([request], None)

        observations: list[TextLine] = []
        for result in request.results() or ():
            candidates = result.topCandidates_(1)
            if not candidates:
                continue
            box = result.boundingBox()
            observations.append(
                TextLine(
                    text=candidates[0].string(),
                    x=box.origin.x,
                    y=box.origin.y + box.size.height / 2,
                )
            )
        return observations
```

- [ ] **Step 5: Запустить тесты**

```bash
uv run pytest tests/intake/test_ocr.py -v
```

Ожидается: 7 PASS на машине партнёра.

- [ ] **Step 6: Прогнать весь набор и закоммитить**

```bash
uv run pytest -q
git add pyproject.toml uv.lock src/healthcoach/intake/ocr.py tests/intake/test_ocr.py
git commit -m "feat: распознавание фотографий бланка средствами macOS"
```

Ожидается: 296 проходящих.

---

### Task 5: Из записи бланка — в измерение среза

**Files:**
- Create: `src/healthcoach/intake/documents.py`
- Create: `src/healthcoach/intake/measurements.py`
- Modify: `src/healthcoach/intake/resolve.py` — вырезать служебный код лаборатории из названия
- Modify: `src/healthcoach/scoring/references.py` — статус для измерения без числа
- Modify: `src/healthcoach/scoring/findings.py` — тяжесть нового статуса
- Test: `tests/intake/test_read_document.py`
- Test: `tests/intake/test_import_measurements.py`

**Interfaces:**
- Consumes: `LabTable`, `LabRow`, `parse_lab_lines`, `parse_number`; `read_pdf_lines`; `OCREngine`, `rows_from_observations`; `resolve_analyte`; `convert_to_reference`, `UnitError`; `SOURCE_PDF`, `SOURCE_PHOTO`
- Produces:
  - `ReadDocument(source: str, lines: tuple[str, ...], table: LabTable)`
  - `read_document(path: Path, engine: OCREngine | None = None) -> ReadDocument`
  - `DocumentError`
  - `PreparedMeasurement(analyte_id, raw_name, value: float | None, raw_value, units, problem: str | None)`
  - `prepare_measurements(references, table: LabTable) -> list[PreparedMeasurement]`
  - `STATUS_NO_VALUE = "значение не распознано"` в `healthcoach.scoring.references`

**Почему нераспознанные строки всё равно становятся измерениями.** Решение партнёра: в срез попадают все строки документа. В одной выгрузке 21 показатель, в базе референсов три; отбрасывать остальные значило бы терять данные безвозвратно — добавив показатель в референсы позже, коуч уже не увидит его в старых срезах.

- [ ] **Step 1: Написать падающие тесты единого входа**

Файл `tests/intake/test_read_document.py`:

```python
from pathlib import Path

import pytest

from healthcoach.intake.documents import DocumentError, read_document
from healthcoach.intake.ocr import TextLine
from healthcoach.storage.snapshots import SOURCE_PDF, SOURCE_PHOTO

FIXTURES = Path(__file__).parent / "fixtures"


class FakeEngine:
    """Движок распознавания, отдающий заранее известные наблюдения."""

    def __init__(self, observations):
        self._observations = observations

    def read(self, path: Path):
        return self._observations


def test_photo_goes_through_the_engine(tmp_path):
    path = tmp_path / "бланк.jpg"
    path.write_bytes(b"\xff\xd8\xff")
    engine = FakeEngine(
        [
            TextLine("Показатель", x=0.10, y=0.90),
            TextLine("Результат", x=0.40, y=0.90),
            TextLine("Ед. изм.", x=0.65, y=0.90),
            TextLine("Референсные пределы", x=0.85, y=0.90),
            TextLine("Гемоглобин", x=0.10, y=0.80),
            TextLine("103", x=0.40, y=0.80),
            TextLine("г/л", x=0.65, y=0.80),
            TextLine("117 - 155", x=0.85, y=0.80),
        ]
    )

    document = read_document(path, engine)
    assert document.source == SOURCE_PHOTO
    (row,) = document.table.rows
    assert row.name == "Гемоглобин"
    assert row.value_text == "103"
    assert row.units == "г/л"
    assert row.reference_text == "117 - 155"


def test_photo_without_an_engine_is_refused(tmp_path):
    path = tmp_path / "бланк.jpg"
    path.write_bytes(b"\xff\xd8\xff")
    with pytest.raises(DocumentError, match="распознавание"):
        read_document(path, None)


def test_unknown_extension_is_refused(tmp_path):
    path = tmp_path / "бланк.docx"
    path.write_bytes(b"nope")
    with pytest.raises(DocumentError, match="не поддерживается"):
        read_document(path)


@pytest.mark.samples
def test_sample_pdf_is_read_as_pdf(samples_dir):
    path = sorted(samples_dir.glob("*.pdf"))[0]
    document = read_document(path)
    assert document.source == SOURCE_PDF
    assert document.table.rows
```

- [ ] **Step 2: Написать падающие тесты приведения к измерению**

Файл `tests/intake/test_import_measurements.py`:

```python
from pathlib import Path

from healthcoach.intake.lab_table import LabRow, LabTable
from healthcoach.intake.measurements import prepare_measurements
from healthcoach.knowledge.references import load_references

REFS = Path(__file__).parents[2] / "knowledge" / "references"


def _table(*rows: LabRow) -> LabTable:
    return LabTable(rows=rows, unparsed=())


def test_known_analyte_is_recognised_and_converted():
    references = load_references(REFS)
    table = _table(LabRow("Ферритин", "45", "мкг/л", "10 - 120", "строка"))

    (prepared,) = prepare_measurements(references, table)
    assert prepared.analyte_id == "ферритин"
    assert prepared.value == 45.0
    assert prepared.units == "нг/мл"
    assert prepared.problem is None


def test_unknown_analyte_is_kept_not_dropped():
    """21 показатель в выгрузке против трёх в базе — терять их нельзя."""
    references = load_references(REFS)
    table = _table(LabRow("Гомоцистеин", "12", "мкмоль/л", "5 - 15", "строка"))

    (prepared,) = prepare_measurements(references, table)
    assert prepared.analyte_id == ""
    assert prepared.raw_name == "Гомоцистеин"
    assert prepared.value == 12.0
    assert prepared.problem == "показатель не распознан"


def test_non_numeric_value_keeps_its_text():
    references = load_references(REFS)
    table = _table(LabRow("Ферритин", "<0.60", "нг/мл", "< 5", "строка"))

    (prepared,) = prepare_measurements(references, table)
    assert prepared.value is None
    assert prepared.raw_value == "<0.60"
    assert prepared.problem == "число не извлечено"


def test_unmatched_units_are_not_assumed_equivalent():
    references = load_references(REFS)
    table = _table(LabRow("Ферритин", "45", "пмоль/л", "10 - 120", "строка"))

    (prepared,) = prepare_measurements(references, table)
    assert prepared.units == "пмоль/л"
    assert prepared.value == 45.0
    assert "единицы" in prepared.problem


def test_laboratory_code_in_the_name_does_not_prevent_recognition():
    references = load_references(REFS)
    table = _table(
        LabRow("Ферритин A09.05.076 (Приказ МЗ РФ № 804н)", "45", "нг/мл", "", "строка")
    )

    (prepared,) = prepare_measurements(references, table)
    assert prepared.analyte_id == "ферритин"
```

- [ ] **Step 3: Запустить тесты и убедиться, что они падают**

```bash
uv run pytest tests/intake/test_read_document.py tests/intake/test_import_measurements.py -v
```

Ожидается: ошибки импорта `healthcoach.intake.documents` и `healthcoach.intake.measurements`.

Имя файла намеренно не `test_documents.py`: под `tests/` нет `__init__.py`, а такой файл уже есть в `tests/storage/`, и pytest не соберёт оба в одном прогоне.

- [ ] **Step 4: Научить распознавание названий вырезать служебный код**

В `src/healthcoach/intake/resolve.py` дописать после `_SPACES`:

```python
_LAB_CODE = re.compile(r"\bA\d{2}\.\d{2}\.\d{3}\b\s*(\([^()]*\))?")
"""Код номенклатуры медицинских услуг: «Ферритин A09.05.076 (Приказ …)»."""
```

и в `_clean` первой строкой добавить:

```python
    text = _LAB_CODE.sub("", text)
```

- [ ] **Step 5: Добавить статус для измерения без числа**

В `src/healthcoach/scoring/references.py` дописать к константам статусов:

```python
STATUS_NO_VALUE = "значение не распознано"
```

и в `check_measurements`, первым делом внутри цикла по измерениям:

```python
        if measurement.value is None:
            verdicts.append(_unresolved(measurement, STATUS_NO_VALUE))
            continue
```

В `src/healthcoach/scoring/findings.py` добавить `STATUS_NO_VALUE` в импорт из `healthcoach.scoring.references` и в словарь `_SEVERITY`:

```python
    STATUS_NO_VALUE: 4,
```

- [ ] **Step 6: Реализовать единый вход**

Файл `src/healthcoach/intake/documents.py`:

```python
"""Единый вход: файл выгрузки — в записи бланка.

PDF читается текстовым слоем, фотография — через движок распознавания.
Дальше оба идут одним путём: строки текста разбираются по шапке таблицы.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from healthcoach.intake.lab_table import LabTable, parse_lab_lines
from healthcoach.intake.ocr import OCREngine, rows_from_observations
from healthcoach.intake.pdf import read_pdf_lines
from healthcoach.storage.snapshots import SOURCE_PDF, SOURCE_PHOTO

PHOTO_SUFFIXES = frozenset({".jpg", ".jpeg", ".png", ".heic"})


class DocumentError(Exception):
    """Документ прочитать нельзя."""


@dataclass(frozen=True)
class ReadDocument:
    source: str
    lines: tuple[str, ...]
    table: LabTable


def read_document(path: Path, engine: OCREngine | None = None) -> ReadDocument:
    """Прочитать выгрузку и разобрать её в записи бланка."""
    suffix = path.suffix.casefold()

    if suffix == ".pdf":
        lines = read_pdf_lines(path)
        source = SOURCE_PDF
    elif suffix in PHOTO_SUFFIXES:
        if engine is None:
            raise DocumentError(
                f"{path.name}: для фотографии нужно распознавание, движок не задан"
            )
        lines = rows_from_observations(engine.read(path))
        source = SOURCE_PHOTO
    else:
        raise DocumentError(f"{path.name}: формат {suffix!r} не поддерживается")

    return ReadDocument(
        source=source, lines=tuple(lines), table=parse_lab_lines(lines)
    )
```

- [ ] **Step 7: Реализовать приведение к измерению**

Файл `src/healthcoach/intake/measurements.py`:

```python
"""Запись бланка — в измерение среза.

Ничего не отбрасывается: нераспознанный показатель сохраняется с пустым
идентификатором и пометкой, нечисловое значение — исходным текстом.
В одной выгрузке два десятка показателей, а в базе знаний коуча их
единицы; отбросить лишнее значило бы потерять данные, которые
понадобятся, как только коуч заведёт референс.
"""

from __future__ import annotations

from dataclasses import dataclass

from healthcoach.intake.lab_table import LabTable, parse_number
from healthcoach.intake.resolve import resolve_analyte
from healthcoach.knowledge.references import References
from healthcoach.knowledge.units import UnitError, convert_to_reference

UNRESOLVED = ""
"""Идентификатор нераспознанного показателя: хранится, но не трактуется."""


@dataclass(frozen=True)
class PreparedMeasurement:
    analyte_id: str
    raw_name: str
    value: float | None
    raw_value: str
    units: str
    problem: str | None


def prepare_measurements(
    references: References, table: LabTable
) -> list[PreparedMeasurement]:
    """Превратить записи бланка в измерения, ничего не отбрасывая."""
    prepared: list[PreparedMeasurement] = []

    for row in table.rows:
        value = parse_number(row.value_text)
        resolution = resolve_analyte(references, row.name)

        analyte_id, units, problem = UNRESOLVED, row.units, None

        if resolution.is_ambiguous:
            candidates = ", ".join(a.name for a in resolution.candidates)
            problem = f"название подходит нескольким показателям: {candidates}"
        elif not resolution.is_certain:
            problem = "показатель не распознан"
        else:
            analyte_id = resolution.analyte.id
            if value is None:
                units = row.units
            else:
                try:
                    value = convert_to_reference(resolution.analyte, value, row.units)
                    units = resolution.analyte.units
                except UnitError:
                    problem = f"единицы не сопоставлены: {row.units}"

        if value is None and problem is None:
            problem = "число не извлечено"
        elif value is None:
            problem = f"{problem}; число не извлечено"

        prepared.append(
            PreparedMeasurement(
                analyte_id=analyte_id,
                raw_name=row.name,
                value=value,
                raw_value=row.value_text,
                units=units,
                problem=problem,
            )
        )

    return prepared
```

- [ ] **Step 8: Запустить тесты**

```bash
uv run pytest tests/intake -v
```

Ожидается: все PASS. Обратите внимание на `test_non_numeric_value_keeps_its_text`: у распознанного показателя без числа `problem` должен быть ровно `"число не извлечено"`.

- [ ] **Step 9: Прогнать весь набор и закоммитить**

```bash
uv run pytest -q
git add src/healthcoach/intake src/healthcoach/scoring tests/intake
git commit -m "feat: запись бланка превращается в измерение среза, ничего не теряя"
```

Ожидается: 305 проходящих.

---

### Task 6: Экран загрузки документа

**Files:**
- Create: `src/healthcoach/app/routes_documents.py`
- Modify: `src/healthcoach/app/main.py` — подключить маршрутизатор
- Modify: `src/healthcoach/app/deps.py` — движок распознавания в контексте
- Modify: `src/healthcoach/app/templates/snapshot.html` — форма загрузки и группировка строк
- Modify: `src/healthcoach/app/routes_snapshots.py` — строки таблицы знают источник и проблему
- Test: `tests/app/test_document_routes.py`

**Interfaces:**
- Consumes: `read_document`, `DocumentError`; `prepare_measurements`; `DocumentRepository`; `AppleVisionEngine`; `Context.session()`
- Produces: `Repositories.documents: DocumentRepository`; маршруты `POST /snapshots/{id}/documents`, `POST /snapshots/{id}/measurements/{mid}/value`

**Как выглядит экран.** Решение партнёра: узнанные показатели сверху списком, нераспознанные — свёрнутым блоком, чтобы три важных не тонули в двадцати прочих. Строки, которые разбор не смог прочитать, показываются текстом как есть под отдельным заголовком: коуч вводит их руками.

**Куда кладётся файл.** В `context.documents_dir / str(snapshot_id)`, имя — идентификатор документа с исходным расширением. Исходное имя файла хранится в базе, а не на диске: в именах выгрузок встречаются номера заказов и фамилии.

- [ ] **Step 1: Написать падающие тесты**

Файл `tests/app/test_document_routes.py`:

```python
from datetime import date
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from healthcoach.app.deps import build_context
from healthcoach.app.main import create_app

KNOWLEDGE = Path(__file__).parents[2] / "knowledge"
FIXTURES = Path(__file__).parents[1] / "intake" / "fixtures"

WOMAN = {"full_name": "Иванова Мария", "sex": "ж", "birth_date": "1990-05-17"}


@pytest.fixture
def client(tmp_path):
    context = build_context(data_dir=tmp_path, knowledge_dir=KNOWLEDGE)
    with TestClient(create_app(context)) as test_client:
        yield test_client, context


def _snapshot(test_client) -> int:
    test_client.post("/clients", data=WOMAN)
    test_client.post("/clients/CL-0001/snapshots", data={"taken_on": "2026-09-01"})
    return 1


def _measurements(context, snapshot_id):
    with context.session() as repo:
        return repo.snapshots.measurements(snapshot_id)


def test_unsupported_format_is_refused(client):
    test_client, _ = client
    snapshot_id = _snapshot(test_client)
    response = test_client.post(
        f"/snapshots/{snapshot_id}/documents",
        files={"file": ("бланк.docx", b"nope", "application/octet-stream")},
        follow_redirects=False,
    )
    assert response.status_code == 400


def test_unknown_snapshot_is_404(client):
    test_client, _ = client
    response = test_client.post(
        "/snapshots/999/documents",
        files={"file": ("бланк.pdf", b"%PDF-1.4", "application/pdf")},
        follow_redirects=False,
    )
    assert response.status_code == 404


def test_value_can_be_filled_in_by_hand(client):
    """У «<0.60» числа нет: коуч решает, что вписать."""
    test_client, context = client
    snapshot_id = _snapshot(test_client)
    with context.session() as repo:
        stored = repo.snapshots.add_measurement(
            snapshot_id,
            analyte_id="ферритин",
            raw_name="Ферритин",
            value=None,
            raw_value="<0.60",
            units="нг/мл",
            taken_on=date(2026, 8, 20),
        )

    test_client.post(
        f"/snapshots/{snapshot_id}/measurements/{stored.id}/value",
        data={"value": "0,3"},
    )

    (read_back,) = _measurements(context, snapshot_id)
    assert read_back.value == 0.3
    assert read_back.raw_value == "<0.60"


def test_value_of_another_snapshot_is_404(client):
    test_client, context = client
    first = _snapshot(test_client)
    test_client.post("/clients/CL-0001/snapshots", data={"taken_on": "2026-10-01"})
    with context.session() as repo:
        second = repo.snapshots.for_client("CL-0001")[-1].id
        stored = repo.snapshots.add_measurement(
            second,
            analyte_id="ферритин",
            raw_name="Ферритин",
            value=None,
            raw_value="<0.60",
            units="нг/мл",
            taken_on=date(2026, 8, 20),
        )

    response = test_client.post(
        f"/snapshots/{first}/measurements/{stored.id}/value",
        data={"value": "0.3"},
        follow_redirects=False,
    )
    assert response.status_code == 404


def test_non_numeric_value_is_refused(client):
    test_client, context = client
    snapshot_id = _snapshot(test_client)
    with context.session() as repo:
        stored = repo.snapshots.add_measurement(
            snapshot_id,
            analyte_id="ферритин",
            raw_name="Ферритин",
            value=None,
            raw_value="<0.60",
            units="нг/мл",
            taken_on=date(2026, 8, 20),
        )

    response = test_client.post(
        f"/snapshots/{snapshot_id}/measurements/{stored.id}/value",
        data={"value": "мало"},
        follow_redirects=False,
    )
    assert response.status_code == 400
```

- [ ] **Step 2: Запустить тесты и убедиться, что они падают**

```bash
uv run pytest tests/app/test_document_routes.py -v
```

Ожидается: FAIL — маршрутов ещё нет.

- [ ] **Step 3: Положить движок распознавания в контекст**

В `src/healthcoach/app/deps.py` добавить импорт и поле:

```python
from healthcoach.intake.ocr import AppleVisionEngine, OCREngine
```

В `Context` добавить поле после `database_path`:

```python
    ocr: OCREngine | None
```

В `build_context` — перед `return Context(`:

```python
    # Распознавание есть только в macOS. Без него PDF читаются как обычно,
    # а фотография честно отвечает, что распознать её нечем.
    engine: OCREngine | None
    try:
        engine = AppleVisionEngine()
    except Exception:
        engine = None
```

и в вызов `Context(...)` добавить `ocr=engine,`.

- [ ] **Step 4: Реализовать маршруты**

Файл `src/healthcoach/app/routes_documents.py`:

```python
"""Загрузка выгрузки лаборатории к срезу."""

from __future__ import annotations

from datetime import date, datetime
from pathlib import Path

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import RedirectResponse

from healthcoach.app.deps import Context
from healthcoach.intake.documents import DocumentError, read_document
from healthcoach.intake.lab_table import LabTableError, parse_number
from healthcoach.intake.measurements import prepare_measurements

def build_router(context: Context) -> APIRouter:
    router = APIRouter()

    @router.post("/snapshots/{snapshot_id}/documents")
    async def upload_document(snapshot_id: int, file: UploadFile = File(...)):
        with context.session() as repo:
            snapshot = repo.snapshots.get(snapshot_id)
            if snapshot is None:
                raise HTTPException(
                    status_code=404, detail=f"нет среза {snapshot_id}"
                )

        payload = await file.read()
        suffix = Path(file.filename or "").suffix.casefold()
        folder = context.documents_dir / str(snapshot_id)
        folder.mkdir(parents=True, exist_ok=True)

        added_at = datetime.now()
        with context.session() as repo:
            document = repo.documents.add(
                snapshot_id, file.filename or "без имени", "", added_at
            )

        stored_path = folder / f"{document.id}{suffix}"
        stored_path.write_bytes(payload)

        try:
            read = read_document(stored_path, context.ocr)
        except (DocumentError, LabTableError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        with context.session() as repo:
            for prepared in prepare_measurements(context.references, read.table):
                repo.snapshots.add_measurement(
                    snapshot_id,
                    analyte_id=prepared.analyte_id,
                    raw_name=prepared.raw_name,
                    value=prepared.value,
                    raw_value=prepared.raw_value,
                    units=prepared.units,
                    taken_on=snapshot.taken_on,
                    source=read.source,
                    document_id=document.id,
                )

        return RedirectResponse(f"/snapshots/{snapshot_id}", status_code=303)

    @router.post("/snapshots/{snapshot_id}/measurements/{measurement_id}/value")
    def set_value(snapshot_id: int, measurement_id: int, value: str = Form(...)):
        number = parse_number(value)
        if number is None:
            raise HTTPException(
                status_code=400, detail="значение должно быть числом"
            )
        with context.session() as repo:
            if repo.snapshots.get(snapshot_id) is None:
                raise HTTPException(
                    status_code=404, detail=f"нет среза {snapshot_id}"
                )
            if not repo.snapshots.set_value(measurement_id, snapshot_id, number):
                raise HTTPException(
                    status_code=404,
                    detail=f"в срезе {snapshot_id} нет показателя {measurement_id}",
                )
        return RedirectResponse(f"/snapshots/{snapshot_id}", status_code=303)

    return router
```

Хранилище документов должно выдаваться сессией наравне с остальными. В `src/healthcoach/app/deps.py` добавить в `Repositories` поле `documents: DocumentRepository`, импортировать `DocumentRepository` и собирать его в `Context.session()`:

```python
            yield Repositories(
                clients=ClientRepository(connection),
                snapshots=SnapshotRepository(connection),
                documents=DocumentRepository(connection),
            )
```

- [ ] **Step 5: Подключить маршрутизатор**

В `src/healthcoach/app/main.py`:

```python
from healthcoach.app import routes_clients, routes_documents, routes_snapshots
```

```python
    app.include_router(routes_documents.build_router(context))
```

- [ ] **Step 6: Показать источник и проблему на экране среза**

В `src/healthcoach/app/routes_snapshots.py` в `_rows` добавлять в `Row` источник, а в шаблоне `snapshot.html` заменить таблицу показателей на группировку: узнанные, затем свёрнутый блок нераспознанных, затем неразобранные строки документа. Форма загрузки документа добавляется перед таблицей:

```html
<h2>Документы</h2>
<form method="post" action="/snapshots/{{ snapshot.id }}/documents"
      enctype="multipart/form-data">
  <label>Выгрузка лаборатории
    <input type="file" name="file" accept=".pdf,.jpg,.jpeg,.png" required></label>
  <button type="submit">Загрузить</button>
</form>
```

В таблице показателей добавить колонку источника и строку правки значения там, где числа нет:

```html
    <td class="muted">{{ row.measurement.source }}</td>
    <td>
      {% if row.measurement.value is none %}
      <form method="post"
            action="/snapshots/{{ snapshot.id }}/measurements/{{ row.measurement.id }}/value">
        <span class="warn">{{ row.measurement.raw_value }}</span>
        <input name="value" size="6" inputmode="decimal" required>
        <button type="submit">Вписать</button>
      </form>
      {% else %}{{ row.measurement.value }} {{ row.measurement.units }}{% endif %}
    </td>
```

- [ ] **Step 7: Запустить тесты**

```bash
uv run pytest tests/app -v
```

Ожидается: все PASS.

- [ ] **Step 8: Пройти сквозной путь руками**

```bash
uv run python -m healthcoach.app.main
```

1. Завести клиента, создать срез.
2. Загрузить `samples/Биохимия 22.08.pdf` — на экране должны появиться СРБ, ревматоидный фактор и АСЛО, все неподтверждённые, все с источником «pdf».
3. Загрузить `samples/2026-07-01 ОАК.jpg` — строки должны прийти с источником «фото».
4. Проверить, что нераспознанные показатели свёрнуты, а неразобранные строки видны текстом.
5. Подтвердить ферритин, если он есть, и открыть находки.
6. Остановить `Ctrl+C`, удалить `data/healthcoach.db` и папку `data/documents` — это проверочные данные, в рабочей базе им не место.

- [ ] **Step 9: Коммит**

```bash
git add src/healthcoach/app tests/app
git commit -m "feat: загрузка выгрузки лаборатории и автозаполнение показателей среза"
```

---

## Что дальше

**План 4 — интерпретация и отчёт.** Обезличивание с обязательным тестом на утечку — теперь оно особенно важно: в каждой выгрузке лежат ФИО, дата рождения, адрес и номер полиса, и разбор их не удаляет. Адаптер `LLMProvider` поверх `claude -p`, сборка черновика с привязкой к находкам, экран правки и утверждения, PDF через WeasyPrint, графики динамики, портфолио с подсветкой врачей.

**Долги, записанные при исполнении планов 2 и 3.**

- Единицы сравниваются в трёх местах строковым равенством вместо канонической нормализации (`scoring/references.py`, `scoring/derived.py`, `app/routes_snapshots.py`). Сегодня недостижимо, потому что ручной ввод всегда переписывает единицы на эталонные. **Этот план делает долг живым:** `prepare_measurements` пишет единицы из бланка, когда пересчёт не удался, и синоним, объявленный коучем, будет помечен как несопоставленный. Закрыть в первую очередь.
- Исходное введённое значение не хранилось; задача 1 добавляет `raw_value`, но для ручного ввода он заполняется тем же числом. Пересчитанное и исходное всё ещё неразличимы, когда коуч ввёл значение в других единицах.
- Уникальность идентификаторов вопросов между блоками опросника ничем не обеспечена: сегодня 544 из 544 уникальны, но загрузчик проверяет только идентификаторы блоков.
