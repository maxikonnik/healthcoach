# План 5. Клиентский PDF и графики динамики

> **Для агентов:** ОБЯЗАТЕЛЬНЫЙ ПОДНАВЫК: используйте superpowers:subagent-driven-development (рекомендуется) или superpowers:executing-plans, чтобы выполнять этот план задача за задачей. Шаги помечены чекбоксами (`- [ ]`).

**Цель:** утверждённый коучем черновик превращается в PDF на 5–10 страниц, который можно отдать клиенту. Со второго среза в отчёте появляются графики динамики показателей.

**Архитектура.** Четыре слоя. Первый собирает всё, что нужно отчёту, в один неизменяемый объект: клиент, срез, утверждённые разделы, показатели с коридорами, история по каждому показателю. Второй рисует графики динамики в SVG — своим кодом, без новых зависимостей. Третий раскладывает это в HTML по шаблону и печатает WeasyPrint. Четвёртый отдаёт файл коучу.

**Технологии:** Python 3.12, WeasyPrint поверх системного pango, SVG своим кодом, существующие `healthcoach.storage`, `healthcoach.scoring`, `healthcoach.app`.

## Что установлено до написания плана

Проверено руками на этой машине, не предполагается:

- **WeasyPrint работает** после `brew install pango`: 4 страницы A4 из тестового документа, разрывы страниц по `break-before: page`, нумерация через `@bottom-center`, кириллица извлекается обратно без потерь.
- **Без переменной окружения он не запускается**: `OSError: cannot load library 'libgobject-2.0-0'`. Установка `os.environ["DYLD_FALLBACK_LIBRARY_PATH"]` **до импорта** `weasyprint` решает это внутри процесса — проверено. Коуч не должен настраивать окружение руками.
- **Родной путь macOS не годится**: `WKWebView.createPDFWithConfiguration` отдаёт одну страницу высотой в 16 листов A4 — длинный снимок экрана, а не документ. Печатный конвейер `NSPrintOperation` в фоновом процессе зависает.
- `SnapshotRepository.history(client_code, analyte_id)` уже отдаёт все измерения показателя по клиенту, отсортированные **по дате забора** — это ровно то, что нужно графику.
- Восемь разделов черновика (`SECTIONS`) — это пункты 2–9 структуры отчёта из спецификации. Титул и дисклеймер собирает шаблон: там нечего трактовать.
- Имени специалиста в системе нет нигде. Титулу его взять неоткуда — задача 1 добавляет.

## Решения партнёра

1. **PDF собирает WeasyPrint**, системные зависимости поставлены. Вёрстка правится как обычная веб-страница и независимо от логики — так спецификация и задумывала.
2. **Графики рисуются своим кодом в SVG.** График простой: точки по датам забора, линия, полоса целевого коридора. Сто строк кода вместо тяжёлой зависимости, и полный контроль над тем, что видит клиент.

## Global Constraints

- Python 3.12, всё через `uv run`. Никаких голых `python` и `pip`.
- **Данные клиентов не попадают в репозиторий никогда.** `.gitignore` закрывает `data/`, `clients/`, `*.db`, `samples/`. Тесты пишут в `tmp_path`.
- **Реестр «код клиента ↔ ФИО» доступен только через `ClientRepository`.** Стражи параметризованы по всем модулям `storage/`.
- **Врачебные контакты не покидают базу коуча.** В клиентский PDF не попадают ни имена врачей, ни их контакты — только специальности.
- **Ссылок на источники в клиентском PDF нет.** Обоснование остаётся в рабочем черновике коуча.
- **PDF собирается только из утверждённого черновика.** Неутверждённый — отказ, а не «черновой вариант».
- **Числовая основа считается кодом.** Отчёт печатает то, что посчитано, и ничего не пересчитывает.
- Каждая задача заканчивается запуском `uv run pytest` и коммитом.
- Набор тестов на старте: **474 проходящих**.

## Файловая структура

| Файл | Ответственность |
|---|---|
| `knowledge/coach.yaml` | имя и подпись специалиста для титула |
| `src/healthcoach/knowledge/coach.py` | чтение профиля коуча |
| `src/healthcoach/report/data.py` | сборка всего, что нужно отчёту, в один объект |
| `src/healthcoach/report/charts.py` | графики динамики в SVG |
| `src/healthcoach/report/pdf.py` | HTML в PDF через WeasyPrint |
| `src/healthcoach/app/templates/report_pdf.html` | вёрстка клиентского отчёта |
| `src/healthcoach/app/routes_report.py` | выдача PDF коучу |

---

### Task 1: Профиль коуча и данные отчёта

**Files:**
- Create: `knowledge/coach.yaml`
- Create: `src/healthcoach/knowledge/coach.py`
- Create: `src/healthcoach/report/data.py`
- Modify: `src/healthcoach/app/deps.py` — профиль в контекст
- Test: `tests/knowledge/test_coach.py`
- Test: `tests/report/test_data.py`

**Interfaces:**
- Consumes: `Client`, `Snapshot`, `StoredMeasurement`, `DraftRepository`, `SnapshotRepository`, `ClientRepository`, `References`, `Finding`
- Produces:
  - `Coach(name, title, signature)` и `load_coach(path) -> Coach`, `CoachError`
  - `Point(taken_on: date, value: float)`
  - `Series(analyte_id, title, units, points: tuple[Point, ...], target: Interval | None)` со свойством `has_dynamics` — точек больше одной
  - `ReportData(client_name, client_code, taken_on, coach, sections, findings, series, approved_at)`
  - `collect_report(repo, questionnaire, references, coach, snapshot_id) -> ReportData`
  - `ReportError`

**Почему сборка данных отдельно от вёрстки.** Шаблон не должен ходить в базу: он получает готовый объект и только раскладывает его. Так вёрстку можно править, не боясь сломать выборку, а выборку проверить тестом без единой строки HTML.

**Почему `has_dynamics`, а не подсчёт в шаблоне.** Спецификация говорит: динамика появляется начиная со второго среза. Одна точка — не динамика, а первое измерение; рисовать по ней график значит показать клиенту линию, которой нет. Правило записано один раз в данных.

**Почему отчёт собирается только по утверждённому черновику.** Неутверждённый черновик — это то, что написала модель и коуч ещё не проверил. Выдать его клиенту нельзя ни при каких обстоятельствах, и отличать «утверждён» от «не утверждён» должен код, а не внимательность коуча.

- [ ] **Step 1: Написать падающие тесты профиля коуча**

Файл `tests/knowledge/test_coach.py`:

```python
import pytest

from healthcoach.knowledge.coach import CoachError, load_coach


def _write(tmp_path, text: str):
    path = tmp_path / "coach.yaml"
    path.write_text(text, encoding="utf-8")
    return path


def test_profile_is_read(tmp_path):
    path = _write(
        tmp_path,
        "имя: Иконникова Екатерина\nдолжность: нутрициолог\nподпись: С уважением\n",
    )
    coach = load_coach(path)
    assert coach.name == "Иконникова Екатерина"
    assert coach.title == "нутрициолог"
    assert coach.signature == "С уважением"


def test_name_is_required(tmp_path):
    path = _write(tmp_path, "должность: нутрициолог\n")
    with pytest.raises(CoachError, match="имя"):
        load_coach(path)


def test_blank_name_is_refused(tmp_path):
    """Титул с пустым именем специалиста — брак, а не мелочь."""
    path = _write(tmp_path, "имя: '   '\n")
    with pytest.raises(CoachError, match="имя"):
        load_coach(path)


def test_optional_fields_default_to_empty(tmp_path):
    coach = load_coach(_write(tmp_path, "имя: Иконникова Екатерина\n"))
    assert coach.title == ""
    assert coach.signature == ""


def test_missing_file_is_refused(tmp_path):
    with pytest.raises(CoachError, match="не найден"):
        load_coach(tmp_path / "нет.yaml")
```

- [ ] **Step 2: Написать падающие тесты сборки данных**

Файл `tests/report/test_data.py`:

```python
from datetime import date, datetime
from pathlib import Path

import pytest

from healthcoach.knowledge.coach import Coach
from healthcoach.knowledge.questionnaire import load_questionnaire
from healthcoach.knowledge.references import load_references
from healthcoach.report.data import ReportError, collect_report
from healthcoach.storage.clients import ClientRepository
from healthcoach.storage.db import open_database
from healthcoach.storage.drafts import DraftRepository
from healthcoach.storage.snapshots import SnapshotRepository

REFS = Path(__file__).parents[2] / "knowledge" / "references"
SPEC = Path(__file__).parents[2] / "knowledge" / "questionnaire.yaml"
COACH = Coach(name="Иконникова Екатерина", title="нутрициолог", signature="")


@pytest.fixture(scope="module")
def knowledge():
    return load_questionnaire(SPEC), load_references(REFS)


def _collect(repo, knowledge, snapshot_id):
    questionnaire, references = knowledge
    return collect_report(repo, questionnaire, references, COACH, snapshot_id)


class Repos:
    """Три хранилища на одном соединении — как их выдаёт Context.session()."""

    def __init__(self, connection):
        self.clients = ClientRepository(connection)
        self.snapshots = SnapshotRepository(connection)
        self.drafts = DraftRepository(connection)


@pytest.fixture
def repo(tmp_path):
    connection = open_database(tmp_path / "db.sqlite")
    yield Repos(connection)
    connection.close()


def _client_with_snapshot(repo, taken_on=date(2026, 9, 1)):
    client = repo.clients.add("Соловьёва Ирина", "ж", date(1985, 3, 24))
    snapshot = repo.snapshots.create(client.code, taken_on)
    return client, snapshot


def _approved_draft(repo, snapshot_id):
    repo.drafts.save_section(snapshot_id, "запрос", "Текст запроса.", ())
    repo.drafts.save_section(snapshot_id, "показатели", "Текст показателей.", ())
    repo.drafts.approve(snapshot_id, datetime(2026, 9, 2, 10, 0))


def test_report_carries_the_client_and_the_coach(repo, knowledge):
    _, snapshot = _client_with_snapshot(repo)
    _approved_draft(repo, snapshot.id)

    data = _collect(repo, knowledge, snapshot.id)

    assert data.client_name == "Соловьёва Ирина"
    assert data.client_code == "CL-0001"
    assert data.taken_on == date(2026, 9, 1)
    assert data.coach.name == "Иконникова Екатерина"
    assert data.approved_at == datetime(2026, 9, 2, 10, 0)


def test_sections_come_in_the_order_of_the_report(repo, knowledge):
    _, snapshot = _client_with_snapshot(repo)
    _approved_draft(repo, snapshot.id)

    data = _collect(repo, knowledge, snapshot.id)

    assert [s.section_id for s in data.sections] == ["запрос", "показатели"]


def test_section_takes_the_coach_edit_over_the_model_text(repo, knowledge):
    """В отчёт идёт то, что оставил коуч, а не то, что написала модель."""
    _, snapshot = _client_with_snapshot(repo)
    saved = repo.drafts.save_section(snapshot.id, "запрос", "Текст модели.", ())
    repo.drafts.edit_section(saved.id, snapshot.id, "Правка коуча.")
    repo.drafts.approve(snapshot.id, datetime(2026, 9, 2))

    data = _collect(repo, knowledge, snapshot.id)

    assert data.sections[0].text == "Правка коуча."


def test_unapproved_draft_is_refused(repo, knowledge):
    """Неутверждённый черновик клиенту не отдаётся ни при каких условиях."""
    _, snapshot = _client_with_snapshot(repo)
    repo.drafts.save_section(snapshot.id, "запрос", "Текст.", ())

    with pytest.raises(ReportError, match="не утверждён"):
        _collect(repo, knowledge, snapshot.id)


def test_missing_draft_is_refused(repo, knowledge):
    _, snapshot = _client_with_snapshot(repo)
    with pytest.raises(ReportError, match="не утверждён"):
        _collect(repo, knowledge, snapshot.id)


def test_unknown_snapshot_is_refused(repo, knowledge):
    with pytest.raises(ReportError, match="нет среза"):
        _collect(repo, knowledge, 99999)


def test_only_confirmed_measurements_reach_the_report(repo, knowledge):
    """Ворота сверки держатся и здесь: клиент видит только сверенное."""
    client, snapshot = _client_with_snapshot(repo)
    confirmed = repo.snapshots.add_measurement(
        snapshot.id, "ферритин", "Ферритин", 18.0, "18", "нг/мл", date(2026, 8, 20)
    )
    repo.snapshots.add_measurement(
        snapshot.id, "ферритин", "Ферритин", 999.0, "999", "нг/мл", date(2026, 8, 21)
    )
    repo.snapshots.confirm_measurement(confirmed.id, snapshot.id)
    _approved_draft(repo, snapshot.id)

    data = _collect(repo, knowledge, snapshot.id)

    values = [f.value for f in data.findings]
    assert 18.0 in values
    assert 999.0 not in values


def test_a_single_measurement_is_not_dynamics(repo, knowledge):
    """Одна точка — первое измерение, а не динамика: линии здесь нет."""
    client, snapshot = _client_with_snapshot(repo)
    stored = repo.snapshots.add_measurement(
        snapshot.id, "ферритин", "Ферритин", 18.0, "18", "нг/мл", date(2026, 8, 20)
    )
    repo.snapshots.confirm_measurement(stored.id, snapshot.id)
    _approved_draft(repo, snapshot.id)

    data = _collect(repo, knowledge, snapshot.id)

    (series,) = data.series
    assert len(series.points) == 1
    assert series.has_dynamics is False


def test_two_snapshots_give_dynamics_sorted_by_sampling_date(repo, knowledge):
    client, first = _client_with_snapshot(repo, date(2026, 6, 1))
    second = repo.snapshots.create(client.code, date(2026, 9, 1))

    later = repo.snapshots.add_measurement(
        second.id, "ферритин", "Ферритин", 45.0, "45", "нг/мл", date(2026, 8, 25)
    )
    earlier = repo.snapshots.add_measurement(
        first.id, "ферритин", "Ферритин", 18.0, "18", "нг/мл", date(2026, 5, 20)
    )
    repo.snapshots.confirm_measurement(later.id, second.id)
    repo.snapshots.confirm_measurement(earlier.id, first.id)
    _approved_draft(repo, second.id)

    data = collect_report(repo, load_references(REFS), COACH, second.id)

    (series,) = data.series
    assert series.has_dynamics is True
    assert [p.value for p in series.points] == [18.0, 45.0]
    assert [p.taken_on for p in series.points] == [date(2026, 5, 20), date(2026, 8, 25)]


def test_unconfirmed_history_does_not_reach_the_chart(repo, knowledge):
    """График строится по сверенному, иначе клиент увидит непроверенную точку."""
    client, first = _client_with_snapshot(repo, date(2026, 6, 1))
    second = repo.snapshots.create(client.code, date(2026, 9, 1))
    repo.snapshots.add_measurement(
        first.id, "ферритин", "Ферритин", 5.0, "5", "нг/мл", date(2026, 5, 20)
    )
    stored = repo.snapshots.add_measurement(
        second.id, "ферритин", "Ферритин", 45.0, "45", "нг/мл", date(2026, 8, 25)
    )
    repo.snapshots.confirm_measurement(stored.id, second.id)
    _approved_draft(repo, second.id)

    data = collect_report(repo, load_references(REFS), COACH, second.id)

    (series,) = data.series
    assert [p.value for p in series.points] == [45.0]
    assert series.has_dynamics is False


def test_unrecognised_measurement_has_no_series(repo, knowledge):
    """У показателя без идентификатора нечего откладывать по оси."""
    client, snapshot = _client_with_snapshot(repo)
    stored = repo.snapshots.add_measurement(
        snapshot.id, "", "Гомоцистеин", 12.0, "12", "мкмоль/л", date(2026, 8, 20)
    )
    repo.snapshots.confirm_measurement(stored.id, snapshot.id)
    _approved_draft(repo, snapshot.id)

    data = _collect(repo, knowledge, snapshot.id)

    assert data.series == ()
```

- [ ] **Step 3: Запустить тесты и убедиться, что они падают**

```bash
uv run pytest tests/knowledge/test_coach.py tests/report/test_data.py -q
```

Ожидается: ошибки импорта `healthcoach.knowledge.coach` и `healthcoach.report.data`.

- [ ] **Step 4: Создать профиль коуча**

Файл `knowledge/coach.yaml`:

```yaml
# Кто подписывает отчёт. Попадает на титульный лист клиентского PDF.
имя: Иконникова Екатерина
должность: специалист по здоровью
подпись: ''
```

Файл `src/healthcoach/knowledge/coach.py`:

```python
"""Кто подписывает отчёт.

Отдельный файл, а не поле в настройках: имя специалиста печатается на
титуле клиентского PDF и меняется вместе с базой знаний, под контролем
версий.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml


class CoachError(Exception):
    """Профиль специалиста непригоден."""


@dataclass(frozen=True)
class Coach:
    name: str
    title: str
    signature: str


def load_coach(path: Path) -> Coach:
    """Прочитать профиль специалиста."""
    if not path.is_file():
        raise CoachError(f"{path}: файл профиля специалиста не найден")

    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    name = str(raw.get("имя", "")).strip()
    if not name:
        raise CoachError(f"{path}: не указано имя специалиста — титул подписать нечем")

    return Coach(
        name=name,
        title=str(raw.get("должность", "") or "").strip(),
        signature=str(raw.get("подпись", "") or "").strip(),
    )
```

- [ ] **Step 5: Реализовать сборку данных**

Файл `src/healthcoach/report/data.py`:

```python
"""Всё, что нужно клиентскому отчёту, в одном объекте.

Шаблон не ходит в базу: он получает готовое и только раскладывает. Так
вёрстку можно править, не боясь сломать выборку, а выборку проверить
тестом без единой строки HTML.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime

from healthcoach.knowledge.coach import Coach
from healthcoach.knowledge.references import Interval, References
from healthcoach.knowledge.questionnaire import Questionnaire
from healthcoach.scoring.findings import Finding, collect_findings
from healthcoach.scoring.references import Measurement, Subject, select_target
from healthcoach.storage.drafts import DraftSection


class ReportError(Exception):
    """Отчёт собрать нельзя."""


@dataclass(frozen=True)
class Point:
    taken_on: date
    value: float


@dataclass(frozen=True)
class Series:
    analyte_id: str
    title: str
    units: str
    points: tuple[Point, ...]
    target: Interval | None

    @property
    def has_dynamics(self) -> bool:
        """Динамика начинается со второго измерения.

        Одна точка — это первое измерение, а не динамика. Рисовать по ней
        график значит показать клиенту линию, которой нет.
        """
        return len(self.points) > 1


@dataclass(frozen=True)
class ReportData:
    client_name: str
    client_code: str
    taken_on: date
    coach: Coach
    sections: tuple[DraftSection, ...]
    findings: tuple[Finding, ...]
    series: tuple[Series, ...]
    approved_at: datetime


def collect_report(
    repo,
    questionnaire: Questionnaire,
    references: References,
    coach: Coach,
    snapshot_id: int,
) -> ReportData:
    """Собрать данные отчёта по утверждённому черновику среза."""
    snapshot = repo.snapshots.get(snapshot_id)
    if snapshot is None:
        raise ReportError(f"нет среза {snapshot_id}")

    approved_at = repo.drafts.approved_at(snapshot_id)
    if approved_at is None:
        raise ReportError(
            f"черновик среза {snapshot_id} не утверждён — клиенту его отдавать нельзя"
        )

    client = repo.clients.get(snapshot.client_code)
    if client is None:
        raise ReportError(f"нет клиента {snapshot.client_code}")
    if not client.is_complete:
        raise ReportError(
            f"карточка клиента {client.code} не заполнена: без пола и даты "
            f"рождения целевой коридор не выбрать"
        )

    confirmed = [m for m in repo.snapshots.measurements(snapshot_id) if m.confirmed]
    subject = Subject(sex=client.sex, age=client.age_on(snapshot.taken_on))
    findings = collect_findings(
        questionnaire,
        references,
        repo.snapshots.answers(snapshot_id),
        [
            Measurement(m.analyte_id, m.value, m.units, label=m.raw_name, row_id=m.id)
            for m in confirmed
        ],
        subject,
    )

    return ReportData(
        client_name=client.full_name,
        client_code=client.code,
        taken_on=snapshot.taken_on,
        coach=coach,
        sections=tuple(repo.drafts.sections(snapshot_id)),
        findings=tuple(findings),
        series=_series(repo, references, subject, client.code, confirmed),
        approved_at=approved_at,
    )


def _series(repo, references, subject, client_code, confirmed) -> tuple[Series, ...]:
    """Ряды динамики по показателям этого среза.

    В ряд идут только сверенные измерения: клиент не должен увидеть точку,
    которую коуч не проверил.
    """
    result: list[Series] = []
    for analyte_id in dict.fromkeys(m.analyte_id for m in confirmed if m.analyte_id):
        analyte = references.analyte(analyte_id)
        if analyte is None:
            continue
        points = tuple(
            Point(taken_on=m.taken_on, value=m.value)
            for m in repo.snapshots.history(client_code, analyte_id)
            if m.confirmed and m.value is not None
        )
        if not points:
            continue
        chosen = select_target(analyte, subject)
        result.append(
            Series(
                analyte_id=analyte_id,
                title=analyte.name,
                units=analyte.units,
                points=points,
                target=chosen.optimal if chosen is not None else None,
            )
        )
    return tuple(result)
```

- [ ] **Step 6: Положить профиль в контекст**

В `src/healthcoach/app/deps.py` импортировать `Coach`, `load_coach`, добавить в `Context` поле `coach: Coach` и собирать его в `build_context` из `knowledge_dir / "coach.yaml"`.

- [ ] **Step 7: Прогнать весь набор и закоммитить**

```bash
uv run pytest -q
git add knowledge/coach.yaml src/healthcoach/knowledge/coach.py src/healthcoach/report/data.py src/healthcoach/app/deps.py tests/knowledge/test_coach.py tests/report/test_data.py
git commit -m "feat: профиль специалиста и сборка данных клиентского отчёта"
```

---

### Task 2: Графики динамики

**Files:**
- Create: `src/healthcoach/report/charts.py`
- Test: `tests/report/test_charts.py`

**Interfaces:**
- Consumes: `Series`, `Point` из `healthcoach.report.data`
- Produces: `chart_svg(series: Series, width: int = 520, height: int = 180) -> str`

**Что рисуется.** Полоса целевого коридора, линия по точкам, сами точки, подписи дат под крайними точками и подписи значений у точек. Ось значений подписывается минимумом и максимумом.

**Чего не рисуется.** График по одной точке. Это проверяет вызывающий по `has_dynamics`, но и сама функция обязана отказаться: молча нарисовать точку без линии — значит показать клиенту «динамику», которой нет.

**Почему SVG своим кодом.** График простой, а зависимость ради него тяжёлая. SVG вставляется прямо в HTML и печатается WeasyPrint без промежуточных файлов.

**Как считается масштаб.** По минимуму и максимуму значений вместе с границами коридора, чтобы коридор всегда был виден целиком. Если все значения равны — коридор задаёт размах; если и коридора нет, берётся ±10% от значения, иначе делить будет не на что.

- [ ] **Step 1: Написать падающие тесты**

Файл `tests/report/test_charts.py`:

```python
import re
import xml.etree.ElementTree as ET
from datetime import date

import pytest

from healthcoach.knowledge.references import Interval
from healthcoach.report.charts import ChartError, chart_svg
from healthcoach.report.data import Point, Series


def _series(values, target=Interval(60, 90)):
    points = tuple(
        Point(taken_on=date(2026, m, 1), value=v) for m, v in zip(range(3, 12), values)
    )
    return Series(
        analyte_id="ферритин", title="Ферритин", units="нг/мл",
        points=points, target=target,
    )


def test_svg_is_well_formed():
    svg = chart_svg(_series([18.0, 45.0, 70.0]))
    root = ET.fromstring(svg)
    assert root.tag.endswith("svg")


def test_a_point_per_measurement():
    svg = chart_svg(_series([18.0, 45.0, 70.0]))
    assert svg.count("<circle") == 3


def test_values_and_units_are_visible():
    svg = chart_svg(_series([18.0, 45.0]))
    assert "18" in svg
    assert "45" in svg
    assert "нг/мл" in svg


def test_target_corridor_is_drawn():
    svg = chart_svg(_series([18.0, 45.0], target=Interval(60, 90)))
    assert "<rect" in svg


def test_chart_without_a_target_still_draws():
    svg = chart_svg(_series([18.0, 45.0], target=None))
    ET.fromstring(svg)
    assert svg.count("<circle") == 2


def test_a_single_point_is_refused():
    """Одна точка — не динамика; нарисовать её значит соврать клиенту."""
    with pytest.raises(ChartError, match="одной точке"):
        chart_svg(_series([18.0]))


def test_equal_values_do_not_divide_by_zero():
    svg = chart_svg(_series([50.0, 50.0, 50.0], target=None))
    ET.fromstring(svg)
    assert svg.count("<circle") == 3


def test_points_stay_inside_the_canvas():
    """Точка за краем поля молча исчезнет при печати."""
    width, height = 400, 150
    svg = chart_svg(_series([18.0, 45.0, 200.0]), width=width, height=height)
    for cx, cy in re.findall(r'<circle cx="([\d.]+)" cy="([\d.]+)"', svg):
        assert 0 <= float(cx) <= width
        assert 0 <= float(cy) <= height


def test_dates_are_shown_for_the_ends():
    svg = chart_svg(_series([18.0, 45.0, 70.0]))
    assert "03.2026" in svg
    assert "05.2026" in svg


def test_hostile_title_cannot_break_the_markup():
    """Название приходит из базы знаний коуча, но экранируется как чужое."""
    series = Series(
        analyte_id="x", title='<script>alert("взлом")</script>', units="ед",
        points=(Point(date(2026, 3, 1), 1.0), Point(date(2026, 4, 1), 2.0)),
        target=None,
    )
    svg = chart_svg(series)
    assert "<script>" not in svg
    ET.fromstring(svg)
```

- [ ] **Step 2: Запустить тесты и убедиться, что они падают**

```bash
uv run pytest tests/report/test_charts.py -q
```

Ожидается: ошибка импорта `healthcoach.report.charts`.

- [ ] **Step 3: Реализовать графики**

Файл `src/healthcoach/report/charts.py`:

```python
"""Графики динамики показателей в SVG.

Своим кодом, а не библиотекой: график простой — полоса коридора, линия,
точки, — а зависимость ради него была бы тяжёлой. SVG вставляется прямо в
HTML и печатается без промежуточных файлов.
"""

from __future__ import annotations

import html

from healthcoach.report.data import Series

PADDING_LEFT = 46
PADDING_RIGHT = 12
PADDING_TOP = 14
PADDING_BOTTOM = 26


class ChartError(Exception):
    """График построить нельзя."""


def _scale(series: Series) -> tuple[float, float]:
    """Нижняя и верхняя границы оси значений.

    Коридор включается в размах целиком: клиент должен видеть, куда
    показатель идёт относительно цели, а не только сами точки.
    """
    values = [p.value for p in series.points]
    if series.target is not None:
        if series.target.low is not None:
            values.append(series.target.low)
        if series.target.high is not None:
            values.append(series.target.high)

    low, high = min(values), max(values)
    if low == high:
        # Все значения совпали и коридора нет — иначе делить не на что.
        spread = abs(low) * 0.1 or 1.0
        low, high = low - spread, high + spread

    margin = (high - low) * 0.1
    return low - margin, high + margin


def chart_svg(series: Series, width: int = 520, height: int = 180) -> str:
    """Нарисовать динамику показателя."""
    if not series.has_dynamics:
        raise ChartError(
            f"{series.analyte_id}: по одной точке динамики нет — график не строится"
        )

    low, high = _scale(series)
    plot_w = width - PADDING_LEFT - PADDING_RIGHT
    plot_h = height - PADDING_TOP - PADDING_BOTTOM

    def x(i: int) -> float:
        return PADDING_LEFT + plot_w * i / (len(series.points) - 1)

    def y(value: float) -> float:
        return PADDING_TOP + plot_h * (1 - (value - low) / (high - low))

    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
        f'viewBox="0 0 {width} {height}" role="img">',
        f'<title>{html.escape(series.title)}</title>',
    ]

    if series.target is not None and series.target.low is not None and series.target.high is not None:
        top, bottom = y(series.target.high), y(series.target.low)
        parts.append(
            f'<rect x="{PADDING_LEFT}" y="{top:.1f}" width="{plot_w}" '
            f'height="{bottom - top:.1f}" fill="#e8f2e8"/>'
        )

    line = " ".join(f"{x(i):.1f},{y(p.value):.1f}" for i, p in enumerate(series.points))
    parts.append(f'<polyline points="{line}" fill="none" stroke="#4a7c59" stroke-width="2"/>')

    for i, point in enumerate(series.points):
        px, py = x(i), y(point.value)
        parts.append(f'<circle cx="{px:.1f}" cy="{py:.1f}" r="4" fill="#4a7c59"/>')
        parts.append(
            f'<text x="{px:.1f}" y="{py - 9:.1f}" font-size="10" '
            f'text-anchor="middle" fill="#333">{point.value:g}</text>'
        )

    first, last = series.points[0], series.points[-1]
    parts.append(
        f'<text x="{PADDING_LEFT}" y="{height - 8}" font-size="9" fill="#666">'
        f'{first.taken_on.strftime("%m.%Y")}</text>'
    )
    parts.append(
        f'<text x="{width - PADDING_RIGHT}" y="{height - 8}" font-size="9" '
        f'text-anchor="end" fill="#666">{last.taken_on.strftime("%m.%Y")}</text>'
    )
    parts.append(
        f'<text x="4" y="{PADDING_TOP + 4}" font-size="9" fill="#666">{high:.0f}</text>'
    )
    parts.append(
        f'<text x="4" y="{height - PADDING_BOTTOM}" font-size="9" fill="#666">{low:.0f}</text>'
    )
    parts.append(
        f'<text x="4" y="{height - 8}" font-size="9" fill="#666">'
        f'{html.escape(series.units)}</text>'
    )

    parts.append("</svg>")
    return "".join(parts)
```

- [ ] **Step 4: Запустить тесты, прогнать набор, закоммитить**

```bash
uv run pytest tests/report/test_charts.py -q
uv run pytest -q
git add src/healthcoach/report/charts.py tests/report/test_charts.py
git commit -m "feat: графики динамики показателей в SVG"
```

---

### Task 3: Сборка PDF

**Files:**
- Create: `src/healthcoach/report/pdf.py`
- Create: `src/healthcoach/app/templates/report_pdf.html`
- Modify: `pyproject.toml` — добавить `weasyprint`
- Test: `tests/report/test_pdf.py`

**Interfaces:**
- Consumes: `ReportData`, `chart_svg`, `ChartError`
- Produces: `render_report_html(data: ReportData, templates) -> str`, `report_pdf(html: str) -> bytes`, `PdfBuildError`

**Про переменную окружения — это главное в задаче.** WeasyPrint загружает системные библиотеки через `dlopen` в момент импорта. На этой машине они лежат в `/opt/homebrew/lib`, которого нет в путях поиска по умолчанию, и импорт падает с `OSError: cannot load library 'libgobject-2.0-0'`. Проверено: установка `os.environ["DYLD_FALLBACK_LIBRARY_PATH"]` **до** импорта `weasyprint` решает это внутри процесса. Коуч не должен настраивать окружение руками, поэтому это делает сам модуль. Импорт `weasyprint` обязан быть **внутри функции**, после установки переменной, а не в начале файла.

**Структура отчёта** — из спецификации: титул, восемь разделов черновика в их порядке, графики динамики внутри раздела «динамика», дисклеймер. Ссылок на источники нет. Врачей нет — только специальности, и те приходят текстом из раздела «врачи».

**Что делать с разделом «динамика», когда динамики нет.** Раздел печатается как есть: модель, получив только одну точку, пишет, что это точка отсчёта. Графика при этом нет, и это правильно.

- [ ] **Step 1: Добавить зависимость**

В `pyproject.toml` в `dependencies` добавить `"weasyprint>=62"`.

- [ ] **Step 2: Написать падающие тесты**

Файл `tests/report/test_pdf.py`:

```python
from datetime import date, datetime

import pytest

from healthcoach.knowledge.coach import Coach
from healthcoach.knowledge.references import Interval
from healthcoach.report.data import Point, ReportData, Series
from healthcoach.report.pdf import PdfBuildError, report_pdf
from healthcoach.storage.drafts import DraftSection


def _section(section_id: str, text: str) -> DraftSection:
    return DraftSection(
        id=1, snapshot_id=1, section_id=section_id,
        generated=text, edited="", finding_ids=(),
    )


def _data(sections=None, series=()) -> ReportData:
    return ReportData(
        client_name="Соловьёва Ирина Анатольевна",
        client_code="CL-0001",
        taken_on=date(2026, 9, 1),
        coach=Coach(name="Иконникова Екатерина", title="нутрициолог", signature=""),
        sections=tuple(sections or [_section("запрос", "Текст запроса.")]),
        findings=(),
        series=series,
        approved_at=datetime(2026, 9, 2, 10, 0),
    )


def test_pdf_is_produced():
    pdf = report_pdf("<html><body><p>тест</p></body></html>")
    assert pdf[:5] == b"%PDF-"
    assert len(pdf) > 500


def test_cyrillic_survives_the_print():
    """Кириллица в PDF — то, ради чего выбран этот движок."""
    import pdfplumber, io

    pdf = report_pdf(
        '<html><head><meta charset="utf-8"></head><body>'
        "<p>Соловьёва Ирина — ферритин 18,0 нг/мл</p></body></html>"
    )
    with pdfplumber.open(io.BytesIO(pdf)) as doc:
        text = doc.pages[0].extract_text() or ""
    assert "Соловьёва" in text
    assert "нг/мл" in text


def test_page_breaks_are_honoured():
    """Отчёт на 5–10 страниц: разрывы должны работать, иначе это простыня."""
    import pdfplumber, io

    body = '<p>первая</p><div style="break-before:page"><p>вторая</p></div>'
    pdf = report_pdf(f'<html><head><meta charset="utf-8"></head><body>{body}</body></html>')
    with pdfplumber.open(io.BytesIO(pdf)) as doc:
        assert len(doc.pages) == 2


def test_broken_html_is_reported_not_swallowed():
    with pytest.raises(PdfBuildError):
        report_pdf(None)
```

- [ ] **Step 3: Запустить тесты и убедиться, что они падают**

```bash
uv run pytest tests/report/test_pdf.py -q
```

Ожидается: ошибка импорта `healthcoach.report.pdf`.

- [ ] **Step 4: Реализовать сборку PDF**

Файл `src/healthcoach/report/pdf.py`:

```python
"""Печать отчёта в PDF.

WeasyPrint загружает системные библиотеки через dlopen в момент импорта.
На macOS они ставятся homebrew в каталог, которого нет в путях поиска по
умолчанию, и импорт падает с «cannot load library 'libgobject-2.0-0'».
Поэтому путь добавляется здесь, до импорта, — коуч не должен настраивать
окружение руками, чтобы получить отчёт.
"""

from __future__ import annotations

import os
from pathlib import Path

LIBRARY_PATHS = ("/opt/homebrew/lib", "/usr/local/lib")
"""Куда homebrew кладёт pango и его зависимости: Apple Silicon и Intel."""


class PdfBuildError(Exception):
    """PDF собрать не удалось."""


def _prepare_library_path() -> None:
    existing = os.environ.get("DYLD_FALLBACK_LIBRARY_PATH", "")
    parts = [p for p in LIBRARY_PATHS if Path(p).is_dir()]
    if not parts:
        return
    if existing:
        parts.append(existing)
    os.environ["DYLD_FALLBACK_LIBRARY_PATH"] = ":".join(parts)


def report_pdf(html: str) -> bytes:
    """Напечатать HTML в PDF."""
    _prepare_library_path()
    try:
        from weasyprint import HTML
    except Exception as exc:  # системных библиотек нет — сказать прямо
        raise PdfBuildError(
            f"движок печати недоступен: {exc}. Нужен pango: brew install pango"
        ) from exc

    try:
        return HTML(string=html).write_pdf()
    except Exception as exc:
        raise PdfBuildError(f"отчёт не напечатан: {exc}") from exc


def render_report_html(data, templates) -> str:
    """Разложить данные отчёта по шаблону."""
    from healthcoach.report.charts import ChartError, chart_svg

    charts = {}
    for series in data.series:
        if not series.has_dynamics:
            continue
        try:
            charts[series.analyte_id] = chart_svg(series)
        except ChartError:
            continue

    template = templates.get_template("report_pdf.html")
    return template.render(data=data, charts=charts)
```

- [ ] **Step 5: Реализовать шаблон отчёта**

Файл `src/healthcoach/app/templates/report_pdf.html`. Титульный лист, затем разделы, затем дисклеймер. Раздел с идентификатором `динамика` печатает под своим текстом графики из `charts`. Ни имён врачей, ни ссылок на источники.

```html
<!doctype html>
<html lang="ru">
<head>
<meta charset="utf-8">
<title>Отчёт {{ data.client_name }}</title>
<style>
  @page {
    size: A4;
    margin: 20mm 18mm 22mm;
    @bottom-center { content: counter(page); font: 9pt sans-serif; color: #888; }
  }
  @page :first { @bottom-center { content: ""; } }
  body { font: 11pt/1.6 "Helvetica Neue", Helvetica, Arial, sans-serif; color: #222; }
  h1 { font-size: 17pt; margin: 0 0 .4em; }
  h2 { font-size: 13pt; margin: 1.6em 0 .5em; break-after: avoid; }
  p { margin: 0 0 .7em; orphans: 2; widows: 2; }
  .title-page { break-after: page; padding-top: 22vh; text-align: center; }
  .title-page .client { font-size: 20pt; margin-bottom: .3em; }
  .title-page .meta { color: #666; font-size: 11pt; }
  .chart { margin: 1em 0; break-inside: avoid; }
  .chart figcaption { font-size: 9pt; color: #666; margin-top: .2em; }
  .disclaimer { margin-top: 2em; padding-top: 1em; border-top: 1px solid #ddd;
                font-size: 9pt; color: #666; break-inside: avoid; }
</style>
</head>
<body>

<div class="title-page">
  <p class="client">{{ data.client_name }}</p>
  <h1>Отчёт по результатам обследования</h1>
  <p class="meta">Срез от {{ data.taken_on.strftime("%d.%m.%Y") }}</p>
  <p class="meta">{{ data.coach.name }}{% if data.coach.title %}, {{ data.coach.title }}{% endif %}</p>
</div>

{% for section in data.sections %}
<h2>{{ titles.get(section.section_id, section.section_id) }}</h2>
{% for paragraph in section.text.split("\n") %}
{% if paragraph.strip() %}<p>{{ paragraph.strip() }}</p>{% endif %}
{% endfor %}

{% if section.section_id == "динамика" %}
{% for series in data.series %}
{% if charts.get(series.analyte_id) %}
<figure class="chart">
  {{ charts[series.analyte_id] | safe }}
  <figcaption>{{ series.title }}, {{ series.units }}</figcaption>
</figure>
{% endif %}
{% endfor %}
{% endif %}
{% endfor %}

<div class="disclaimer">
  <p>Отчёт подготовлен специалистом по здоровью и не является медицинским
  заключением. Он не ставит диагноз и не назначает лечение. Решения о
  диагностике и терапии принимает врач.</p>
  <p>Утверждён {{ data.approved_at.strftime("%d.%m.%Y") }}.</p>
</div>

</body>
</html>
```

**Замечание исполнителю.** Шаблон обращается к `titles` — словарю «идентификатор раздела → заголовок». В `render_report_html` его нет. Возьмите его из `healthcoach.report.sections.SECTIONS` и передайте в `render`; заголовки уже там. Если найдёте другое несоответствие — доложите.

- [ ] **Step 6: Запустить тесты, прогнать набор, закоммитить**

```bash
uv run pytest tests/report/test_pdf.py -q
uv run pytest -q
git add pyproject.toml uv.lock src/healthcoach/report/pdf.py src/healthcoach/app/templates/report_pdf.html tests/report/test_pdf.py
git commit -m "feat: печать клиентского отчёта в PDF"
```

---

### Task 4: Выдача отчёта коучу

**Files:**
- Modify: `src/healthcoach/app/routes_report.py`
- Modify: `src/healthcoach/app/templates/report.html`
- Test: `tests/app/test_report_routes.py`

**Interfaces:**
- Consumes: `collect_report`, `ReportError`; `render_report_html`, `report_pdf`, `PdfBuildError`
- Produces: маршрут `GET /snapshots/{id}/report.pdf`

**Что отдаётся.** Файл с именем вида `отчёт-CL-0001-2026-09-01.pdf`, вложением. Кнопка появляется на экране черновика только после утверждения — до него скачивать нечего.

**Коды ответов.** Неизвестный срез — 404. Неутверждённый черновик — 409: черновик есть, но отдавать его нельзя. Движок печати недоступен — 503 с указанием, что поставить.

- [ ] **Step 1: Написать падающие тесты**

Дописать в `tests/app/test_report_routes.py`:

```python
def test_report_is_refused_until_the_draft_is_approved(client):
    """До утверждения отдавать клиенту нечего."""
    test_client, context, _ = client
    snapshot_id = _snapshot_with_a_finding(test_client, context)
    _approve_request(test_client, snapshot_id)
    test_client.post(f"/snapshots/{snapshot_id}/draft")

    response = test_client.get(f"/snapshots/{snapshot_id}/report.pdf")

    assert response.status_code == 409


def test_report_is_a_pdf_attachment_after_approval(client):
    test_client, context, _ = client
    snapshot_id = _snapshot_with_a_finding(test_client, context)
    _approve_request(test_client, snapshot_id)
    test_client.post(f"/snapshots/{snapshot_id}/draft")
    test_client.post(f"/snapshots/{snapshot_id}/draft/approve")

    response = test_client.get(f"/snapshots/{snapshot_id}/report.pdf")

    assert response.status_code == 200
    assert response.headers["content-type"] == "application/pdf"
    assert "attachment" in response.headers.get("content-disposition", "")
    assert response.content[:5] == b"%PDF-"


def test_report_of_an_unknown_snapshot_is_404(client):
    test_client, _, _ = client
    assert test_client.get("/snapshots/999/report.pdf").status_code == 404


def test_download_button_appears_only_after_approval(client):
    test_client, context, _ = client
    snapshot_id = _snapshot_with_a_finding(test_client, context)
    _approve_request(test_client, snapshot_id)
    test_client.post(f"/snapshots/{snapshot_id}/draft")

    before = test_client.get(f"/snapshots/{snapshot_id}/draft").text
    assert "report.pdf" not in before

    test_client.post(f"/snapshots/{snapshot_id}/draft/approve")

    after = test_client.get(f"/snapshots/{snapshot_id}/draft").text
    assert "report.pdf" in after
```

- [ ] **Step 2: Запустить тесты и убедиться, что они падают**

```bash
uv run pytest tests/app/test_report_routes.py -q
```

Ожидается: 404 вместо ожидаемых кодов — маршрута ещё нет.

- [ ] **Step 3: Реализовать маршрут**

В `src/healthcoach/app/routes_report.py` добавить маршрут. Все обращения к базе — внутри `with context.session() as repo:`; печать — за пределами сессии, чтобы соединение не держалось всё время сборки.

```python
    @router.get("/snapshots/{snapshot_id}/report.pdf")
    def report_file(snapshot_id: int):
        with context.session() as repo:
            snapshot = repo.snapshots.get(snapshot_id)
            if snapshot is None:
                raise HTTPException(status_code=404, detail=f"нет среза {snapshot_id}")
            try:
                data = collect_report(
                    repo, context.references, context.coach,
                    context.questionnaire, snapshot_id,
                )
            except ReportError as exc:
                raise HTTPException(status_code=409, detail=str(exc)) from exc

        try:
            body = report_pdf(render_report_html(data, templates))
        except PdfBuildError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc

        name = f"отчёт-{data.client_code}-{data.taken_on.isoformat()}.pdf"
        return Response(
            content=body,
            media_type="application/pdf",
            headers={"content-disposition": f'attachment; filename="{name}"'},
        )
```

- [ ] **Step 4: Добавить кнопку на экран черновика**

В `src/healthcoach/app/templates/report.html`, внутри блока, который отрисовывается при `approved_at`, добавить ссылку на скачивание.

```html
<p><a href="/snapshots/{{ snapshot.id }}/report.pdf">Скачать отчёт для клиента (PDF)</a></p>
```

- [ ] **Step 5: Запустить тесты**

```bash
uv run pytest tests/app -q
```

- [ ] **Step 6: Пройти сквозной путь руками**

```bash
uv run python -m healthcoach.app.main
```

1. Завести клиента, создать срез, приложить выгрузку из `samples/`, сверить показатель.
2. Ввести и вычитать запрос, утвердить, собрать черновик, утвердить черновик.
3. Скачать PDF. Открыть его и проверить глазами: титул с именем клиента и специалиста, разделы в порядке отчёта, кириллица не побита, дисклеймер на месте, страниц больше одной, номера страниц идут.
4. Создать второй срез тому же клиенту, ввести и сверить тот же показатель с другим значением, собрать и утвердить черновик, скачать PDF — в разделе «динамика» должен появиться график с двумя точками.
5. Остановить `Ctrl+C`, удалить `data/healthcoach.db` и `data/documents/`.

Приложите к отчёту, сколько получилось страниц и что показал график.

- [ ] **Step 7: Коммит**

```bash
git add src/healthcoach/app tests/app
git commit -m "feat: выдача клиентского отчёта в PDF"
```

---

## Что дальше

**Портфолио клиента с подсветкой доверенных врачей** — единственное, что осталось от исходного замысла плана 5. Врачи видны только коучу и передаются клиенту отдельно, в частном порядке; в PDF они не попадают никогда.

**Долги, записанные при исполнении планов 2–4** — см. «Что дальше» в плане 4. Отдельно напомню про укрепление обезличивания: партнёр отложил его сознательно, пять способов обхода записаны там же поимённо.

**Наполнение `knowledge/references/`.** В базе один показатель. Пока это так, отчёт будет коротким независимо от качества кода: большинство строк из выгрузок приходит нераспознанными, и модели нечего трактовать.
