# План 6. CX: рабочий стол, шаги воронки, карточка, возврат к месту

> **Для агентов:** ОБЯЗАТЕЛЬНЫЙ ПОДНАВЫК: используйте superpowers:subagent-driven-development. Шаги помечены чекбоксами (`- [ ]`).

**Цель:** интерфейс организуется вокруг рабочего дня коуча, а не вокруг данных. Главный экран отвечает «у кого что происходит», срез показывает «на каком я шаге», карточка ставит работу выше паспорта, а действия не сбрасывают прокрутку.

**Архитектура.** Один новый модуль `app/status.py` считает состояние работы по клиенту и по срезу — плашки и шаги. Всё остальное — правки маршрутов и шаблонов. Утверждённые партнёром макеты лежат в `макеты/CX-1..4.pdf`; серые врезки в них — обоснования.

**Технологии:** существующие. Ни одной новой зависимости. Сворачивание — `<details>`, без JS.

## Решения партнёра

Взяты все четыре варианта макетов. Первый и второй связаны: плашка на рабочем столе ведёт к шагу, подсвеченному на срезе.

## Global Constraints

- Python 3.12, всё через `uv run`. Тесты пишут базы в `tmp_path`.
- **Данные клиентов не попадают в репозиторий никогда.**
- **Каждое обращение к базе — внутри `with context.session() as repo:`.**
- **Никаких молчаливых допущений**: статус не угадывается — если данных нет, плашка так и говорит.
- Существующие маршруты не меняют кодов ответов; правки редиректов меняют только якорь.
- Каждая задача заканчивается `uv run pytest` и коммитом.
- Набор на старте: **552 проходящих, 1 отложенный**.

## Файловая структура

| Файл | Ответственность |
|---|---|
| `src/healthcoach/app/status.py` | плашки клиента и шаги среза |
| `src/healthcoach/app/routes_clients.py` | рабочий стол, сортировка |
| `src/healthcoach/app/templates/clients.html` | рабочий стол |
| `src/healthcoach/app/templates/client.html` | карточка: работа выше паспорта |
| `src/healthcoach/app/templates/snapshot.html` | строка шагов, якоря |
| `src/healthcoach/app/routes_snapshots.py`, `routes_documents.py`, `routes_report.py` | якоря в редиректах |

---

### Task 1: Модуль статусов

**Files:**
- Create: `src/healthcoach/app/status.py`
- Test: `tests/app/test_status.py`

**Interfaces:**
- Consumes: `Repositories` (clients, snapshots, drafts, requests доступны из сессии), `Client`
- Produces:
  - `Badge(kind, text)` — kind из `"ok" | "warn" | "bad" | "muted"`
  - `Overview(latest_taken_on: date | None, badges: tuple[Badge, ...])`
  - `client_overview(repo, client) -> Overview`
  - `Step(title, state, detail, anchor)` — state из `"done" | "part" | "todo"`
  - `snapshot_steps(repo, snapshot_id) -> tuple[Step, ...]` — ровно пять шагов: Анкета, Показатели, Запрос, Черновик, PDF

**Правила плашек (по приоритету):** карточка не заполнена → одна `bad`-плашка и всё; срезов нет → `muted` «нет срезов»; иначе по последнему срезу (максимум `taken_on`, при равенстве — `id`): нет ни ответов, ни показателей → `muted` «ожидаем данные клиента»; есть несверенные → `warn` «не сверено: N»; черновик утверждён → `ok` «отчёт готов», иначе если разделы есть → `warn` «черновик ждёт утверждения». Пустой список плашек невозможен: если ничего не сработало — `muted` «в работе».

**Правила шагов:** Анкета — done «ответов: N» при N>0, иначе todo «не загружена», якорь `#анкета`. Показатели — done «сверено: N» когда N>0 и все сверены; part «сверено X из N» когда N>0; todo «нет», якорь `#показатели`. Запрос — done «утверждён»; part «вычитан, не утверждён» при непустой вычитке; part «не вычитан» при сыром тексте; todo «не введён»; якорь — страница черновика. Черновик — done «утверждён» / part «ждёт утверждения» при разделах / todo. PDF — done «скачать» только при утверждённом черновике, иначе todo «после утверждения».

- [ ] **Step 1: Тесты**

Файл `tests/app/test_status.py`:

```python
from datetime import date, datetime
from pathlib import Path

import pytest

from healthcoach.app.status import client_overview, snapshot_steps
from healthcoach.storage.clients import ClientRepository
from healthcoach.storage.db import open_database
from healthcoach.storage.drafts import DraftRepository
from healthcoach.storage.requests import RequestRepository
from healthcoach.storage.snapshots import SnapshotRepository


class Repos:
    def __init__(self, c):
        self.clients = ClientRepository(c)
        self.snapshots = SnapshotRepository(c)
        self.drafts = DraftRepository(c)
        self.requests = RequestRepository(c)


@pytest.fixture
def repo(tmp_path):
    c = open_database(tmp_path / "db.sqlite")
    yield Repos(c)
    c.close()


def _client(repo):
    return repo.clients.add("Соловьёва Ирина", "ж", date(1985, 3, 24))


def test_incomplete_card_is_the_only_badge(repo):
    client = _client(repo)
    import sqlite3
    repo.clients._connection.execute(
        "UPDATE identities SET sex='', birth_date='' WHERE code=?", (client.code,)
    )
    repo.clients._connection.commit()
    over = client_overview(repo, repo.clients.get(client.code))
    assert [b.kind for b in over.badges] == ["bad"]


def test_no_snapshots_says_so(repo):
    over = client_overview(repo, _client(repo))
    assert over.latest_taken_on is None
    assert [b.text for b in over.badges] == ["нет срезов"]


def test_unverified_measurements_are_counted(repo):
    client = _client(repo)
    s = repo.snapshots.create(client.code, date(2026, 9, 1))
    a = repo.snapshots.add_measurement(s.id, "ферритин", "Ферритин", 18.0, "18", "нг/мл", date(2026, 8, 20))
    repo.snapshots.add_measurement(s.id, "", "Калий", 4.2, "4.2", "ммоль/л", date(2026, 8, 20))
    repo.snapshots.confirm_measurement(a.id, s.id)
    over = client_overview(repo, client)
    assert over.latest_taken_on == date(2026, 9, 1)
    assert any(b.text == "не сверено: 1" and b.kind == "warn" for b in over.badges)


def test_badges_come_from_the_latest_snapshot_only(repo):
    client = _client(repo)
    old = repo.snapshots.create(client.code, date(2026, 3, 1))
    repo.snapshots.add_measurement(old.id, "ферритин", "Ферритин", 18.0, "18", "нг/мл", date(2026, 2, 20))
    fresh = repo.snapshots.create(client.code, date(2026, 9, 1))
    repo.drafts.save_section(fresh.id, "запрос", "Текст", ())
    repo.drafts.approve(fresh.id, datetime(2026, 9, 2))
    over = client_overview(repo, client)
    assert [b.text for b in over.badges] == ["отчёт готов"]


def test_draft_waiting_for_approval(repo):
    client = _client(repo)
    s = repo.snapshots.create(client.code, date(2026, 9, 1))
    repo.drafts.save_section(s.id, "запрос", "Текст", ())
    over = client_overview(repo, client)
    assert any(b.text == "черновик ждёт утверждения" for b in over.badges)


def test_empty_snapshot_awaits_client_data(repo):
    client = _client(repo)
    repo.snapshots.create(client.code, date(2026, 9, 1))
    over = client_overview(repo, client)
    assert [b.text for b in over.badges] == ["ожидаем данные клиента"]


def test_steps_are_always_five_in_order(repo):
    client = _client(repo)
    s = repo.snapshots.create(client.code, date(2026, 9, 1))
    steps = snapshot_steps(repo, s.id)
    assert [st.title for st in steps] == ["Анкета", "Показатели", "Запрос", "Черновик", "PDF"]
    assert all(st.state == "todo" for st in steps)


def test_partially_verified_measurements_are_a_part_step(repo):
    client = _client(repo)
    s = repo.snapshots.create(client.code, date(2026, 9, 1))
    a = repo.snapshots.add_measurement(s.id, "ферритин", "Ферритин", 18.0, "18", "нг/мл", date(2026, 8, 20))
    repo.snapshots.add_measurement(s.id, "", "Калий", 4.2, "4.2", "ммоль/л", date(2026, 8, 20))
    repo.snapshots.confirm_measurement(a.id, s.id)
    step = snapshot_steps(repo, s.id)[1]
    assert step.state == "part"
    assert step.detail == "сверено 1 из 2"
    assert step.anchor == "#показатели"


def test_pdf_step_is_done_only_after_approval(repo):
    client = _client(repo)
    s = repo.snapshots.create(client.code, date(2026, 9, 1))
    repo.drafts.save_section(s.id, "запрос", "Текст", ())
    assert snapshot_steps(repo, s.id)[4].state == "todo"
    repo.drafts.approve(s.id, datetime(2026, 9, 2))
    steps = snapshot_steps(repo, s.id)
    assert steps[3].state == "done"
    assert steps[4].state == "done"


def test_request_states(repo):
    client = _client(repo)
    s = repo.snapshots.create(client.code, date(2026, 9, 1))
    repo.requests.save(s.id, "Устал")
    assert snapshot_steps(repo, s.id)[2].detail == "не вычитан"
    repo.requests.set_redacted(s.id, "Устал")
    assert snapshot_steps(repo, s.id)[2].detail == "вычитан, не утверждён"
    repo.requests.approve(s.id)
    assert snapshot_steps(repo, s.id)[2].state == "done"
```

- [ ] **Step 2: Убедиться, что падают** (`uv run pytest tests/app/test_status.py -q` → ошибка импорта)

- [ ] **Step 3: Реализация**

Файл `src/healthcoach/app/status.py`:

```python
"""Состояние работы: плашки по клиенту и шаги по срезу.

Правила собраны в одном месте, потому что их читают два экрана:
рабочий стол ведёт ровно к тому шагу, который подсвечен на срезе.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from healthcoach.storage.clients import Client


@dataclass(frozen=True)
class Badge:
    kind: str
    text: str


@dataclass(frozen=True)
class Overview:
    latest_taken_on: date | None
    badges: tuple[Badge, ...]


@dataclass(frozen=True)
class Step:
    title: str
    state: str
    detail: str
    anchor: str


def client_overview(repo, client: Client) -> Overview:
    """Плашки клиента — по последнему срезу."""
    if not client.is_complete:
        return Overview(None, (Badge("bad", "карточка не заполнена"),))
    snapshots = repo.snapshots.for_client(client.code)
    if not snapshots:
        return Overview(None, (Badge("muted", "нет срезов"),))
    latest = max(snapshots, key=lambda s: (s.taken_on, s.id))
    return Overview(latest.taken_on, _snapshot_badges(repo, latest.id))


def _snapshot_badges(repo, snapshot_id: int) -> tuple[Badge, ...]:
    badges: list[Badge] = []
    measurements = repo.snapshots.measurements(snapshot_id)
    answers = repo.snapshots.answers(snapshot_id)
    unverified = sum(1 for m in measurements if not m.confirmed)
    if unverified:
        badges.append(Badge("warn", f"не сверено: {unverified}"))
    if repo.drafts.approved_at(snapshot_id) is not None:
        badges.append(Badge("ok", "отчёт готов"))
    elif repo.drafts.sections(snapshot_id):
        badges.append(Badge("warn", "черновик ждёт утверждения"))
    if badges:
        return tuple(badges)
    # Ничего не сработало: пустой срез ждёт данных, непустой просто в работе.
    if not measurements and not answers:
        return (Badge("muted", "ожидаем данные клиента"),)
    return (Badge("muted", "в работе"),)


def snapshot_steps(repo, snapshot_id: int) -> tuple[Step, ...]:
    """Пять шагов воронки среза, всегда в одном порядке."""
    answers = repo.snapshots.answers(snapshot_id)
    measurements = repo.snapshots.measurements(snapshot_id)
    confirmed = sum(1 for m in measurements if m.confirmed)
    request = repo.requests.get(snapshot_id)
    sections = repo.drafts.sections(snapshot_id)
    approved = repo.drafts.approved_at(snapshot_id) is not None
    draft_page = f"/snapshots/{snapshot_id}/draft"

    if answers:
        questionnaire = Step("Анкета", "done", f"ответов: {len(answers)}", "#анкета")
    else:
        questionnaire = Step("Анкета", "todo", "не загружена", "#анкета")

    total = len(measurements)
    if total and confirmed == total:
        indicators = Step("Показатели", "done", f"сверено: {total}", "#показатели")
    elif total:
        indicators = Step(
            "Показатели", "part", f"сверено {confirmed} из {total}", "#показатели"
        )
    else:
        indicators = Step("Показатели", "todo", "нет", "#показатели")

    if request is None:
        req = Step("Запрос", "todo", "не введён", draft_page)
    elif request.approved:
        req = Step("Запрос", "done", "утверждён", draft_page)
    elif request.redacted:
        req = Step("Запрос", "part", "вычитан, не утверждён", draft_page)
    else:
        req = Step("Запрос", "part", "не вычитан", draft_page)

    if approved:
        draft = Step("Черновик", "done", "утверждён", draft_page)
        pdf = Step("PDF", "done", "скачать", f"/snapshots/{snapshot_id}/report.pdf")
    elif sections:
        draft = Step("Черновик", "part", "ждёт утверждения", draft_page)
        pdf = Step("PDF", "todo", "после утверждения", draft_page)
    else:
        draft = Step("Черновик", "todo", "не собран", draft_page)
        pdf = Step("PDF", "todo", "после утверждения", draft_page)

    return (questionnaire, indicators, req, draft, pdf)
```

- [ ] **Step 4: Прогнать, закоммитить** (`uv run pytest -q` → 562; `git commit -m "feat: модуль состояния работы — плашки клиента и шаги среза"`, стажить только свои пути)

---

### Task 2: Рабочий стол

**Files:**
- Modify: `src/healthcoach/app/routes_clients.py` — маршрут `/` собирает обзоры и сортирует
- Modify: `src/healthcoach/app/templates/clients.html`
- Test: `tests/app/test_clients_routes.py` (дополнить)

**Interfaces:** Consumes `client_overview`. Маршрут `/` передаёт в шаблон список пар `(client, overview)`, отсортированный по `latest_taken_on` убыванием, клиенты без срезов — в конце (сортировочный ключ `(latest is None, -ordinal)` или эквивалент).

**Шаблон по макету CX-1:** заголовок «Клиенты», справа `<details><summary>＋ Новый клиент</summary>` с существующей формой внутри. Таблица: Клиент (ссылка на карточку по имени, а не по коду) · Последний срез · Состояние работы. Плашки — `<span class="tag {{ badge.kind }}">`. CSS классов `tag/ok/warn/bad/muted-tag` добавить в `base.html` по цветам макета. Колонки пола и даты рождения из таблицы убрать — их место на карточке.

**Тесты (дополнить существующий файл, помощники там уже есть):** плашка «не сверено: N» видна на `/` после добавления неподтверждённого измерения; клиент с последним срезом раньше — ниже клиента с более поздним; клиент без срезов — последним и с «нет срезов»; форма добавления присутствует внутри `<details>`; существующий тест добавления клиента через `/clients` продолжает проходить без правок.

- [ ] Тесты → RED → реализация → GREEN → полный набор → коммит `feat: рабочий стол — состояние работы по клиентам вместо анкеты`

---

### Task 3: Шаги воронки на срезе

**Files:**
- Modify: `src/healthcoach/app/routes_snapshots.py` — `render_snapshot_page` передаёт `steps`
- Modify: `src/healthcoach/app/templates/snapshot.html`
- Test: `tests/app/test_snapshot_routes.py` (дополнить)

**Шаблон по макету CX-2:** сразу под `<h1>` — полоса из пяти шагов, каждый — ссылка на свой якорь или страницу. Классы `step done/part/todo`, CSS в `base.html` по макету. Заголовкам разделов дать id: `<h2 id="анкета">`, `<h2 id="документы">`, `<h2 id="показатели">`, `<h2 id="находки">`, `<h2 id="отчёт">`.

**Тесты:** на срезе с частично сверенными показателями страница содержит «сверено 1 из 2» и ссылку `#показатели`; после утверждения черновика шаг PDF ведёт на `report.pdf`; на пустом срезе все пять шагов видны.

- [ ] Тесты → RED → реализация → GREEN → полный набор → коммит `feat: строка шагов воронки на экране среза`

---

### Task 4: Карточка и возврат к месту действия

**Files:**
- Modify: `src/healthcoach/app/templates/client.html`
- Modify: `src/healthcoach/app/routes_snapshots.py`, `routes_documents.py`, `routes_report.py` — якоря в редиректах
- Test: `tests/app/test_clients_routes.py`, `tests/app/test_snapshot_routes.py`, `tests/app/test_document_routes.py`, `tests/app/test_report_routes.py` (дополнить)

**Карточка по макету CX-3:** порядок — `<h1>`, срезы (с плашками из `_snapshot_badges`? нет — по срезу клиента плашки не нужны, достаточно существующего списка, поднятого наверх, плюс кнопка «＋ Новый срез»), опросник, затем `<details {% if not client.is_complete %}open{% endif %}><summary>Паспортные данные и контакты</summary>` с формой правки внутри. Предупреждение о незаполненной карточке остаётся снаружи `<details>`.

**Якоря по макету CX-4** — только адрес редиректа, код ответа не меняется:
- `routes_snapshots.py`: добавление показателя и подтверждение → `/snapshots/{id}#показатели`
- `routes_documents.py`: загрузка документа → `#документы`; вписывание значения → `#показатели`
- `routes_report.py`: правка раздела → `/snapshots/{id}/draft#s{section_row_id}`; разделам на странице черновика дать `id="s{{ section.id }}"`

**Тесты:** `location` редиректа подтверждения оканчивается на `#показатели`; загрузки документа — на `#документы`; правки раздела — на `#s{id}`; на карточке `<details>` без `open` при заполненной карточке и с `open` при незаполненной; блок срезов в HTML стоит раньше формы паспортных данных (сравнить индексы вхождений).

- [ ] Тесты → RED → реализация → GREEN → полный набор → коммит `feat: карточка ставит работу выше паспорта, действия возвращают к месту`

---

## Что дальше

Долги прежних планов — в «Что дальше» планов 4 и 5. Модель не знает о графике рядом с её текстом (план 5). Наполнение `knowledge/references/` остаётся главным ограничением качества отчётов.
