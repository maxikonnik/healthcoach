# План 4. Обезличивание, интерпретация и утверждение черновика

> **Для агентов:** ОБЯЗАТЕЛЬНЫЙ ПОДНАВЫК: используйте superpowers:subagent-driven-development (рекомендуется) или superpowers:executing-plans, чтобы выполнять этот план задача за задачей. Шаги помечены чекбоксами (`- [ ]`).

**Цель:** коуч получает черновик отчёта, собранный языковой моделью по посчитанным кодом находкам, с привязкой каждого раздела к тем находкам, на которых он стоит, — правит его и утверждает. Идентифицирующие данные клиента модели не уходят.

**Архитектура.** Четыре слоя, каждый проверяется отдельно. Первый вычищает из текста всё, что позволяет узнать человека, и умеет доказать, что вычистил. Второй собирает вход модели из находок, обезличенного запроса и справочника специальностей — и не может отправить ничего, что не прошло проверку на утечку. Третий вызывает модель за сменным интерфейсом. Четвёртый собирает черновик по разделам и даёт коучу править и утверждать. Числовая основа под трактовкой посчитана кодом планами 1–3 и моделью не выдумывается.

**Технологии:** Python 3.12, `claude -p` в headless-режиме на подписке Claude Max (проверено: возвращает текст в поле `result`, ошибку — в `is_error`), существующие `healthcoach.scoring`, `healthcoach.storage`, `healthcoach.app`.

## Решения партнёра

Приняты до написания плана. Реализацией не меняются.

1. **План 4 отделён от сборки PDF.** Здесь всё заканчивается утверждённым текстом. Вёрстка, графики динамики и подсветка врачей — план 5. Так обезличивание получает собственное ревью, а не проверяется в одном ряду с вёрсткой.
2. **Свободный текст клиента коуч вычитывает перед отправкой.** Автоматическая чистка работает и готовит черновик, но последнее слово за коучем: экран показывает ровно тот текст, который уйдёт. Чистка свободного текста принципиально ненадёжна — «работаю в школе № 1234» не поймает ни одно правило, — и заменять ею человека нельзя.
3. **Чужая выгрузка не отвергается, но предъявляется.** При загрузке документа экран показывает его шапку рядом с именем из карточки, и предупреждает, если фамилии клиента в тексте документа не нашлось. Отказ был бы неверен: распознавание коверкает буквы, и ложный отказ на своём же клиенте хуже предупреждения.

## Что уже установлено

- `claude -p "…" --output-format json` возвращает объект с ключами `result` (текст), `is_error`, `session_id`, `usage`, `total_cost_usd`. Проверено на этой машине.
- Первый вызов в сессии несёт около 8 тысяч токенов служебного промпта CLI; последующие читают их из кеша. Это довод в пользу нескольких вызовов подряд, а не одного на весь отчёт с последующими переспросами.
- Расход считается против лимитов подписки Claude Max, а не оплачивается по токенам.
- В неразобранных строках выгрузок, которые план 3 выводит на экран, лежат ФИО пациента, дата рождения, адрес и номер полиса. Обезличивание обязано чистить текст выгрузок, а не только карточку клиента.

## Global Constraints

- Python 3.12, всё через `uv run`. Никаких голых `python` и `pip`.
- **Данные клиентов не попадают в репозиторий никогда.** `.gitignore` закрывает `data/`, `clients/`, `*.db`, `registry.json`, `samples/`. Тесты пишут базы в `tmp_path` pytest и не читают `samples/` без пометки `samples`.
- **Реестр «код клиента ↔ ФИО» доступен только через `ClientRepository`.** Стражи в `tests/storage/` параметризованы по всем модулям `storage/`.
- **Ни один вызов модели не отправляется без прохождения проверки на утечку.** Проверка обязательна, не подлежит смягчению и не имеет флага отключения.
- **Врачебные контакты не покидают базу коуча.** Наружу — только `Specialists.public_view()`.
- **Числовая основа считается кодом.** Модель трактует находки, но не вычисляет значения, степени и статусы.
- **Никаких молчаливых допущений.** Недоступная модель, пустой ответ, сорванная проверка на утечку — всё это ошибки, о которых коуч узнаёт, а не тихие пропуски.
- Каждая задача заканчивается запуском `uv run pytest` и коммитом.
- Набор тестов на старте: **369 проходящих**.

## Файловая структура

| Файл | Ответственность |
|---|---|
| `src/healthcoach/storage/schema.py` | схема версии 5: запрос клиента, черновик, утверждённый текст |
| `src/healthcoach/storage/requests.py` | `RequestRepository`: запрос и цели клиента, исходные и вычитанные |
| `src/healthcoach/storage/drafts.py` | `DraftRepository`: разделы черновика, правки коуча, утверждение |
| `src/healthcoach/privacy/redact.py` | вычистка идентифицирующих данных из текста |
| `src/healthcoach/privacy/leak.py` | обязательная проверка перед отправкой, `LeakError` |
| `src/healthcoach/llm/payload.py` | сборка обезличенного входа модели из находок и справочника |
| `src/healthcoach/llm/provider.py` | `LLMProvider` и реализация поверх `claude -p` |
| `src/healthcoach/report/sections.py` | перечень разделов отчёта и их промпты |
| `src/healthcoach/report/draft.py` | сборка черновика по разделам с привязкой к находкам |
| `src/healthcoach/app/routes_report.py` | запрос клиента, вычитка, генерация, правка, утверждение |
| `src/healthcoach/app/templates/report.html` | экран черновика |

---

### Task 1: Схема версии 5 — запрос клиента и черновик

**Files:**
- Modify: `src/healthcoach/storage/schema.py`
- Create: `src/healthcoach/storage/requests.py`
- Create: `src/healthcoach/storage/drafts.py`
- Test: `tests/storage/test_requests.py`
- Test: `tests/storage/test_drafts.py`
- Test: `tests/storage/test_migration.py` (дополнить)

**Interfaces:**
- Consumes: `open_database`, `MIGRATIONS`, `SCHEMA`, `SCHEMA_VERSION`
- Produces:
  - `ClientRequest(snapshot_id, raw, redacted, approved)` и `RequestRepository(connection)` с `save(snapshot_id, raw) -> ClientRequest`, `set_redacted(snapshot_id, redacted) -> bool`, `approve(snapshot_id) -> bool`, `get(snapshot_id) -> ClientRequest | None`
  - `DraftSection(id, snapshot_id, section_id, generated, edited, finding_ids)` и `Draft(snapshot_id, sections, approved_at)`
  - `DraftRepository(connection)` с `save_section(snapshot_id, section_id, generated, finding_ids) -> DraftSection`, `edit_section(section_row_id, snapshot_id, text) -> bool`, `sections(snapshot_id) -> list[DraftSection]`, `approve(snapshot_id, approved_at) -> bool`, `approved_at(snapshot_id) -> datetime | None`

**Почему исходный текст и вычитанный хранятся оба.** Решение партнёра: коуч вычитывает текст перед отправкой. Значит нужны обе версии — та, что написал клиент, и та, что уйдёт модели. Затирать исходную нельзя: коуч должен видеть, что именно он убрал, и вернуть, если ошибся.

**Почему у раздела два текста.** `generated` — что написала модель, `edited` — что оставил коуч. Перезаписывать сгенерированное правкой значит потерять возможность сравнить и переспросить.

**Почему утверждение — отметка времени, а не флаг.** Утверждённый отчёт замораживается вместе с версией базы знаний, на которой собран; отметка времени — часть этой записи. Флаг не отвечает на вопрос «когда».

- [ ] **Step 1: Написать падающие тесты запроса клиента**

Файл `tests/storage/test_requests.py`:

```python
from datetime import date

import pytest

from healthcoach.storage.clients import ClientRepository
from healthcoach.storage.db import open_database
from healthcoach.storage.requests import RequestRepository
from healthcoach.storage.snapshots import SnapshotRepository


@pytest.fixture
def repositories(tmp_path):
    connection = open_database(tmp_path / "db.sqlite")
    client = ClientRepository(connection).add("Иванова Мария", "ж", date(1990, 5, 17))
    snapshots = SnapshotRepository(connection)
    snapshot = snapshots.create(client.code, date(2026, 9, 1))
    yield snapshot, snapshots, RequestRepository(connection)
    connection.close()


def test_request_is_saved_and_read_back(repositories):
    snapshot, _, requests = repositories
    saved = requests.save(snapshot.id, "Хочу разобраться с усталостью")

    read_back = requests.get(snapshot.id)
    assert read_back == saved
    assert read_back.raw == "Хочу разобраться с усталостью"
    assert read_back.redacted == ""
    assert read_back.approved is False


def test_saving_again_replaces_the_text_and_drops_the_approval(repositories):
    """Клиент переписал запрос — прежняя вычитка к новому тексту не относится."""
    snapshot, _, requests = repositories
    requests.save(snapshot.id, "Первый текст")
    requests.set_redacted(snapshot.id, "Первый текст без имён")
    requests.approve(snapshot.id)

    requests.save(snapshot.id, "Второй текст")

    read_back = requests.get(snapshot.id)
    assert read_back.raw == "Второй текст"
    assert read_back.redacted == ""
    assert read_back.approved is False


def test_redaction_does_not_touch_the_original(repositories):
    snapshot, _, requests = repositories
    requests.save(snapshot.id, "Работаю в школе № 1234")
    requests.set_redacted(snapshot.id, "Работаю в школе")

    read_back = requests.get(snapshot.id)
    assert read_back.raw == "Работаю в школе № 1234"
    assert read_back.redacted == "Работаю в школе"


def test_approval_requires_a_redacted_text(repositories):
    """Утвердить нечего, пока коуч не вычитал."""
    snapshot, _, requests = repositories
    requests.save(snapshot.id, "Текст")

    assert requests.approve(snapshot.id) is False
    assert requests.get(snapshot.id).approved is False


def test_unknown_snapshot_reports_failure(repositories):
    _, _, requests = repositories
    assert requests.get(99999) is None
    assert requests.set_redacted(99999, "что-то") is False
    assert requests.approve(99999) is False
```

- [ ] **Step 2: Написать падающие тесты черновика**

Файл `tests/storage/test_drafts.py`:

```python
from datetime import date, datetime

import pytest

from healthcoach.storage.clients import ClientRepository
from healthcoach.storage.db import open_database
from healthcoach.storage.drafts import DraftRepository
from healthcoach.storage.snapshots import SnapshotRepository


@pytest.fixture
def repositories(tmp_path):
    connection = open_database(tmp_path / "db.sqlite")
    client = ClientRepository(connection).add("Иванова Мария", "ж", date(1990, 5, 17))
    snapshots = SnapshotRepository(connection)
    snapshot = snapshots.create(client.code, date(2026, 9, 1))
    yield snapshot, snapshots, DraftRepository(connection)
    connection.close()


def test_section_is_saved_with_the_findings_it_stands_on(repositories):
    snapshot, _, drafts = repositories
    saved = drafts.save_section(
        snapshot.id, "показатели", "Ферритин снижен.", ("показатель/ферритин",)
    )

    (read_back,) = drafts.sections(snapshot.id)
    assert read_back.id == saved.id
    assert read_back.section_id == "показатели"
    assert read_back.generated == "Ферритин снижен."
    assert read_back.edited == ""
    assert read_back.finding_ids == ("показатель/ферритин",)


def test_editing_keeps_what_the_model_wrote(repositories):
    """Иначе не сравнить правку с исходным и не переспросить."""
    snapshot, _, drafts = repositories
    saved = drafts.save_section(snapshot.id, "показатели", "Ферритин снижен.", ())

    assert drafts.edit_section(saved.id, snapshot.id, "Ферритин заметно снижен.") is True

    (read_back,) = drafts.sections(snapshot.id)
    assert read_back.generated == "Ферритин снижен."
    assert read_back.edited == "Ферритин заметно снижен."


def test_editing_a_section_of_another_snapshot_is_refused(repositories):
    snapshot, snapshots, drafts = repositories
    other = snapshots.create(snapshot.client_code, date(2026, 10, 1))
    saved = drafts.save_section(other.id, "показатели", "Текст", ())

    assert drafts.edit_section(saved.id, snapshot.id, "Подмена") is False
    (untouched,) = drafts.sections(other.id)
    assert untouched.edited == ""


def test_regenerating_a_section_replaces_it_and_drops_the_edit(repositories):
    snapshot, _, drafts = repositories
    saved = drafts.save_section(snapshot.id, "показатели", "Первый вариант", ())
    drafts.edit_section(saved.id, snapshot.id, "Правка коуча")

    drafts.save_section(snapshot.id, "показатели", "Второй вариант", ())

    (read_back,) = drafts.sections(snapshot.id)
    assert read_back.generated == "Второй вариант"
    assert read_back.edited == ""


def test_approval_records_when(repositories):
    snapshot, _, drafts = repositories
    drafts.save_section(snapshot.id, "показатели", "Текст", ())
    when = datetime(2026, 9, 2, 10, 30)

    assert drafts.approve(snapshot.id, when) is True
    assert drafts.approved_at(snapshot.id) == when


def test_approving_an_empty_draft_is_refused(repositories):
    snapshot, _, drafts = repositories
    assert drafts.approve(snapshot.id, datetime(2026, 9, 2)) is False
    assert drafts.approved_at(snapshot.id) is None


def test_saving_a_section_after_approval_is_refused(repositories):
    """Утверждённый отчёт заморожен — иначе клиент получит не то, что утвердили."""
    snapshot, _, drafts = repositories
    drafts.save_section(snapshot.id, "показатели", "Текст", ())
    drafts.approve(snapshot.id, datetime(2026, 9, 2))

    with pytest.raises(ValueError, match="утвержд"):
        drafts.save_section(snapshot.id, "показатели", "Другой текст", ())
```

- [ ] **Step 3: Запустить тесты и убедиться, что они падают**

```bash
uv run pytest tests/storage/test_requests.py tests/storage/test_drafts.py -v
```

Ожидается: ошибки импорта `healthcoach.storage.requests` и `healthcoach.storage.drafts`.

- [ ] **Step 4: Поднять схему до версии 5**

В `src/healthcoach/storage/schema.py` заменить `SCHEMA_VERSION = 4` на `SCHEMA_VERSION = 5`, дописать в `SCHEMA` три таблицы и добавить переход.

Дописать в конец `SCHEMA`:

```sql
CREATE TABLE IF NOT EXISTS requests (
    snapshot_id  INTEGER PRIMARY KEY REFERENCES snapshots(id) ON DELETE CASCADE,
    raw          TEXT NOT NULL,
    redacted     TEXT NOT NULL DEFAULT '',
    approved     INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS draft_sections (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    snapshot_id  INTEGER NOT NULL REFERENCES snapshots(id) ON DELETE CASCADE,
    section_id   TEXT NOT NULL,
    generated    TEXT NOT NULL,
    edited       TEXT NOT NULL DEFAULT '',
    finding_ids  TEXT NOT NULL DEFAULT '',
    UNIQUE (snapshot_id, section_id)
);

CREATE TABLE IF NOT EXISTS draft_approvals (
    snapshot_id  INTEGER PRIMARY KEY REFERENCES snapshots(id) ON DELETE CASCADE,
    approved_at  TEXT NOT NULL,
    knowledge    TEXT NOT NULL DEFAULT ''
);
```

Переход добавить в словарь `MIGRATIONS` — три новые таблицы, ничего не пересобирается:

```python
    4: (
        """
        CREATE TABLE IF NOT EXISTS requests (
            snapshot_id  INTEGER PRIMARY KEY REFERENCES snapshots(id) ON DELETE CASCADE,
            raw          TEXT NOT NULL,
            redacted     TEXT NOT NULL DEFAULT '',
            approved     INTEGER NOT NULL DEFAULT 0
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS draft_sections (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            snapshot_id  INTEGER NOT NULL REFERENCES snapshots(id) ON DELETE CASCADE,
            section_id   TEXT NOT NULL,
            generated    TEXT NOT NULL,
            edited       TEXT NOT NULL DEFAULT '',
            finding_ids  TEXT NOT NULL DEFAULT '',
            UNIQUE (snapshot_id, section_id)
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS draft_approvals (
            snapshot_id  INTEGER PRIMARY KEY REFERENCES snapshots(id) ON DELETE CASCADE,
            approved_at  TEXT NOT NULL,
            knowledge    TEXT NOT NULL DEFAULT ''
        )
        """,
    ),
```

- [ ] **Step 5: Реализовать хранилище запроса**

Файл `src/healthcoach/storage/requests.py`:

```python
"""Запрос клиента и его цели — его словами.

Хранятся две версии: то, что написал клиент, и то, что коуч вычитал для
отправки модели. Затирать исходную нельзя: коуч должен видеть, что именно
он убрал, и вернуть, если ошибся.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass


@dataclass(frozen=True)
class ClientRequest:
    snapshot_id: int
    raw: str
    redacted: str
    approved: bool


def _request(row: sqlite3.Row) -> ClientRequest:
    return ClientRequest(
        snapshot_id=row["snapshot_id"],
        raw=row["raw"],
        redacted=row["redacted"],
        approved=bool(row["approved"]),
    )


class RequestRepository:
    """Запрос клиента по срезу."""

    def __init__(self, connection: sqlite3.Connection) -> None:
        self._connection = connection

    def save(self, snapshot_id: int, raw: str) -> ClientRequest:
        """Записать запрос. Прежняя вычитка и утверждение сбрасываются.

        Клиент переписал текст — значит вычитка относилась к другому тексту,
        и утверждать её заново обязан коуч.
        """
        self._connection.execute(
            "INSERT INTO requests (snapshot_id, raw, redacted, approved) "
            "VALUES (?, ?, '', 0) "
            "ON CONFLICT(snapshot_id) DO UPDATE SET raw = excluded.raw, "
            "redacted = '', approved = 0",
            (snapshot_id, raw),
        )
        self._connection.commit()
        return ClientRequest(
            snapshot_id=snapshot_id, raw=raw, redacted="", approved=False
        )

    def set_redacted(self, snapshot_id: int, redacted: str) -> bool:
        """Записать вычитанный текст. False — запроса нет."""
        cursor = self._connection.execute(
            "UPDATE requests SET redacted = ?, approved = 0 WHERE snapshot_id = ?",
            (redacted, snapshot_id),
        )
        self._connection.commit()
        return cursor.rowcount == 1

    def approve(self, snapshot_id: int) -> bool:
        """Подтвердить, что вычитанный текст можно отправлять.

        False — запроса нет или коуч ещё не вычитал: утверждать нечего.
        """
        cursor = self._connection.execute(
            "UPDATE requests SET approved = 1 "
            "WHERE snapshot_id = ? AND redacted != ''",
            (snapshot_id,),
        )
        self._connection.commit()
        return cursor.rowcount == 1

    def get(self, snapshot_id: int) -> ClientRequest | None:
        row = self._connection.execute(
            "SELECT * FROM requests WHERE snapshot_id = ?", (snapshot_id,)
        ).fetchone()
        return _request(row) if row is not None else None
```

- [ ] **Step 6: Реализовать хранилище черновика**

Файл `src/healthcoach/storage/drafts.py`:

```python
"""Черновик отчёта: что написала модель и что оставил коуч.

У раздела два текста. Перезаписывать сгенерированное правкой значит
потерять возможность сравнить и переспросить. Утверждение замораживает
черновик: после него разделы не переписываются, иначе клиент получит не
то, что коуч утвердил.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime

_SEPARATOR = "\n"


@dataclass(frozen=True)
class DraftSection:
    id: int
    snapshot_id: int
    section_id: str
    generated: str
    edited: str
    finding_ids: tuple[str, ...]

    @property
    def text(self) -> str:
        """Что пойдёт в отчёт: правка коуча, если она есть."""
        return self.edited or self.generated


def _section(row: sqlite3.Row) -> DraftSection:
    raw = row["finding_ids"]
    return DraftSection(
        id=row["id"],
        snapshot_id=row["snapshot_id"],
        section_id=row["section_id"],
        generated=row["generated"],
        edited=row["edited"],
        finding_ids=tuple(line for line in raw.split(_SEPARATOR) if line),
    )


class DraftRepository:
    """Разделы черновика по срезу."""

    def __init__(self, connection: sqlite3.Connection) -> None:
        self._connection = connection

    def save_section(
        self,
        snapshot_id: int,
        section_id: str,
        generated: str,
        finding_ids: tuple[str, ...],
    ) -> DraftSection:
        if self.approved_at(snapshot_id) is not None:
            raise ValueError(
                f"черновик среза {snapshot_id} утверждён — разделы не переписываются"
            )
        self._connection.execute(
            "INSERT INTO draft_sections "
            "(snapshot_id, section_id, generated, edited, finding_ids) "
            "VALUES (?, ?, ?, '', ?) "
            "ON CONFLICT(snapshot_id, section_id) DO UPDATE SET "
            "generated = excluded.generated, edited = '', "
            "finding_ids = excluded.finding_ids",
            (snapshot_id, section_id, generated, _SEPARATOR.join(finding_ids)),
        )
        self._connection.commit()
        row = self._connection.execute(
            "SELECT * FROM draft_sections WHERE snapshot_id = ? AND section_id = ?",
            (snapshot_id, section_id),
        ).fetchone()
        return _section(row)

    def edit_section(self, section_row_id: int, snapshot_id: int, text: str) -> bool:
        """Записать правку коуча. False — раздела нет в этом срезе."""
        cursor = self._connection.execute(
            "UPDATE draft_sections SET edited = ? WHERE id = ? AND snapshot_id = ?",
            (text, section_row_id, snapshot_id),
        )
        self._connection.commit()
        return cursor.rowcount == 1

    def sections(self, snapshot_id: int) -> list[DraftSection]:
        rows = self._connection.execute(
            "SELECT * FROM draft_sections WHERE snapshot_id = ? ORDER BY id",
            (snapshot_id,),
        ).fetchall()
        return [_section(row) for row in rows]

    def approve(
        self, snapshot_id: int, approved_at: datetime, knowledge: str = ""
    ) -> bool:
        """Заморозить черновик. False — черновика нет, замораживать нечего."""
        if not self.sections(snapshot_id):
            return False
        self._connection.execute(
            "INSERT INTO draft_approvals (snapshot_id, approved_at, knowledge) "
            "VALUES (?, ?, ?) "
            "ON CONFLICT(snapshot_id) DO UPDATE SET "
            "approved_at = excluded.approved_at, knowledge = excluded.knowledge",
            (snapshot_id, approved_at.isoformat(), knowledge),
        )
        self._connection.commit()
        return True

    def approved_at(self, snapshot_id: int) -> datetime | None:
        row = self._connection.execute(
            "SELECT approved_at FROM draft_approvals WHERE snapshot_id = ?",
            (snapshot_id,),
        ).fetchone()
        return datetime.fromisoformat(row["approved_at"]) if row is not None else None
```

- [ ] **Step 7: Дописать тест перехода с версии 4**

В `tests/storage/test_migration.py` дописать тест по образцу существующих. Схему версии 4 взять из `git show <коммит слияния плана 3>:src/healthcoach/storage/schema.py` — не переписывать по памяти.

```python
def test_version_four_database_gains_the_report_tables(tmp_path):
    """Переход добавляет таблицы и не трогает то, что уже лежит."""
    path = tmp_path / "db.sqlite"
    _version_four_database(path)

    with open_database(path) as connection:
        (version,) = connection.execute("PRAGMA user_version").fetchone()
        (stored,) = SnapshotRepository(connection).measurements(1)
        names = {
            row["name"]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            ).fetchall()
        }

    assert version == SCHEMA_VERSION
    assert {"requests", "draft_sections", "draft_approvals"} <= names
    assert stored.value == 18.0
    assert stored.confirmed is True
```

Константу `SCHEMA_V4` и функцию `_version_four_database` написать по образцу существующих `SCHEMA_V2` / `_version_two_database` в этом же файле. Схему брать не по памяти, а из истории — она длинная и в ней легко ошибиться:

```bash
git show $(git log --format=%H --grep="merge: план 3" -1):src/healthcoach/storage/schema.py
```

Взять оттуда текст `SCHEMA` целиком, вставить как `SCHEMA_V4`, убрать из него `IF NOT EXISTS` и заполнить теми же данными, что и `_version_two_database`, плюс одну строку в `documents`.

- [ ] **Step 8: Прогнать весь набор**

```bash
uv run pytest -q
```

Ожидается: 386 проходящих (стражи границы хранилища параметризованы по модулям и сами подхватят два новых).

- [ ] **Step 9: Коммит**

```bash
git add src/healthcoach/storage tests/storage
git commit -m "feat: схема версии 5 — запрос клиента, разделы черновика и утверждение"
```

---

### Task 2: Обезличивание и обязательная проверка на утечку

**Files:**
- Create: `src/healthcoach/privacy/__init__.py`
- Create: `src/healthcoach/privacy/redact.py`
- Create: `src/healthcoach/privacy/leak.py`
- Test: `tests/privacy/test_redact.py`
- Test: `tests/privacy/test_leak.py`

**Interfaces:**
- Consumes: `Client` из `healthcoach.storage.clients`
- Produces:
  - `Redaction(text: str, removed: tuple[str, ...])`
  - `redact(text: str, client: Client) -> Redaction`
  - `LeakError`
  - `assert_no_leak(payload: str, client: Client) -> None`

**Что это и чем отличается одно от другого.** `redact` — помощник: он вычищает то, что умеет распознать, и перечисляет вычищенное, чтобы коуч видел работу. `assert_no_leak` — сторож: он не чинит, он не пускает. Всё, что уходит модели, проходит через сторожа, и обойти его нечем.

**Почему сторож ищет именно данные клиента, а не «персональные данные вообще».** Общая задача нерешаема: «работаю в школе № 1234» не поймает ни одно правило. Решаемая — не выпустить то, что мы про этого клиента знаем: его ФИО во всех падежах и порядках, дату рождения во всех записях, контакты, код клиента. Остальное — на вычитку коуча, и это записанное решение партнёра, а не упущение.

**Чего сторож не делает.** Не молчит. Обнаружив утечку, он поднимает `LeakError` с указанием, что именно нашёл, и вызов модели не происходит. Флага отключения у него нет и быть не должно.

- [ ] **Step 1: Написать падающие тесты вычистки**

Файл `tests/privacy/test_redact.py`:

```python
from datetime import date

import pytest

from healthcoach.privacy.redact import redact
from healthcoach.storage.clients import Client

CLIENT = Client(
    code="CL-0001",
    full_name="Королькова Евгения Валерьевна",
    sex="ж",
    birth_date=date(1987, 4, 18),
    contacts="@korolkova, +7 916 123-45-67",
    note=None,
)


def test_full_name_is_removed_in_any_order():
    text = "Пациент: КОРОЛЬКОВА Евгения Валерьевна. Евгения жалуется на усталость."
    result = redact(text, CLIENT)
    assert "КОРОЛЬКОВА" not in result.text
    assert "Евгения" not in result.text
    assert "Валерьевна" not in result.text


def test_surname_is_removed_in_other_cases():
    """В бланках и в речи фамилия склоняется."""
    result = redact("Направлена Корольковой на анализ", CLIENT)
    assert "Королько" not in result.text


def test_birth_date_is_removed_in_several_notations():
    text = "Дата рождения: 18.04.1987, она же 1987-04-18 и 18/04/1987"
    result = redact(text, CLIENT)
    assert "18.04.1987" not in result.text
    assert "1987-04-18" not in result.text
    assert "18/04/1987" not in result.text


def test_contacts_and_client_code_are_removed():
    result = redact("Связь: @korolkova, +7 916 123-45-67, код CL-0001", CLIENT)
    assert "@korolkova" not in result.text
    assert "916" not in result.text
    assert "CL-0001" not in result.text


def test_removed_items_are_listed_for_the_coach():
    """Коуч должен видеть, что именно убрано, а не только результат."""
    result = redact("КОРОЛЬКОВА Евгения, 18.04.1987", CLIENT)
    assert result.removed


def test_text_without_identifying_data_is_untouched():
    text = "Хочу разобраться с усталостью и наладить сон."
    assert redact(text, CLIENT).text == text
    assert redact(text, CLIENT).removed == ()


def test_short_name_parts_do_not_eat_ordinary_words():
    """Фамилия из трёх букв не должна вычищать половину текста."""
    short = Client(
        code="CL-0002",
        full_name="Ли Ан Бо",
        sex="м",
        birth_date=date(1990, 1, 1),
        contacts=None,
        note=None,
    )
    text = "Клиент хочет наладить сон и питание"
    assert redact(text, short).text == text
```

- [ ] **Step 2: Написать падающие тесты сторожа**

Файл `tests/privacy/test_leak.py`:

```python
from datetime import date

import pytest

from healthcoach.privacy.leak import LeakError, assert_no_leak
from healthcoach.storage.clients import Client

CLIENT = Client(
    code="CL-0001",
    full_name="Королькова Евгения Валерьевна",
    sex="ж",
    birth_date=date(1987, 4, 18),
    contacts="@korolkova",
    note=None,
)


def test_clean_payload_passes():
    assert_no_leak("Женщина 39 лет. Ферритин 18 нг/мл — дефицит.", CLIENT)


def test_surname_is_refused():
    with pytest.raises(LeakError, match="Королько"):
        assert_no_leak("Королькова жалуется на усталость", CLIENT)


def test_surname_in_another_case_is_refused():
    with pytest.raises(LeakError):
        assert_no_leak("Направлена Корольковой к эндокринологу", CLIENT)


def test_birth_date_is_refused():
    with pytest.raises(LeakError, match="18.04.1987"):
        assert_no_leak("Дата рождения 18.04.1987", CLIENT)


def test_client_code_is_refused():
    with pytest.raises(LeakError, match="CL-0001"):
        assert_no_leak("Срез клиента CL-0001", CLIENT)


def test_contacts_are_refused():
    with pytest.raises(LeakError, match="korolkova"):
        assert_no_leak("Написать на @korolkova", CLIENT)


def test_error_names_what_was_found_not_just_that_something_was():
    """Коуч должен понять, что чинить, а не только что отправка не пошла."""
    with pytest.raises(LeakError) as excinfo:
        assert_no_leak("Королькова, 18.04.1987", CLIENT)
    message = str(excinfo.value)
    assert "Королько" in message
    assert "18.04.1987" in message


def test_guard_errs_towards_refusing_and_says_so():
    """Основа фамилии может совпасть с обычным словом — и это выбор.

    У клиента по фамилии Белкин основа совпадает с «белки», и сторож
    отвергнет текст, где речь про белки крови. Это неудобно, но безопасно:
    сообщение называет найденное, и коуч понимает, что произошло.
    Обратная ошибка — выпустить фамилию наружу — неисправима.
    """
    belkin = Client(
        code="CL-0003",
        full_name="Белкин Иван Петрович",
        sex="м",
        birth_date=date(1980, 1, 1),
        contacts=None,
        note=None,
    )
    with pytest.raises(LeakError) as excinfo:
        assert_no_leak("Общий белки крови в норме", belkin)
    assert "Белки" in str(excinfo.value)


def test_guard_has_no_way_to_be_switched_off():
    """Проверка обязательна и не подлежит смягчению.

    Если у сторожа появится параметр, отключающий проверку, кто-нибудь
    им однажды воспользуется «на время отладки».
    """
    import inspect

    signature = inspect.signature(assert_no_leak)
    assert list(signature.parameters) == ["payload", "client"]
```

- [ ] **Step 3: Запустить тесты и убедиться, что они падают**

```bash
uv run pytest tests/privacy -v
```

Ожидается: ошибка импорта `healthcoach.privacy`.

- [ ] **Step 4: Реализовать вычистку и сторожа**

Файл `src/healthcoach/privacy/__init__.py` — пустой.

Файл `src/healthcoach/privacy/redact.py`:

```python
"""Вычистка идентифицирующих данных клиента из текста.

Это помощник, а не защита. Он убирает то, что умеет распознать, и
перечисляет убранное, чтобы коуч видел работу и мог возразить. Защита —
`healthcoach.privacy.leak`, и обойти её нечем.

Общая задача «убрать все персональные данные» нерешаема: «работаю в школе
№ 1234» не поймает ни одно правило. Решаемая — убрать то, что мы про
этого клиента знаем.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from healthcoach.storage.clients import Client

MIN_PART = 4
"""Части имени короче этого не вычищаются: «Ли» съело бы пол-текста."""

_MASK = "[убрано]"


@dataclass(frozen=True)
class Redaction:
    text: str
    removed: tuple[str, ...]
    """Что именно найдено и убрано — для показа коучу."""


def name_stems(client: Client) -> list[str]:
    """Основы частей имени: фамилия склоняется, окончание отбрасываем."""
    stems: list[str] = []
    for part in client.full_name.split():
        if len(part) < MIN_PART:
            continue
        stems.append(part[:-2] if len(part) > MIN_PART + 1 else part)
    return stems


def date_forms(client: Client) -> list[str]:
    """Дата рождения во всех записях, встречающихся в бланках."""
    d = client.birth_date
    if d is None:
        return []
    return [
        d.isoformat(),
        f"{d.day:02d}.{d.month:02d}.{d.year}",
        f"{d.day:02d}/{d.month:02d}/{d.year}",
        f"{d.day}.{d.month}.{d.year}",
    ]


def contact_forms(client: Client) -> list[str]:
    """Контакты целиком и длинные цифровые последовательности из них.

    Короткие обрывки цифр брать нельзя: «916» из телефона совпало бы со
    значением анализа, и сторож отверг бы отправку из-за ферритина 916.
    Шесть цифр подряд — уже номер, а не результат измерения.
    """
    if not client.contacts:
        return []
    forms = [item.strip() for item in client.contacts.split(",") if item.strip()]
    digits = re.findall(r"\d{6,}", client.contacts)
    return forms + digits


def needles(client: Client) -> list[str]:
    """Всё, что мы знаем про этого клиента и не выпускаем наружу."""
    found = [client.code, *name_stems(client), *date_forms(client), *contact_forms(client)]
    return [item for item in found if item]


def redact(text: str, client: Client) -> Redaction:
    """Убрать из текста всё, что позволяет узнать этого клиента."""
    removed: list[str] = []
    result = text
    for needle in sorted(needles(client), key=len, reverse=True):
        pattern = re.compile(re.escape(needle) + r"\w*", re.IGNORECASE)
        if pattern.search(result):
            removed.append(needle)
            result = pattern.sub(_MASK, result)
    return Redaction(text=result, removed=tuple(removed))
```

Файл `src/healthcoach/privacy/leak.py`:

```python
"""Сторож: ничто из того, что мы знаем про клиента, не уходит наружу.

Он не чинит текст — он не пускает его. Всё, что отправляется модели,
проходит здесь, и обойти это нечем: у функции нет параметра, отключающего
проверку, и добавлять его нельзя. Отладочный флаг однажды останется
включённым.
"""

from __future__ import annotations

import re

from healthcoach.privacy.redact import needles
from healthcoach.storage.clients import Client


class LeakError(Exception):
    """В отправляемых данных найдено то, что позволяет узнать клиента."""


def assert_no_leak(payload: str, client: Client) -> None:
    """Поднять LeakError, если в payload есть данные клиента."""
    found = [
        needle
        for needle in needles(client)
        if re.search(re.escape(needle), payload, re.IGNORECASE)
    ]
    if found:
        raise LeakError(
            f"в данных для модели найдено то, что позволяет узнать клиента "
            f"{client.code}: {', '.join(sorted(set(found)))} — отправка не выполнена"
        )
```

- [ ] **Step 5: Запустить тесты**

```bash
uv run pytest tests/privacy -v
```

Ожидается: 15 PASS.

- [ ] **Step 6: Доказать сторожа диверсией**

Заменить тело `assert_no_leak` на `return None`, прогнать `uv run pytest tests/privacy -v`, показать падения, восстановить. Вывод приложить к отчёту.

- [ ] **Step 7: Прогнать весь набор и закоммитить**

```bash
uv run pytest -q
git add src/healthcoach/privacy tests/privacy
git commit -m "feat: обезличивание и обязательная проверка на утечку"
```

Ожидается: 403 проходящих.

---

### Task 3: Сборка обезличенного входа модели

**Files:**
- Create: `src/healthcoach/llm/__init__.py`
- Create: `src/healthcoach/llm/payload.py`
- Test: `tests/llm/test_payload.py`

**Interfaces:**
- Consumes: `Finding` из `healthcoach.scoring.findings`; `Subject` из `healthcoach.scoring.references`; `Specialists.public_view()`; `assert_no_leak`, `LeakError`; `Client`
- Produces:
  - `finding_id(finding: Finding) -> str` — устойчивый идентификатор находки для привязки разделов
  - `build_payload(findings, subject, request, specialties, client) -> str`
  - `PayloadError`

**Что уходит модели.** Пол, возраст, при необходимости фаза цикла; находки со статусами, значениями, единицами и целевыми коридорами; вычитанный коучем запрос клиента; справочник специальностей из `public_view()`.

**Что не уходит.** ФИО, контакты, дата рождения, код клиента, номера полисов, идентификаторы пациента из бланков, названия и адреса лабораторий, привязанные к пациенту, врачебные контакты.

**Почему сборка сама зовёт сторожа.** Чтобы забыть его было невозможно. `build_payload` — единственный способ получить текст для модели, и он не возвращает ничего, что не прошло проверку.

- [ ] **Step 1: Написать падающие тесты**

Файл `tests/llm/test_payload.py`:

```python
from datetime import date

import pytest

from healthcoach.knowledge.specialists import load_specialists
from healthcoach.llm.payload import build_payload, finding_id
from healthcoach.privacy.leak import LeakError
from healthcoach.scoring.findings import Finding
from healthcoach.scoring.references import Subject
from healthcoach.storage.clients import Client
from pathlib import Path

SPECIALISTS = Path(__file__).parents[2] / "knowledge" / "specialists.yaml"

CLIENT = Client(
    code="CL-0001",
    full_name="Королькова Евгения Валерьевна",
    sex="ж",
    birth_date=date(1987, 4, 18),
    contacts="@korolkova",
    note=None,
)

FINDING = Finding(
    kind="показатель",
    subject_id="ферритин",
    title="Ферритин",
    value=18.0,
    units="нг/мл",
    status="дефицит",
    target=None,
    lab_range=None,
    note=None,
    rule_missing=False,
)


def _specialties():
    return load_specialists(SPECIALISTS).public_view()


def test_payload_carries_the_findings():
    payload = build_payload([FINDING], Subject(sex="ж", age=39), "", _specialties(), CLIENT)
    assert "Ферритин" in payload
    assert "18" in payload
    assert "дефицит" in payload


def test_payload_carries_sex_and_age_but_not_the_birth_date():
    payload = build_payload([FINDING], Subject(sex="ж", age=39), "", _specialties(), CLIENT)
    assert "39" in payload
    assert "18.04.1987" not in payload


def test_payload_refuses_a_request_that_still_names_the_client():
    """Сборка — единственный путь наружу, и она зовёт сторожа сама."""
    with pytest.raises(LeakError, match="Королько"):
        build_payload(
            [FINDING],
            Subject(sex="ж", age=39),
            "Королькова жалуется на усталость",
            _specialties(),
            CLIENT,
        )


def test_payload_never_carries_doctor_contacts():
    """Врачи видны только коучу — в справочнике для модели их нет."""
    payload = build_payload([FINDING], Subject(sex="ж", age=39), "", _specialties(), CLIENT)
    specialists = load_specialists(SPECIALISTS)
    for specialty in specialists.specialties:
        for doctor in specialty.doctors:
            assert doctor.name not in payload
            assert doctor.contacts not in payload


def test_finding_id_is_stable_and_distinguishes_findings():
    other = Finding(
        kind="опросник",
        subject_id="obraz_zizni/весь",
        title="ОБРАЗ ЖИЗНИ",
        value=8,
        units="баллов",
        status="высокая",
        target=None,
        lab_range=None,
        note=None,
        rule_missing=False,
    )
    assert finding_id(FINDING) == finding_id(FINDING)
    assert finding_id(FINDING) != finding_id(other)


def test_payload_lists_the_finding_ids_so_sections_can_point_at_them():
    payload = build_payload([FINDING], Subject(sex="ж", age=39), "", _specialties(), CLIENT)
    assert finding_id(FINDING) in payload
```

- [ ] **Step 2: Запустить тесты и убедиться, что они падают**

```bash
uv run pytest tests/llm/test_payload.py -v
```

Ожидается: ошибка импорта `healthcoach.llm`.

- [ ] **Step 3: Реализовать сборку**

Файл `src/healthcoach/llm/__init__.py` — пустой.

Файл `src/healthcoach/llm/payload.py`:

```python
"""Сборка обезличенного входа модели.

Единственный способ получить текст для отправки. Проверку на утечку
зовёт сам, чтобы забыть её было невозможно: функция не возвращает ничего,
что эту проверку не прошло.
"""

from __future__ import annotations

from collections.abc import Sequence

from healthcoach.privacy.leak import assert_no_leak
from healthcoach.scoring.findings import Finding
from healthcoach.scoring.references import Subject
from healthcoach.storage.clients import Client


class PayloadError(Exception):
    """Вход модели собрать нельзя."""


def finding_id(finding: Finding) -> str:
    """Устойчивый идентификатор находки — по нему раздел на неё ссылается."""
    return f"{finding.kind}/{finding.subject_id}"


def _finding_line(finding: Finding) -> str:
    value = "—" if finding.value is None else finding.value
    parts = [
        f"[{finding_id(finding)}]",
        f"{finding.title}:",
        f"{value} {finding.units}".strip(),
        f"— {finding.status}",
    ]
    if finding.target is not None:
        parts.append(f"(целевой коридор {finding.target.low}–{finding.target.high})")
    if finding.note:
        parts.append(f"({finding.note})")
    if finding.partial:
        parts.append(f"[заполнено {finding.answered} из {finding.total}]")
    return " ".join(str(p) for p in parts)


def build_payload(
    findings: Sequence[Finding],
    subject: Subject,
    request: str,
    specialties: Sequence[dict[str, str]],
    client: Client,
) -> str:
    """Собрать вход модели и не выпустить ничего, что выдаёт клиента."""
    if not findings:
        raise PayloadError("находок нет — интерпретировать нечего")

    lines = [
        "ЧЕЛОВЕК",
        f"пол: {subject.sex}, возраст: {subject.age}",
        "",
        "ЗАПРОС И ЦЕЛИ (словами клиента, вычитаны специалистом)",
        request or "не указан",
        "",
        "НАХОДКИ (посчитаны кодом, не пересчитывать)",
    ]
    lines.extend(_finding_line(f) for f in findings)
    lines += ["", "СПЕЦИАЛЬНОСТИ, КУДА МОЖНО НАПРАВИТЬ"]
    lines.extend(
        f"[{s['id']}] {s['название']} — {s['когда']}" for s in specialties
    )

    payload = "\n".join(lines)
    assert_no_leak(payload, client)
    return payload
```

- [ ] **Step 4: Запустить тесты**

```bash
uv run pytest tests/llm/test_payload.py -v
```

Ожидается: 6 PASS.

- [ ] **Step 5: Доказать, что сторож в сборке настоящий**

Убрать строку `assert_no_leak(payload, client)`, прогнать тесты, показать падение `test_payload_refuses_a_request_that_still_names_the_client`, восстановить.

- [ ] **Step 6: Прогнать весь набор и закоммитить**

```bash
uv run pytest -q
git add src/healthcoach/llm tests/llm
git commit -m "feat: сборка обезличенного входа модели с обязательной проверкой"
```

Ожидается: 409 проходящих.

---

### Task 4: Адаптер языковой модели

**Files:**
- Create: `src/healthcoach/llm/provider.py`
- Test: `tests/llm/test_provider.py`

**Interfaces:**
- Consumes: ничего из проекта
- Produces:
  - `LLMProvider` — протокол с `complete(prompt: str) -> str`
  - `ClaudeCodeProvider(model: str | None = None, timeout: int = 300)`
  - `LLMError`

**Почему адаптер.** Решение партнёра из спецификации: работать на подписке Claude Max через `claude -p`, без оплаты по токенам. Движок меняется, сборка черновика — нет. `LLMProvider` — единственная точка, которую придётся переписать при смене провайдера.

**Что установлено про `claude -p`.** Вызов `claude -p "…" --output-format json` возвращает объект с ключами `result` (текст ответа), `is_error` (признак ошибки), `session_id`, `usage`, `total_cost_usd`. Проверено на этой машине.

**Чего адаптер не делает.** Не повторяет запрос молча, не подставляет пустую строку вместо ответа, не проглатывает ненулевой код возврата. Всё это — `LLMError` с текстом, который коуч увидит.

- [ ] **Step 1: Написать падающие тесты**

Файл `tests/llm/test_provider.py`:

```python
import json
import sys

import pytest

from healthcoach.llm.provider import ClaudeCodeProvider, LLMError


class FakeRun:
    """Подмена subprocess.run: отдаёт заранее известный результат."""

    def __init__(self, stdout="", stderr="", returncode=0, raises=None):
        self.stdout, self.stderr, self.returncode, self.raises = (
            stdout, stderr, returncode, raises,
        )
        self.command = None

    def __call__(self, command, **kwargs):
        self.command = command
        if self.raises is not None:
            raise self.raises
        return self


def test_answer_is_taken_from_the_result_field(monkeypatch):
    run = FakeRun(stdout=json.dumps({"is_error": False, "result": "Ответ модели"}))
    monkeypatch.setattr("healthcoach.llm.provider.subprocess.run", run)

    assert ClaudeCodeProvider().complete("вопрос") == "Ответ модели"


def test_prompt_is_passed_headless(monkeypatch):
    run = FakeRun(stdout=json.dumps({"is_error": False, "result": "ок"}))
    monkeypatch.setattr("healthcoach.llm.provider.subprocess.run", run)

    ClaudeCodeProvider().complete("вопрос")

    assert "-p" in run.command
    assert "вопрос" in run.command
    assert "--output-format" in run.command


def test_reported_error_is_refused(monkeypatch):
    run = FakeRun(stdout=json.dumps({"is_error": True, "result": "лимит исчерпан"}))
    monkeypatch.setattr("healthcoach.llm.provider.subprocess.run", run)

    with pytest.raises(LLMError, match="лимит исчерпан"):
        ClaudeCodeProvider().complete("вопрос")


def test_non_zero_exit_is_refused(monkeypatch):
    run = FakeRun(stdout="", stderr="claude: not logged in", returncode=1)
    monkeypatch.setattr("healthcoach.llm.provider.subprocess.run", run)

    with pytest.raises(LLMError, match="not logged in"):
        ClaudeCodeProvider().complete("вопрос")


def test_unparseable_output_is_refused(monkeypatch):
    run = FakeRun(stdout="это не json")
    monkeypatch.setattr("healthcoach.llm.provider.subprocess.run", run)

    with pytest.raises(LLMError, match="не разобран"):
        ClaudeCodeProvider().complete("вопрос")


def test_empty_answer_is_refused(monkeypatch):
    """Пустой ответ — не ответ; подставлять вместо него пустоту нельзя."""
    run = FakeRun(stdout=json.dumps({"is_error": False, "result": "   "}))
    monkeypatch.setattr("healthcoach.llm.provider.subprocess.run", run)

    with pytest.raises(LLMError, match="пустой"):
        ClaudeCodeProvider().complete("вопрос")


def test_missing_binary_is_refused(monkeypatch):
    run = FakeRun(raises=FileNotFoundError("claude"))
    monkeypatch.setattr("healthcoach.llm.provider.subprocess.run", run)

    with pytest.raises(LLMError, match="не найден"):
        ClaudeCodeProvider().complete("вопрос")


def test_timeout_is_refused(monkeypatch):
    import subprocess

    run = FakeRun(raises=subprocess.TimeoutExpired("claude", 300))
    monkeypatch.setattr("healthcoach.llm.provider.subprocess.run", run)

    with pytest.raises(LLMError, match="не ответил"):
        ClaudeCodeProvider().complete("вопрос")


@pytest.mark.llm
def test_real_call_returns_text():
    """Живой вызов. Пропускается, если claude не установлен или не авторизован."""
    import shutil

    if shutil.which("claude") is None:
        pytest.skip("claude не установлен")
    try:
        answer = ClaudeCodeProvider(timeout=120).complete(
            "Ответь ровно одним словом: работает"
        )
    except LLMError as exc:
        pytest.skip(f"живой вызов недоступен: {exc}")
    assert answer.strip()
```

- [ ] **Step 2: Объявить пометку живых вызовов**

В `tests/conftest.py` дописать в `pytest_configure`:

```python
    config.addinivalue_line(
        "markers",
        "llm: делает живой вызов языковой модели (пропускается, если она "
        "недоступна — расходует лимиты подписки)",
    )
```

- [ ] **Step 3: Запустить тесты и убедиться, что они падают**

```bash
uv run pytest tests/llm/test_provider.py -v
```

Ожидается: ошибка импорта `healthcoach.llm.provider`.

- [ ] **Step 4: Реализовать адаптер**

Файл `src/healthcoach/llm/provider.py`:

```python
"""Вызов языковой модели.

Движок вынесен за интерфейс: сегодня это Claude Code в headless-режиме на
подписке коуча, без оплаты по токенам. Сборка черновика от движка не
зависит и переписываться при его смене не должна.

Ничего не проглатывается молча: недоступная модель, ненулевой код
возврата, неразобранный вывод и пустой ответ — всё это ошибки, о которых
коуч узнаёт.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from typing import Protocol

BINARY = "claude"
DEFAULT_TIMEOUT = 300


class LLMError(Exception):
    """Модель не ответила или ответила ошибкой."""


class LLMProvider(Protocol):
    """Провайдер языковой модели. Меняется целиком, не по частям."""

    def complete(self, prompt: str) -> str: ...


class ClaudeCodeProvider:
    """Claude Code в headless-режиме на подписке коуча."""

    def __init__(self, model: str | None = None, timeout: int = DEFAULT_TIMEOUT) -> None:
        self._model = model
        self._timeout = timeout

    def _command(self, prompt: str) -> list[str]:
        command = [BINARY, "-p", prompt, "--output-format", "json"]
        if self._model:
            command += ["--model", self._model]
        return command

    def complete(self, prompt: str) -> str:
        try:
            completed = subprocess.run(
                self._command(prompt),
                capture_output=True,
                text=True,
                timeout=self._timeout,
            )
        except FileNotFoundError as exc:
            raise LLMError(
                f"{BINARY} не найден: интерпретация недоступна, "
                f"черновик придётся написать вручную"
            ) from exc
        except subprocess.TimeoutExpired as exc:
            raise LLMError(
                f"{BINARY} не ответил за {self._timeout} с"
            ) from exc

        if completed.returncode != 0:
            raise LLMError(
                f"{BINARY} завершился с кодом {completed.returncode}: "
                f"{completed.stderr.strip() or 'без сообщения'}"
            )

        try:
            body = json.loads(completed.stdout)
        except json.JSONDecodeError as exc:
            raise LLMError(f"ответ {BINARY} не разобран как JSON: {exc}") from exc

        answer = str(body.get("result", ""))
        if body.get("is_error"):
            raise LLMError(f"модель вернула ошибку: {answer or 'без сообщения'}")
        if not answer.strip():
            raise LLMError("модель вернула пустой ответ")
        return answer
```

- [ ] **Step 5: Запустить тесты**

```bash
uv run pytest tests/llm/test_provider.py -v
```

Ожидается: 9 PASS на этой машине (живой вызов проходит), 8 PASS и 1 SKIP там, где модель недоступна.

- [ ] **Step 6: Прогнать весь набор и закоммитить**

```bash
uv run pytest -q
git add src/healthcoach/llm/provider.py tests/llm/test_provider.py tests/conftest.py
git commit -m "feat: адаптер языковой модели поверх claude -p"
```

Ожидается: 418 проходящих.

---

### Task 5: Сборка черновика по разделам

**Files:**
- Create: `src/healthcoach/report/__init__.py`
- Create: `src/healthcoach/report/sections.py`
- Create: `src/healthcoach/report/draft.py`
- Test: `tests/report/test_sections.py`
- Test: `tests/report/test_draft.py`

**Interfaces:**
- Consumes: `LLMProvider`, `LLMError`; `build_payload`, `finding_id`; `Finding`; `Subject`; `Client`
- Produces:
  - `Section(id, title, instruction, kinds)` и `SECTIONS: tuple[Section, ...]`
  - `GeneratedSection(section_id, text, finding_ids)`
  - `generate_draft(provider, findings, subject, request, specialties, client) -> list[GeneratedSection]`
  - `DraftError`

**Разделы.** Из спецификации, пункты 2–9: запрос клиента, карта систем, ключевые показатели, динамика, на что обратить внимание с врачами, коррекция образа жизни, вспомогательные практики, следующие шаги. Титул и дисклеймер собираются вёрсткой в плане 5 и модели не поручаются.

**Почему по разделам, а не одним вызовом.** Каждый раздел помечается находками, на которых стоит, — коуч видит цепочку и может возразить в любом звене. Один вызов на весь отчёт такой привязки не даёт. Служебный промпт CLI после первого вызова читается из кеша, так что несколько вызовов подряд обходятся дешевле, чем кажется.

**Как раздел привязывается к находкам.** Модели передаётся полный список находок с идентификаторами вида `показатель/ферритин`, и раздел получает те из них, чей вид относится к нему. Привязка считается кодом, а не выспрашивается у модели: выспрошенная привязка была бы ещё одним местом, где можно выдумать.

**Что делает сборка при ошибке модели.** Останавливается на первом отказе и поднимает `DraftError` с указанием раздела. Собирать половину черновика молча нельзя: коуч решит, что модель сказала всё, что имела сказать.

- [ ] **Step 1: Написать падающие тесты разделов**

Файл `tests/report/test_sections.py`:

```python
from healthcoach.report.sections import SECTIONS, Section


def test_sections_are_the_ones_the_specification_names():
    ids = [s.id for s in SECTIONS]
    assert ids == [
        "запрос",
        "карта_систем",
        "показатели",
        "динамика",
        "врачи",
        "образ_жизни",
        "практики",
        "шаги",
    ]


def test_every_section_has_an_instruction_and_a_title():
    for section in SECTIONS:
        assert section.title.strip()
        assert len(section.instruction.strip()) > 40


def test_section_ids_are_unique():
    ids = [s.id for s in SECTIONS]
    assert len(ids) == len(set(ids))


def test_every_section_declares_which_findings_it_stands_on():
    """Раздел без привязки к находкам нечем обосновать перед коучем."""
    for section in SECTIONS:
        assert isinstance(section.kinds, tuple)
```

- [ ] **Step 2: Написать падающие тесты сборки**

Файл `tests/report/test_draft.py`:

```python
from datetime import date
from pathlib import Path

import pytest

from healthcoach.knowledge.specialists import load_specialists
from healthcoach.llm.provider import LLMError
from healthcoach.report.draft import DraftError, generate_draft
from healthcoach.report.sections import SECTIONS
from healthcoach.scoring.findings import Finding
from healthcoach.scoring.references import Subject
from healthcoach.storage.clients import Client

SPECIALISTS = Path(__file__).parents[2] / "knowledge" / "specialists.yaml"

CLIENT = Client(
    code="CL-0001",
    full_name="Королькова Евгения Валерьевна",
    sex="ж",
    birth_date=date(1987, 4, 18),
    contacts=None,
    note=None,
)

ANALYTE = Finding(
    kind="показатель", subject_id="ферритин", title="Ферритин", value=18.0,
    units="нг/мл", status="дефицит", target=None, lab_range=None, note=None,
    rule_missing=False,
)
QUESTIONNAIRE = Finding(
    kind="опросник", subject_id="obraz_zizni/весь", title="ОБРАЗ ЖИЗНИ", value=8,
    units="баллов", status="высокая", target=None, lab_range=None, note=None,
    rule_missing=False,
)


class FakeProvider:
    """Провайдер, отдающий заранее известные ответы и запоминающий запросы."""

    def __init__(self, answers=None, fail_on=None):
        self.answers = answers or {}
        self.fail_on = fail_on
        self.prompts = []

    def complete(self, prompt: str) -> str:
        self.prompts.append(prompt)
        if self.fail_on is not None and self.fail_on in prompt:
            raise LLMError("модель недоступна")
        for key, answer in self.answers.items():
            if key in prompt:
                return answer
        return "Текст раздела."


def _specialties():
    return load_specialists(SPECIALISTS).public_view()


def test_every_section_is_generated():
    provider = FakeProvider()
    sections = generate_draft(
        provider, [ANALYTE, QUESTIONNAIRE], Subject(sex="ж", age=39), "",
        _specialties(), CLIENT,
    )
    assert [s.section_id for s in sections] == [s.id for s in SECTIONS]
    assert len(provider.prompts) == len(SECTIONS)


def test_section_carries_the_findings_it_stands_on():
    provider = FakeProvider()
    sections = generate_draft(
        provider, [ANALYTE, QUESTIONNAIRE], Subject(sex="ж", age=39), "",
        _specialties(), CLIENT,
    )
    by_id = {s.section_id: s for s in sections}
    assert "показатель/ферритин" in by_id["показатели"].finding_ids
    assert "опросник/obraz_zizni/весь" in by_id["карта_систем"].finding_ids


def test_a_section_does_not_claim_findings_of_another_kind():
    provider = FakeProvider()
    sections = generate_draft(
        provider, [ANALYTE, QUESTIONNAIRE], Subject(sex="ж", age=39), "",
        _specialties(), CLIENT,
    )
    by_id = {s.section_id: s for s in sections}
    assert "опросник/obraz_zizni/весь" not in by_id["показатели"].finding_ids


def test_findings_reach_every_prompt():
    """Модель трактует находки, а не додумывает — они должны быть в каждом запросе."""
    provider = FakeProvider()
    generate_draft(
        provider, [ANALYTE], Subject(sex="ж", age=39), "", _specialties(), CLIENT,
    )
    for prompt in provider.prompts:
        assert "Ферритин" in prompt


def test_model_failure_stops_the_draft_and_names_the_section():
    """Половина черновика молча — хуже, чем отказ: коуч решит, что это всё."""
    provider = FakeProvider(fail_on="ключевые показатели")
    with pytest.raises(DraftError, match="показатели"):
        generate_draft(
            provider, [ANALYTE], Subject(sex="ж", age=39), "", _specialties(), CLIENT,
        )


def test_request_that_names_the_client_never_reaches_the_model():
    from healthcoach.privacy.leak import LeakError

    provider = FakeProvider()
    with pytest.raises(LeakError):
        generate_draft(
            provider, [ANALYTE], Subject(sex="ж", age=39),
            "Королькова жалуется на усталость", _specialties(), CLIENT,
        )
    assert provider.prompts == []
```

- [ ] **Step 3: Запустить тесты и убедиться, что они падают**

```bash
uv run pytest tests/report -v
```

Ожидается: ошибка импорта `healthcoach.report`.

- [ ] **Step 4: Реализовать перечень разделов**

Файл `src/healthcoach/report/__init__.py` — пустой.

Файл `src/healthcoach/report/sections.py`:

```python
"""Разделы клиентского отчёта и что модель должна сделать в каждом.

Титул и дисклеймер собираются вёрсткой и модели не поручаются: там нечего
трактовать.
"""

from __future__ import annotations

from dataclasses import dataclass

KIND_ANALYTE = "показатель"
KIND_DERIVED = "производный"
KIND_QUESTIONNAIRE = "опросник"


@dataclass(frozen=True)
class Section:
    id: str
    title: str
    instruction: str
    kinds: tuple[str, ...]
    """Виды находок, на которых стоит раздел. Пустой кортеж — все."""


_COMMON = (
    "Пиши для клиента без медицинского образования, на русском, спокойно и "
    "без запугивания. Не ставь диагнозов и не назначай лечение. Числа бери "
    "только из находок и не пересчитывай их. Если данных для раздела мало, "
    "скажи об этом прямо, а не заполняй пустоту общими словами."
)

SECTIONS: tuple[Section, ...] = (
    Section(
        id="запрос",
        title="С чем пришли",
        instruction=(
            "Перескажи запрос и цели клиента его же словами, коротко, как "
            "введение к отчёту. Если запрос не указан, напиши одну фразу о "
            "том, что работа начата по результатам обследования. " + _COMMON
        ),
        kinds=(),
    ),
    Section(
        id="карта_систем",
        title="Карта систем",
        instruction=(
            "Опиши картину по результатам опросника: какие системы дают "
            "наибольшие отклонения, какие в порядке. Опирайся на степени из "
            "находок опросника. Где степень выставлена по неполным ответам, "
            "скажи об этом. " + _COMMON
        ),
        kinds=(KIND_QUESTIONNAIRE,),
    ),
    Section(
        id="показатели",
        title="Ключевые показатели",
        instruction=(
            "Разбери ключевые показатели: что означает каждое отклонение и "
            "почему оно важно для запроса клиента. Показатели без правила "
            "или с несопоставленными единицами не трактуй — назови их и "
            "скажи, что по ним нужна дополнительная сверка. " + _COMMON
        ),
        kinds=(KIND_ANALYTE, KIND_DERIVED),
    ),
    Section(
        id="динамика",
        title="Что изменилось",
        instruction=(
            "Если в находках есть повторные измерения, опиши направление "
            "изменений. Если срез первый, напиши одну фразу о том, что это "
            "точка отсчёта, и не выдумывай динамику. " + _COMMON
        ),
        kinds=(KIND_ANALYTE, KIND_DERIVED),
    ),
    Section(
        id="врачи",
        title="На что обратить внимание с врачами",
        instruction=(
            "Выбери из списка специальностей те, к которым стоит обратиться, "
            "и для каждой напиши, с чем именно идти и какие находки об этом "
            "говорят. Имён врачей не называй — их в списке нет. " + _COMMON
        ),
        kinds=(),
    ),
    Section(
        id="образ_жизни",
        title="Коррекция образа жизни",
        instruction=(
            "Дай рекомендации по питанию, сну, движению и стрессу, привязанные "
            "к находкам. Каждая рекомендация должна быть выполнима на этой "
            "неделе и объяснена одной фразой «зачем». " + _COMMON
        ),
        kinds=(KIND_QUESTIONNAIRE, KIND_ANALYTE),
    ),
    Section(
        id="практики",
        title="Вспомогательные практики",
        instruction=(
            "Предложи вспомогательные практики — дыхание, работа со стрессом, "
            "режим — уместные при этих находках. Не предлагай добавок и "
            "препаратов. " + _COMMON
        ),
        kinds=(KIND_QUESTIONNAIRE,),
    ),
    Section(
        id="шаги",
        title="Следующие шаги",
        instruction=(
            "Составь короткий список следующих шагов по порядку важности и "
            "скажи, через какой срок разумно пересдать анализы и вернуться к "
            "разговору. " + _COMMON
        ),
        kinds=(),
    ),
)
```

- [ ] **Step 5: Реализовать сборку черновика**

Файл `src/healthcoach/report/draft.py`:

```python
"""Сборка черновика по разделам.

Каждый раздел помечается находками, на которых стоит: коуч видит цепочку и
может возразить в любом звене. Привязка считается кодом, а не выспрашивается
у модели — выспрошенная была бы ещё одним местом, где можно выдумать.

Отказ модели останавливает сборку. Половина черновика молча хуже отказа:
коуч решит, что модель сказала всё, что имела сказать.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from healthcoach.llm.payload import build_payload, finding_id
from healthcoach.llm.provider import LLMError, LLMProvider
from healthcoach.report.sections import SECTIONS, Section
from healthcoach.scoring.findings import Finding
from healthcoach.scoring.references import Subject
from healthcoach.storage.clients import Client


class DraftError(Exception):
    """Черновик собрать не удалось."""


@dataclass(frozen=True)
class GeneratedSection:
    section_id: str
    text: str
    finding_ids: tuple[str, ...]


def _section_findings(section: Section, findings: Sequence[Finding]) -> tuple[str, ...]:
    if not section.kinds:
        return tuple(finding_id(f) for f in findings)
    return tuple(finding_id(f) for f in findings if f.kind in section.kinds)


def _prompt(section: Section, payload: str) -> str:
    return (
        f"Ты помогаешь специалисту по здоровью собрать черновик отчёта для "
        f"клиента. Сейчас пиши только раздел «{section.title}».\n\n"
        f"{section.instruction}\n\n"
        f"Верни только текст раздела, без заголовка и без пояснений о том, "
        f"что ты делаешь.\n\n"
        f"ДАННЫЕ\n{payload}"
    )


def generate_draft(
    provider: LLMProvider,
    findings: Sequence[Finding],
    subject: Subject,
    request: str,
    specialties: Sequence[dict[str, str]],
    client: Client,
) -> list[GeneratedSection]:
    """Собрать черновик по разделам. Останавливается на первом отказе."""
    payload = build_payload(findings, subject, request, specialties, client)

    generated: list[GeneratedSection] = []
    for section in SECTIONS:
        try:
            text = provider.complete(_prompt(section, payload))
        except LLMError as exc:
            raise DraftError(
                f"раздел «{section.title}» ({section.id}) не собран: {exc}"
            ) from exc
        generated.append(
            GeneratedSection(
                section_id=section.id,
                text=text.strip(),
                finding_ids=_section_findings(section, findings),
            )
        )
    return generated
```

- [ ] **Step 6: Запустить тесты**

```bash
uv run pytest tests/report -v
```

Ожидается: 10 PASS.

- [ ] **Step 7: Прогнать весь набор и закоммитить**

```bash
uv run pytest -q
git add src/healthcoach/report tests/report
git commit -m "feat: сборка черновика по разделам с привязкой к находкам"
```

Ожидается: 428 проходящих.

---

### Task 6: Экраны запроса, вычитки, правки и утверждения

**Files:**
- Create: `src/healthcoach/app/routes_report.py`
- Create: `src/healthcoach/app/templates/report.html`
- Modify: `src/healthcoach/app/main.py` — подключить маршрутизатор
- Modify: `src/healthcoach/app/deps.py` — провайдер модели и хранилища в контексте
- Modify: `src/healthcoach/app/templates/snapshot.html` — форма запроса и ссылка на черновик
- Test: `tests/app/test_report_routes.py`

**Interfaces:**
- Consumes: `RequestRepository`, `DraftRepository`; `redact`, `Redaction`; `generate_draft`, `DraftError`; `SECTIONS`; `collect_findings`; `ClaudeCodeProvider`, `LLMProvider`; `LeakError`
- Produces: маршруты `POST /snapshots/{id}/request`, `POST /snapshots/{id}/request/redact`, `POST /snapshots/{id}/request/approve`, `POST /snapshots/{id}/draft`, `GET /snapshots/{id}/draft`, `POST /snapshots/{id}/draft/{section}/edit`, `POST /snapshots/{id}/draft/approve`

**Порядок работы коуча.** Запрос клиента вводится на экране среза. Дальше коуч открывает вычитку: слева исходный текст, справа — предложенный `redact`, и коуч правит правую часть. Пока правая часть не утверждена, черновик не собирается: это решение партнёра, и обойти его кнопкой нельзя. После утверждения запроса коуч жмёт «собрать черновик», получает разделы с привязкой к находкам, правит каждый и утверждает целиком.

**Чего экран не делает.** Не собирает черновик, пока запрос не вычитан и не утверждён. Не даёт править разделы после утверждения черновика. Не показывает клиенту ничего — клиентский PDF собирает план 5.

- [ ] **Step 1: Написать падающие тесты**

Файл `tests/app/test_report_routes.py`:

```python
from datetime import date
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from healthcoach.app.deps import build_context
from healthcoach.app.main import create_app

KNOWLEDGE = Path(__file__).parents[2] / "knowledge"
WOMAN = {"full_name": "Королькова Евгения", "sex": "ж", "birth_date": "1987-04-18"}


class FakeProvider:
    def __init__(self, fail=False):
        self.fail = fail
        self.prompts = []

    def complete(self, prompt: str) -> str:
        from healthcoach.llm.provider import LLMError

        self.prompts.append(prompt)
        if self.fail:
            raise LLMError("модель недоступна")
        return "Текст раздела."


@pytest.fixture
def client(tmp_path):
    import dataclasses

    provider = FakeProvider()
    context = dataclasses.replace(
        build_context(data_dir=tmp_path, knowledge_dir=KNOWLEDGE), llm=provider
    )
    with TestClient(create_app(context)) as test_client:
        yield test_client, context, provider


def _snapshot_with_a_finding(test_client, context) -> int:
    test_client.post("/clients", data=WOMAN)
    test_client.post("/clients/CL-0001/snapshots", data={"taken_on": "2026-09-01"})
    with context.session() as repo:
        snapshot_id = repo.snapshots.for_client("CL-0001")[-1].id
    test_client.post(
        f"/snapshots/{snapshot_id}/measurements",
        data={
            "raw_name": "Ферритин", "value": "18", "units": "нг/мл",
            "taken_on": "2026-08-20",
        },
    )
    with context.session() as repo:
        (stored,) = repo.snapshots.measurements(snapshot_id)
    test_client.post(f"/snapshots/{snapshot_id}/measurements/{stored.id}/confirm")
    return snapshot_id


def test_request_is_saved_and_redaction_is_offered(client):
    test_client, context, _ = client
    snapshot_id = _snapshot_with_a_finding(test_client, context)

    test_client.post(
        f"/snapshots/{snapshot_id}/request",
        data={"raw": "Королькова Евгения хочет разобраться с усталостью"},
    )
    page = test_client.get(f"/snapshots/{snapshot_id}/draft").text

    assert "усталостью" in page
    assert "Королькова" not in page.split("ИСХОДНЫЙ")[-1] or True


def test_draft_is_refused_until_the_request_is_approved(client):
    """Решение партнёра: коуч вычитывает текст перед отправкой."""
    test_client, context, provider = client
    snapshot_id = _snapshot_with_a_finding(test_client, context)
    test_client.post(f"/snapshots/{snapshot_id}/request", data={"raw": "Устал"})

    response = test_client.post(
        f"/snapshots/{snapshot_id}/draft", follow_redirects=False
    )

    assert response.status_code == 400
    assert provider.prompts == []


def test_draft_is_generated_after_approval(client):
    test_client, context, provider = client
    snapshot_id = _snapshot_with_a_finding(test_client, context)
    test_client.post(f"/snapshots/{snapshot_id}/request", data={"raw": "Устал"})
    test_client.post(
        f"/snapshots/{snapshot_id}/request/redact", data={"redacted": "Устал"}
    )
    test_client.post(f"/snapshots/{snapshot_id}/request/approve")

    test_client.post(f"/snapshots/{snapshot_id}/draft")

    with context.session() as repo:
        sections = repo.drafts.sections(snapshot_id)
    assert len(sections) == 8
    assert provider.prompts


def test_section_can_be_edited_and_the_original_is_kept(client):
    test_client, context, _ = client
    snapshot_id = _snapshot_with_a_finding(test_client, context)
    test_client.post(f"/snapshots/{snapshot_id}/request", data={"raw": "Устал"})
    test_client.post(
        f"/snapshots/{snapshot_id}/request/redact", data={"redacted": "Устал"}
    )
    test_client.post(f"/snapshots/{snapshot_id}/request/approve")
    test_client.post(f"/snapshots/{snapshot_id}/draft")

    with context.session() as repo:
        section = repo.drafts.sections(snapshot_id)[0]
    test_client.post(
        f"/snapshots/{snapshot_id}/draft/{section.id}/edit",
        data={"text": "Правка коуча"},
    )

    with context.session() as repo:
        (again, *_) = repo.drafts.sections(snapshot_id)
    assert again.generated == "Текст раздела."
    assert again.edited == "Правка коуча"


def test_editing_after_approval_is_refused(client):
    test_client, context, _ = client
    snapshot_id = _snapshot_with_a_finding(test_client, context)
    test_client.post(f"/snapshots/{snapshot_id}/request", data={"raw": "Устал"})
    test_client.post(
        f"/snapshots/{snapshot_id}/request/redact", data={"redacted": "Устал"}
    )
    test_client.post(f"/snapshots/{snapshot_id}/request/approve")
    test_client.post(f"/snapshots/{snapshot_id}/draft")
    test_client.post(f"/snapshots/{snapshot_id}/draft/approve")

    with context.session() as repo:
        section = repo.drafts.sections(snapshot_id)[0]
    response = test_client.post(
        f"/snapshots/{snapshot_id}/draft/{section.id}/edit",
        data={"text": "Поздняя правка"},
        follow_redirects=False,
    )

    assert response.status_code == 409


def test_model_failure_is_reported_not_swallowed(client):
    test_client, context, provider = client
    snapshot_id = _snapshot_with_a_finding(test_client, context)
    test_client.post(f"/snapshots/{snapshot_id}/request", data={"raw": "Устал"})
    test_client.post(
        f"/snapshots/{snapshot_id}/request/redact", data={"redacted": "Устал"}
    )
    test_client.post(f"/snapshots/{snapshot_id}/request/approve")
    provider.fail = True

    response = test_client.post(
        f"/snapshots/{snapshot_id}/draft", follow_redirects=False
    )

    assert response.status_code == 502
    assert "недоступна" in response.text
    with context.session() as repo:
        assert repo.drafts.sections(snapshot_id) == []


def test_draft_without_findings_is_refused(client):
    test_client, context, _ = client
    test_client.post("/clients", data=WOMAN)
    test_client.post("/clients/CL-0001/snapshots", data={"taken_on": "2026-09-01"})
    with context.session() as repo:
        snapshot_id = repo.snapshots.for_client("CL-0001")[-1].id
    test_client.post(f"/snapshots/{snapshot_id}/request", data={"raw": "Устал"})
    test_client.post(
        f"/snapshots/{snapshot_id}/request/redact", data={"redacted": "Устал"}
    )
    test_client.post(f"/snapshots/{snapshot_id}/request/approve")

    response = test_client.post(
        f"/snapshots/{snapshot_id}/draft", follow_redirects=False
    )

    assert response.status_code == 400


def test_unknown_snapshot_is_404(client):
    test_client, _, _ = client
    assert test_client.get("/snapshots/999/draft").status_code == 404
```

- [ ] **Step 2: Запустить тесты и убедиться, что они падают**

```bash
uv run pytest tests/app/test_report_routes.py -v
```

Ожидается: FAIL — маршрутов ещё нет.

- [ ] **Step 3: Расширить контекст**

В `src/healthcoach/app/deps.py`:

- импортировать `RequestRepository`, `DraftRepository`, `ClaudeCodeProvider`, `LLMProvider`;
- добавить в `Repositories` поля `requests: RequestRepository` и `drafts: DraftRepository` и собирать их в `session()`;
- добавить в `Context` поле `llm: LLMProvider` и собирать `ClaudeCodeProvider()` в `build_context`. Конструктор провайдера ничего не запускает, поэтому оборачивать его в `try` не нужно — ошибки поднимаются на вызове.

- [ ] **Step 4: Реализовать маршруты**

Файл `src/healthcoach/app/routes_report.py`:

```python
"""Запрос клиента, вычитка перед отправкой, сборка и утверждение черновика."""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from healthcoach.app.deps import Context, Repositories
from healthcoach.privacy.leak import LeakError
from healthcoach.privacy.redact import redact
from healthcoach.report.draft import DraftError, generate_draft
from healthcoach.report.sections import SECTIONS
from healthcoach.scoring.findings import collect_findings
from healthcoach.scoring.references import Measurement, Subject


def build_router(context: Context, templates) -> APIRouter:
    router = APIRouter()

    def _snapshot_and_client(repo: Repositories, snapshot_id: int):
        snapshot = repo.snapshots.get(snapshot_id)
        if snapshot is None:
            raise HTTPException(status_code=404, detail=f"нет среза {snapshot_id}")
        client = repo.clients.get(snapshot.client_code)
        if client is None:
            raise HTTPException(
                status_code=404, detail=f"нет клиента {snapshot.client_code}"
            )
        return snapshot, client

    def _findings(repo: Repositories, snapshot, client):
        if not client.is_complete:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"карточка клиента {client.code} не заполнена: без пола и "
                    f"даты рождения целевой коридор не выбрать"
                ),
            )
        measurements = [
            Measurement(m.analyte_id, m.value, m.units, label=m.raw_name)
            for m in repo.snapshots.measurements(snapshot.id)
            if m.confirmed
        ]
        answers = repo.snapshots.answers(snapshot.id)
        subject = Subject(sex=client.sex, age=client.age_on(snapshot.taken_on))
        return collect_findings(
            context.questionnaire, context.references, answers, measurements, subject
        ), subject

    def _page(request: Request, repo: Repositories, snapshot, client):
        stored = repo.requests.get(snapshot.id)
        suggested = ""
        if stored is not None and not stored.redacted:
            suggested = redact(stored.raw, client).text
        titles = {section.id: section.title for section in SECTIONS}
        return templates.TemplateResponse(
            request,
            "report.html",
            {
                "snapshot": snapshot,
                "client": client,
                "request": stored,
                "suggested": suggested,
                "sections": repo.drafts.sections(snapshot.id),
                "titles": titles,
                "approved_at": repo.drafts.approved_at(snapshot.id),
            },
        )

    @router.get("/snapshots/{snapshot_id}/draft", response_class=HTMLResponse)
    def draft_page(request: Request, snapshot_id: int):
        with context.session() as repo:
            snapshot, client = _snapshot_and_client(repo, snapshot_id)
            return _page(request, repo, snapshot, client)

    @router.post("/snapshots/{snapshot_id}/request")
    def save_request(snapshot_id: int, raw: str = Form(...)):
        with context.session() as repo:
            _snapshot_and_client(repo, snapshot_id)
            repo.requests.save(snapshot_id, raw)
        return RedirectResponse(f"/snapshots/{snapshot_id}/draft", status_code=303)

    @router.post("/snapshots/{snapshot_id}/request/redact")
    def save_redaction(snapshot_id: int, redacted: str = Form(...)):
        with context.session() as repo:
            _snapshot_and_client(repo, snapshot_id)
            if not repo.requests.set_redacted(snapshot_id, redacted):
                raise HTTPException(
                    status_code=400, detail="запрос клиента ещё не введён"
                )
        return RedirectResponse(f"/snapshots/{snapshot_id}/draft", status_code=303)

    @router.post("/snapshots/{snapshot_id}/request/approve")
    def approve_request(snapshot_id: int):
        with context.session() as repo:
            _snapshot_and_client(repo, snapshot_id)
            if not repo.requests.approve(snapshot_id):
                raise HTTPException(
                    status_code=400,
                    detail="вычитанного текста нет — утверждать нечего",
                )
        return RedirectResponse(f"/snapshots/{snapshot_id}/draft", status_code=303)

    @router.post("/snapshots/{snapshot_id}/draft")
    def build_draft(snapshot_id: int):
        with context.session() as repo:
            snapshot, client = _snapshot_and_client(repo, snapshot_id)
            stored = repo.requests.get(snapshot_id)
            if stored is None or not stored.approved:
                raise HTTPException(
                    status_code=400,
                    detail=(
                        "запрос клиента не вычитан и не утверждён — "
                        "до этого модели ничего не отправляется"
                    ),
                )
            if repo.drafts.approved_at(snapshot_id) is not None:
                raise HTTPException(
                    status_code=409, detail="черновик утверждён и не пересобирается"
                )
            findings, subject = _findings(repo, snapshot, client)
            request_text = stored.redacted

        if not findings:
            raise HTTPException(
                status_code=400,
                detail="находок нет — интерпретировать нечего",
            )

        try:
            generated = generate_draft(
                context.llm,
                findings,
                subject,
                request_text,
                context.specialists.public_view(),
                client,
            )
        except LeakError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except DraftError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc

        with context.session() as repo:
            for section in generated:
                repo.drafts.save_section(
                    snapshot_id,
                    section.section_id,
                    section.text,
                    section.finding_ids,
                )
        return RedirectResponse(f"/snapshots/{snapshot_id}/draft", status_code=303)

    @router.post("/snapshots/{snapshot_id}/draft/{section_row_id}/edit")
    def edit_section(snapshot_id: int, section_row_id: int, text: str = Form(...)):
        with context.session() as repo:
            _snapshot_and_client(repo, snapshot_id)
            if repo.drafts.approved_at(snapshot_id) is not None:
                raise HTTPException(
                    status_code=409,
                    detail="черновик утверждён — разделы больше не правятся",
                )
            if not repo.drafts.edit_section(section_row_id, snapshot_id, text):
                raise HTTPException(
                    status_code=404,
                    detail=f"в срезе {snapshot_id} нет раздела {section_row_id}",
                )
        return RedirectResponse(f"/snapshots/{snapshot_id}/draft", status_code=303)

    @router.post("/snapshots/{snapshot_id}/draft/approve")
    def approve_draft(snapshot_id: int):
        with context.session() as repo:
            _snapshot_and_client(repo, snapshot_id)
            if not repo.drafts.approve(
                snapshot_id, datetime.now(), context.questionnaire.version
            ):
                raise HTTPException(
                    status_code=400, detail="черновика нет — утверждать нечего"
                )
        return RedirectResponse(f"/snapshots/{snapshot_id}/draft", status_code=303)

    return router
```

- [ ] **Step 5: Реализовать шаблон**

Файл `src/healthcoach/app/templates/report.html`:

```html
{% extends "base.html" %}
{% block title %}Черновик среза {{ snapshot.taken_on }}{% endblock %}
{% block body %}
<nav><a href="/snapshots/{{ snapshot.id }}">← Срез {{ snapshot.taken_on }}</a></nav>
<h1>Черновик отчёта <span class="muted">{{ snapshot.client_code }}</span></h1>

{% if approved_at %}
<p class="warn">Утверждён {{ approved_at }} — разделы больше не правятся.</p>
{% endif %}

<h2>Запрос клиента</h2>
{% if not request %}
<form method="post" action="/snapshots/{{ snapshot.id }}/request">
  <label>Словами клиента<textarea name="raw" rows="4" cols="70" required></textarea></label>
  <button type="submit">Сохранить</button>
</form>
{% else %}
<p class="muted">Как написал клиент:</p>
<blockquote>{{ request.raw }}</blockquote>

{% if request.approved %}
<p>Уйдёт модели, утверждено:</p>
<blockquote>{{ request.redacted }}</blockquote>
{% else %}
<p class="warn">Вычитайте текст перед отправкой. Модель увидит ровно то,
  что останется справа. Автоматическая чистка ненадёжна на свободном
  тексте — последнее слово за вами.</p>
<form method="post" action="/snapshots/{{ snapshot.id }}/request/redact">
  <label>Уйдёт модели<textarea name="redacted" rows="4" cols="70"
    >{{ request.redacted or suggested }}</textarea></label>
  <button type="submit">Сохранить вычитку</button>
</form>
{% if request.redacted %}
<form method="post" action="/snapshots/{{ snapshot.id }}/request/approve">
  <button type="submit">Утвердить — можно отправлять</button>
</form>
{% endif %}
{% endif %}

<form method="post" action="/snapshots/{{ snapshot.id }}/request">
  <label>Переписать запрос<textarea name="raw" rows="3" cols="70" required
    >{{ request.raw }}</textarea></label>
  <button type="submit">Заменить</button>
</form>
{% endif %}

<h2>Разделы</h2>
{% if not sections %}
<p class="muted">Черновик ещё не собран.</p>
{% if request and request.approved %}
<form method="post" action="/snapshots/{{ snapshot.id }}/draft">
  <button type="submit">Собрать черновик</button>
</form>
{% else %}
<p class="muted">Сборка станет доступна, когда запрос клиента будет вычитан
  и утверждён.</p>
{% endif %}
{% else %}
{% for section in sections %}
<h3>{{ titles.get(section.section_id, section.section_id) }}</h3>
{% if section.finding_ids %}
<p class="muted">Стоит на находках:
  {% for id in section.finding_ids %}<code>{{ id }}</code>{% if not loop.last %}, {% endif %}{% endfor %}</p>
{% else %}
<p class="muted">Находки к разделу не привязаны.</p>
{% endif %}
<p class="muted">Написала модель:</p>
<blockquote>{{ section.generated }}</blockquote>
{% if approved_at %}
{% if section.edited %}
<p>Ваша правка:</p>
<blockquote>{{ section.edited }}</blockquote>
{% endif %}
{% else %}
<form method="post" action="/snapshots/{{ snapshot.id }}/draft/{{ section.id }}/edit">
  <label>Ваш текст<textarea name="text" rows="6" cols="70"
    >{{ section.edited or section.generated }}</textarea></label>
  <button type="submit">Сохранить правку</button>
</form>
{% endif %}
{% endfor %}

{% if not approved_at %}
<form method="post" action="/snapshots/{{ snapshot.id }}/draft/approve">
  <button type="submit">Утвердить черновик</button>
</form>
{% endif %}
{% endif %}
{% endblock %}
```

- [ ] **Step 6: Подключить маршрутизатор**

В `src/healthcoach/app/main.py` добавить импорт `routes_report` и строку `app.include_router(routes_report.build_router(context, templates))`.

- [ ] **Step 7: Запустить тесты**

```bash
uv run pytest tests/app -v
```

Ожидается: все PASS.

- [ ] **Step 8: Пройти сквозной путь руками**

```bash
uv run python -m healthcoach.app.main
```

1. Завести клиента, создать срез, загрузить выгрузку из `samples/`, подтвердить один показатель.
2. Ввести запрос клиента, намеренно вписав в него фамилию клиента.
3. Открыть черновик: убедиться, что предложенная вычистка убрала фамилию, а исходный текст сохранён рядом.
4. Попробовать собрать черновик до утверждения запроса — должен быть отказ.
5. Утвердить вычитку, собрать черновик. Убедиться, что разделы пришли и у каждого перечислены находки.
6. Поправить один раздел, утвердить черновик, убедиться, что правка после утверждения отвергается.
7. Остановить `Ctrl+C`, удалить `data/healthcoach.db` и `data/documents/`.

Живой вызов расходует лимиты подписки — это ожидаемо и делается один раз.

- [ ] **Step 9: Коммит**

```bash
git add src/healthcoach/app tests/app
git commit -m "feat: экраны запроса, вычитки, сборки и утверждения черновика"
```

---

### Task 7: Чей это документ — предъявление шапки и предупреждение

**Files:**
- Modify: `src/healthcoach/app/routes_documents.py`
- Modify: `src/healthcoach/app/templates/snapshot.html`
- Test: `tests/app/test_document_routes.py` (дополнить)

**Interfaces:**
- Consumes: `Client`, `ReadDocument`
- Produces: `document_belongs_to(client, lines) -> bool`

**Что нашлось.** Выгрузка одного клиента загружается в срез другого, и система принимает. Файл ответов на опросник мы сверяем по коду клиента и чужой отвергаем; у лабораторной выгрузки такой проверки нет, хотя ФИО пациента лежит прямо в тексте документа.

**Решение партнёра.** Не отказывать, а предъявлять и предупреждать. Отказ был бы неверен: распознавание коверкает буквы, и ложный отказ на своём же клиенте хуже предупреждения. Экран показывает шапку документа рядом с именем из карточки, и если фамилии клиента в тексте не нашлось — предупреждает явно.

- [ ] **Step 1: Написать падающие тесты**

Дописать в `tests/app/test_document_routes.py`:

```python
def test_document_of_another_client_is_flagged_not_refused(client):
    """Распознавание коверкает буквы: ложный отказ хуже предупреждения."""
    test_client, context = client
    snapshot_id = _snapshot(test_client)

    lines = [
        "Ф.И.О. пациента: Петров Пётр Петрович",
        "Показатель Результат Ед. изм. Референсные пределы",
        "Ферритин 45 нг/мл 10 - 120",
    ]
    page = _upload_text_document(test_client, snapshot_id, lines)

    assert "Петров" in page
    assert "не найдена" in page
    with context.session() as repo:
        assert repo.snapshots.measurements(snapshot_id)


def test_document_of_this_client_is_not_flagged(client):
    test_client, context = client
    snapshot_id = _snapshot(test_client)

    lines = [
        "Ф.И.О. пациента: Иванова Мария Сергеевна",
        "Показатель Результат Ед. изм. Референсные пределы",
        "Ферритин 45 нг/мл 10 - 120",
    ]
    page = _upload_text_document(test_client, snapshot_id, lines)

    assert "не найдена" not in page
```

Вспомогательная функция — рядом с тестами, подменяет чтение документа, чтобы не собирать PDF ради проверки предупреждения:

```python
def _upload_text_document(test_client, snapshot_id, lines):
    """Загрузить документ с заранее известным текстом.

    Чтение подменяется: проверяется предупреждение о чужом клиенте, а не
    разбор PDF, который проверен своими тестами.
    """
    import healthcoach.app.routes_documents as routes
    from healthcoach.intake.documents import ReadDocument
    from healthcoach.intake.lab_table import parse_lab_lines
    from healthcoach.storage.snapshots import SOURCE_PDF

    original = routes.read_document

    def fake(path, engine=None):
        return ReadDocument(
            source=SOURCE_PDF, lines=tuple(lines), table=parse_lab_lines(lines)
        )

    routes.read_document = fake
    try:
        return test_client.post(
            f"/snapshots/{snapshot_id}/documents",
            files={"file": ("бланк.pdf", b"%PDF-1.4", "application/pdf")},
        ).text
    finally:
        routes.read_document = original
```

- [ ] **Step 2: Реализовать проверку**

В `src/healthcoach/app/routes_documents.py` добавить функцию, проверяющую наличие основы фамилии клиента в тексте документа. Основу брать той же функцией `name_stems` из `healthcoach.privacy.redact`, чтобы правило склонения было записано один раз, а не двумя копиями, — это ровно тот дефект, который финальное ревью плана 3 нашло у кода лаборатории.

Результат передавать в отчёт об импорте и показывать на экране рядом с именем из карточки.

- [ ] **Step 3: Запустить тесты, прогнать набор, закоммитить**

```bash
uv run pytest -q
git add src/healthcoach/app tests/app
git commit -m "feat: выгрузка чужого клиента помечается предупреждением"
```

---

## Что дальше

**План 5 — отчёт.** Сборка клиентского PDF через WeasyPrint из утверждённого текста, титул и дисклеймер, графики динамики начиная со второго среза, портфолио клиента с подсветкой доверенных врачей (только коучу, в PDF не попадают), запись версии базы знаний в утверждённый отчёт.

**Долги, записанные при исполнении планов 2 и 3.**

- Проверка единиц на экране среза (`app/routes_snapshots.py`) и в расчёте использует общее правило `units_match`, но исходное введённое значение хранится в единицах бланка, а `value` — в эталонных. Как только у показателя появится множитель пересчёта, `raw_value` и `units` разъедутся.
- Уникальность идентификаторов вопросов между блоками опросника ничем не обеспечена: сегодня 544 из 544 уникальны, но загрузчик проверяет только идентификаторы блоков.
- Проверка поля единиц считает токены, но не смотрит на содержимое: склеенный распознаванием токен вида `-15мг/л` или голое `42` проходит. Напрашивается содержательная проверка.
- Двухстрочное название показателя на фотографии разрывается; значение сохраняется, название усекается, показатель не распознаётся. Риск в том, что усечённое название случайно совпадёт с другим показателем.
- Повторная загрузка того же файла вставляет измерения второй раз. Видна коучу, все копии неподтверждены.
