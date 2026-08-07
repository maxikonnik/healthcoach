# Health Coaching MVP — план 1: детерминированное ядро

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Собрать проверяемое кодом ядро: база знаний загружается и валидируется, опросник считается по ключу, показатели сверяются с кастомными референсами коуча, на выходе — единый список находок.

**Architecture:** Чистая библиотека без интерфейса, сети и языковой модели. Два пакета: `knowledge` (загрузка и валидация YAML-базы) и `scoring` (детерминированные вычисления). Данные базы знаний лежат отдельно от кода, в папке `knowledge/` под git. Разовый инструмент импорта переносит спецификацию опросника из xlsx в YAML.

**Tech Stack:** Python 3.12, uv, PyYAML, pytest, openpyxl (только для разового импорта).

## Global Constraints

- Python 3.12 или новее. Системный Python в этой системе — 3.9, поэтому окружение ставится через uv (задача 1).
- Модули `knowledge` и `scoring` **не обращаются к языковой модели, сети и файловой системе вне папки базы знаний**. Это ядро, оно обязано быть воспроизводимым.
- Данные клиентов не попадают в репозиторий никогда. `.gitignore` уже закрывает `data/`, `clients/`, `*.db`, `registry.json`.
- Идентификаторы, названия и содержимое базы знаний — на русском. Имена в коде — на английском, кроме идентификаторов показателей в формулах производных, где кириллица допустима намеренно.
- Никаких молчаливых допущений: неизвестное значение, отсутствующее правило или несовпадение единиц дают явную пометку в результате, а не догадку.
- Каждая задача завершается запуском `uv run pytest` и коммитом.
- Файл `Большой_интегральный_опросник.xlsx` в корне репозитория — источник спецификации опросника. Его не редактируем.

---

### Task 1: Каркас проекта и окружение

**Files:**
- Create: `pyproject.toml`
- Create: `src/healthcoach/__init__.py`
- Create: `tests/test_smoke.py`

**Interfaces:**
- Consumes: ничего
- Produces: рабочее окружение `uv run pytest`; импортируемый пакет `healthcoach` с константой `__version__: str`

- [ ] **Step 1: Установить uv и Python 3.12**

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
export PATH="$HOME/.local/bin:$PATH"
uv python install 3.12
uv --version
```

Ожидается: команда `uv --version` печатает версию. Если `uv` не найден после установки — добавить `$HOME/.local/bin` в `PATH` в `~/.zshrc`.

- [ ] **Step 2: Создать `pyproject.toml`**

```toml
[project]
name = "healthcoach"
version = "0.1.0"
description = "Локальный инструмент health coaching специалиста"
requires-python = ">=3.12"
dependencies = [
    "pyyaml>=6.0.2",
]

[dependency-groups]
dev = [
    "pytest>=8.3",
    "openpyxl>=3.1",
]

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src/healthcoach"]

[tool.pytest.ini_options]
testpaths = ["tests"]
```

- [ ] **Step 3: Создать пакет**

Файл `src/healthcoach/__init__.py`:

```python
"""Локальный инструмент health coaching специалиста."""

__version__ = "0.1.0"
```

- [ ] **Step 4: Написать падающий smoke-тест**

Файл `tests/test_smoke.py`:

```python
from healthcoach import __version__


def test_package_importable():
    assert __version__ == "0.1.0"
```

- [ ] **Step 5: Запустить тест**

```bash
uv run pytest -v
```

Ожидается: PASS. Первый запуск создаст `.venv` и поставит зависимости.

- [ ] **Step 6: Коммит**

```bash
git add pyproject.toml src/healthcoach/__init__.py tests/test_smoke.py uv.lock
git commit -m "chore: каркас проекта на Python 3.12 и uv"
```

---

### Task 2: Модель спецификации опросника

**Files:**
- Create: `src/healthcoach/knowledge/__init__.py`
- Create: `src/healthcoach/knowledge/questionnaire.py`
- Create: `tests/knowledge/test_questionnaire_model.py`

**Interfaces:**
- Consumes: ничего
- Produces:
  - `ScaleOption(score: int, label: str)`
  - `Question(id: str, number: int, text: str, scale: tuple[ScaleOption, ...] | None)`
  - `Threshold(degree: str, min: int | None, max: int | None, sex: str | None)`
  - `Subscale(id: str, title: str, question_ids: tuple[str, ...], thresholds: tuple[Threshold, ...])`
  - `Block(id: str, title: str, part: str, core: bool, scale: tuple[ScaleOption, ...], questions: tuple[Question, ...], subscales: tuple[Subscale, ...])`
  - `Questionnaire(version: str, blocks: tuple[Block, ...])`
  - `Questionnaire.block(block_id: str) -> Block`
  - `Question.options() -> tuple[ScaleOption, ...]` — собственная шкала вопроса или шкала блока
  - `load_questionnaire(path: Path) -> Questionnaire`
  - `QuestionnaireError(Exception)`

**Пояснение к модели.** Подгруппа (`Subscale`) — это не только DASS. В опроснике коуча подгруппы есть у блоков «Питание» (Часть 1 и 2), «Эссенциальные нутриенты», «Женское здоровье» (репродуктивный период части 1 и 2, менопауза), «Системное воспаление», QEESI (пять разделов) и «Candida» (три раздела). У обычного блока ровно одна подгруппа с `id: "весь"`, покрывающая все его вопросы. Единая модель без ветвлений — у DASS подгруппы просто состоят из чересполосных вопросов.

- [ ] **Step 1: Написать падающие тесты**

Файл `tests/knowledge/test_questionnaire_model.py`:

```python
from pathlib import Path

import pytest

from healthcoach.knowledge.questionnaire import (
    QuestionnaireError,
    load_questionnaire,
)

FIXTURE = Path(__file__).parent / "fixtures" / "questionnaire_minimal.yaml"


def test_loads_blocks_and_questions():
    q = load_questionnaire(FIXTURE)
    assert q.version == "1.0"
    block = q.block("obraz_zhizni")
    assert block.title == "Образ жизни"
    assert block.part == "организационная"
    assert block.core is True
    assert len(block.questions) == 2


def test_question_falls_back_to_block_scale():
    q = load_questionnaire(FIXTURE)
    block = q.block("obraz_zhizni")
    zaryadka = next(x for x in block.questions if x.id == "obraz_zhizni.1")
    assert [o.score for o in zaryadka.options()] == [0, 1]

    sport = next(x for x in block.questions if x.id == "obraz_zhizni.2")
    assert [o.score for o in sport.options()] == [0, 1, 2, 3]


def test_subscale_thresholds_parsed():
    q = load_questionnaire(FIXTURE)
    sub = q.block("obraz_zhizni").subscales[0]
    assert sub.id == "весь"
    assert sub.question_ids == ("obraz_zhizni.1", "obraz_zhizni.2")
    high = sub.thresholds[0]
    assert (high.degree, high.min, high.max, high.sex) == ("высокая", 5, None, None)


def test_unknown_block_raises():
    q = load_questionnaire(FIXTURE)
    with pytest.raises(QuestionnaireError, match="нет блока"):
        q.block("нет_такого")


def test_subscale_referencing_unknown_question_raises(tmp_path):
    bad = tmp_path / "bad.yaml"
    bad.write_text(
        "version: '1.0'\n"
        "blocks:\n"
        "  - id: b\n"
        "    title: Б\n"
        "    part: организационная\n"
        "    core: true\n"
        "    scale: [{score: 0, label: нет}]\n"
        "    questions: [{id: b.1, number: 1, text: Вопрос}]\n"
        "    subscales:\n"
        "      - id: весь\n"
        "        title: Весь блок\n"
        "        question_ids: [b.99]\n"
        "        thresholds: []\n",
        encoding="utf-8",
    )
    with pytest.raises(QuestionnaireError, match="b.99"):
        load_questionnaire(bad)
```

Файл `tests/knowledge/fixtures/questionnaire_minimal.yaml`:

```yaml
version: "1.0"
blocks:
  - id: obraz_zhizni
    title: Образ жизни
    part: организационная
    core: true
    scale:
      - {score: 0, label: Да}
      - {score: 1, label: Нет}
    questions:
      - id: obraz_zhizni.1
        number: 1
        text: Ежедневная утренняя разминка/зарядка
      - id: obraz_zhizni.2
        number: 2
        text: Регулярные занятия спортом
        scale:
          - {score: 0, label: Два и больше в неделю}
          - {score: 1, label: Один раз в неделю}
          - {score: 2, label: Один или два раза в месяц}
          - {score: 3, label: Никогда}
    subscales:
      - id: весь
        title: Весь блок
        question_ids: [obraz_zhizni.1, obraz_zhizni.2]
        thresholds:
          - {degree: высокая, min: 5, max: null, sex: null}
```

- [ ] **Step 2: Запустить тесты и убедиться, что они падают**

```bash
uv run pytest tests/knowledge/test_questionnaire_model.py -v
```

Ожидается: FAIL с `ModuleNotFoundError: No module named 'healthcoach.knowledge'`.

- [ ] **Step 3: Реализовать модель**

Файл `src/healthcoach/knowledge/__init__.py`:

```python
"""Загрузка и валидация базы знаний коуча."""
```

Файл `src/healthcoach/knowledge/questionnaire.py`:

```python
"""Спецификация большого интегрального опросника."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml


class QuestionnaireError(Exception):
    """Спецификация опросника некорректна."""


@dataclass(frozen=True)
class ScaleOption:
    score: int
    label: str


@dataclass(frozen=True)
class Question:
    id: str
    number: int
    text: str
    scale: tuple[ScaleOption, ...] | None
    block_scale: tuple[ScaleOption, ...]

    def options(self) -> tuple[ScaleOption, ...]:
        """Собственная шкала вопроса, иначе шкала блока."""
        return self.scale if self.scale else self.block_scale


@dataclass(frozen=True)
class Threshold:
    degree: str
    min: int | None
    max: int | None
    sex: str | None


@dataclass(frozen=True)
class Subscale:
    id: str
    title: str
    question_ids: tuple[str, ...]
    thresholds: tuple[Threshold, ...]


@dataclass(frozen=True)
class Block:
    id: str
    title: str
    part: str
    core: bool
    scale: tuple[ScaleOption, ...]
    questions: tuple[Question, ...]
    subscales: tuple[Subscale, ...]


@dataclass(frozen=True)
class Questionnaire:
    version: str
    blocks: tuple[Block, ...]

    def block(self, block_id: str) -> Block:
        for block in self.blocks:
            if block.id == block_id:
                return block
        raise QuestionnaireError(f"в спецификации нет блока {block_id!r}")


def _scale(raw: list[dict] | None) -> tuple[ScaleOption, ...] | None:
    if raw is None:
        return None
    return tuple(ScaleOption(score=int(o["score"]), label=str(o["label"])) for o in raw)


def _threshold(raw: dict) -> Threshold:
    return Threshold(
        degree=str(raw["degree"]),
        min=None if raw.get("min") is None else int(raw["min"]),
        max=None if raw.get("max") is None else int(raw["max"]),
        sex=None if raw.get("sex") is None else str(raw["sex"]),
    )


def _block(raw: dict) -> Block:
    block_scale = _scale(raw["scale"])
    if not block_scale:
        raise QuestionnaireError(f"блок {raw['id']!r}: пустая шкала")

    questions = tuple(
        Question(
            id=str(q["id"]),
            number=int(q["number"]),
            text=str(q["text"]),
            scale=_scale(q.get("scale")),
            block_scale=block_scale,
        )
        for q in raw["questions"]
    )
    known = {q.id for q in questions}

    subscales = []
    for sub in raw["subscales"]:
        ids = tuple(str(i) for i in sub["question_ids"])
        for question_id in ids:
            if question_id not in known:
                raise QuestionnaireError(
                    f"блок {raw['id']!r}, подгруппа {sub['id']!r}: "
                    f"ссылка на неизвестный вопрос {question_id!r}"
                )
        subscales.append(
            Subscale(
                id=str(sub["id"]),
                title=str(sub["title"]),
                question_ids=ids,
                thresholds=tuple(_threshold(t) for t in sub["thresholds"]),
            )
        )

    return Block(
        id=str(raw["id"]),
        title=str(raw["title"]),
        part=str(raw["part"]),
        core=bool(raw["core"]),
        scale=block_scale,
        questions=questions,
        subscales=tuple(subscales),
    )


def load_questionnaire(path: Path) -> Questionnaire:
    """Прочитать спецификацию опросника из YAML."""
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not raw or "blocks" not in raw:
        raise QuestionnaireError(f"{path}: нет ключа 'blocks'")

    blocks = tuple(_block(b) for b in raw["blocks"])
    ids = [b.id for b in blocks]
    duplicates = {i for i in ids if ids.count(i) > 1}
    if duplicates:
        raise QuestionnaireError(f"повторяющиеся идентификаторы блоков: {sorted(duplicates)}")

    return Questionnaire(version=str(raw["version"]), blocks=blocks)
```

- [ ] **Step 4: Запустить тесты**

```bash
uv run pytest tests/knowledge/test_questionnaire_model.py -v
```

Ожидается: 5 PASS.

- [ ] **Step 5: Коммит**

```bash
git add src/healthcoach/knowledge tests/knowledge
git commit -m "feat: модель спецификации опросника с подгруппами и пошкальными вопросами"
```

---

### Task 3: Валидатор порогов и разовый импорт из xlsx

**Files:**
- Create: `src/healthcoach/knowledge/validation.py`
- Create: `tools/import_questionnaire.py`
- Create: `tests/knowledge/test_validation.py`

**Interfaces:**
- Consumes: `Questionnaire`, `Subscale`, `Threshold`, `QuestionnaireError` из задачи 2
- Produces:
  - `Problem(where: str, message: str)`
  - `validate_questionnaire(q: Questionnaire) -> list[Problem]`
  - `parse_threshold_range(text: str) -> tuple[int | None, int | None]`
  - `RangeParseError(Exception)`

**Зачем валидатор.** В исходном xlsx на листе «РЕЗУЛЬТАТ КЛЮЧ» у блока «Опросник Candida» пороги заданы как `<40` (низкая), `41-140` (средняя), `<140` (высокая) для мужчин и `<60` / `61-180` / `<180` для женщин. Высокая степень с верхней границей, равной верхней границе средней, — почти наверняка опечатка: должно быть `>140` и `>180`. Валидатор ловит такие случаи: пересечения диапазонов, разрывы между ними и отсутствие открытого верхнего порога. Импорт печатает находки, коуч решает.

- [ ] **Step 1: Написать падающие тесты**

Файл `tests/knowledge/test_validation.py`:

```python
import pytest

from healthcoach.knowledge.questionnaire import (
    Block,
    Question,
    Questionnaire,
    ScaleOption,
    Subscale,
    Threshold,
)
from healthcoach.knowledge.validation import (
    RangeParseError,
    parse_threshold_range,
    validate_questionnaire,
)


@pytest.mark.parametrize(
    "text, expected",
    [
        ("4-8", (4, 8)),
        ("0-19", (0, 19)),
        (">14", (15, None)),
        ("> 14", (15, None)),
        ("<40", (None, 39)),
        ("40-100", (40, 100)),
    ],
)
def test_parse_threshold_range(text, expected):
    assert parse_threshold_range(text) == expected


def test_parse_threshold_range_rejects_garbage():
    with pytest.raises(RangeParseError, match="не удалось разобрать"):
        parse_threshold_range("много")


def _questionnaire(thresholds: list[Threshold]) -> Questionnaire:
    scale = (ScaleOption(0, "нет"), ScaleOption(1, "да"))
    question = Question(
        id="b.1", number=1, text="Вопрос", scale=None, block_scale=scale
    )
    block = Block(
        id="b",
        title="Блок",
        part="клиническая",
        core=True,
        scale=scale,
        questions=(question,),
        subscales=(
            Subscale(
                id="весь",
                title="Весь блок",
                question_ids=("b.1",),
                thresholds=tuple(thresholds),
            ),
        ),
    )
    return Questionnaire(version="1.0", blocks=(block,))


def test_valid_thresholds_produce_no_problems():
    q = _questionnaire(
        [
            Threshold("низкая", 4, 8, None),
            Threshold("средняя", 9, 13, None),
            Threshold("высокая", 14, None, None),
        ]
    )
    assert validate_questionnaire(q) == []


def test_overlapping_thresholds_reported():
    q = _questionnaire(
        [
            Threshold("низкая", 4, 8, None),
            Threshold("средняя", 7, 13, None),
        ]
    )
    problems = validate_questionnaire(q)
    assert any("пересекаются" in p.message for p in problems)


def test_gap_between_thresholds_reported():
    q = _questionnaire(
        [
            Threshold("низкая", 4, 8, None),
            Threshold("средняя", 12, 20, None),
        ]
    )
    problems = validate_questionnaire(q)
    assert any("разрыв" in p.message for p in problems)


def test_candida_style_bounded_top_degree_reported():
    """Высшая степень с верхней границей — та самая опечатка в исходном xlsx."""
    q = _questionnaire(
        [
            Threshold("низкая", None, 40, None),
            Threshold("средняя", 41, 140, None),
            Threshold("высокая", None, 140, None),
        ]
    )
    problems = validate_questionnaire(q)
    assert any("верхняя граница" in p.message for p in problems)


def test_degrees_checked_per_sex_independently():
    q = _questionnaire(
        [
            Threshold("низкая", 0, 40, "м"),
            Threshold("высокая", 41, None, "м"),
            Threshold("низкая", 0, 60, "ж"),
            Threshold("высокая", 61, None, "ж"),
        ]
    )
    assert validate_questionnaire(q) == []
```

- [ ] **Step 2: Запустить тесты и убедиться, что они падают**

```bash
uv run pytest tests/knowledge/test_validation.py -v
```

Ожидается: FAIL с `ModuleNotFoundError: No module named 'healthcoach.knowledge.validation'`.

- [ ] **Step 3: Реализовать валидатор**

Файл `src/healthcoach/knowledge/validation.py`:

```python
"""Проверка спецификации опросника на внутренние противоречия."""

from __future__ import annotations

import re
from dataclasses import dataclass

from healthcoach.knowledge.questionnaire import Questionnaire, Subscale, Threshold

_RANGE = re.compile(r"^\s*(\d+)\s*-\s*(\d+)\s*$")
_GREATER = re.compile(r"^\s*>\s*(\d+)\s*$")
_LESS = re.compile(r"^\s*<\s*(\d+)\s*$")

_DEGREE_ORDER = ("низкая", "средняя", "умеренная", "высокая", "тяжёлая", "очень тяжёлая")


class RangeParseError(Exception):
    """Диапазон порога записан в неизвестном формате."""


@dataclass(frozen=True)
class Problem:
    where: str
    message: str


def parse_threshold_range(text: str) -> tuple[int | None, int | None]:
    """Разобрать запись диапазона из ключа опросника.

    Баллы целые, поэтому строгие неравенства сводятся к включающим границам:
    ">14" — это 15 и выше, "<40" — это 39 и ниже.
    """
    if (m := _RANGE.match(text)) is not None:
        return int(m.group(1)), int(m.group(2))
    if (m := _GREATER.match(text)) is not None:
        return int(m.group(1)) + 1, None
    if (m := _LESS.match(text)) is not None:
        return None, int(m.group(1)) - 1
    raise RangeParseError(f"не удалось разобрать диапазон {text!r}")


def _sort_key(threshold: Threshold) -> tuple[int, int]:
    order = (
        _DEGREE_ORDER.index(threshold.degree)
        if threshold.degree in _DEGREE_ORDER
        else len(_DEGREE_ORDER)
    )
    lower = threshold.min if threshold.min is not None else -10**9
    return order, lower


def _check_group(where: str, thresholds: list[Threshold]) -> list[Problem]:
    problems: list[Problem] = []
    ordered = sorted(thresholds, key=_sort_key)

    for earlier, later in zip(ordered, ordered[1:]):
        earlier_top = earlier.max
        later_bottom = later.min
        if earlier_top is None:
            problems.append(
                Problem(
                    where,
                    f"степень {earlier.degree!r} не имеет верхней границы, "
                    f"но после неё идёт {later.degree!r}",
                )
            )
            continue
        if later_bottom is None:
            continue
        if later_bottom <= earlier_top:
            problems.append(
                Problem(
                    where,
                    f"диапазоны {earlier.degree!r} и {later.degree!r} пересекаются: "
                    f"{earlier_top} и {later_bottom}",
                )
            )
        elif later_bottom > earlier_top + 1:
            problems.append(
                Problem(
                    where,
                    f"разрыв между {earlier.degree!r} и {later.degree!r}: "
                    f"баллы {earlier_top + 1}..{later_bottom - 1} никуда не попадают",
                )
            )

    if ordered and ordered[-1].max is not None:
        last = ordered[-1]
        problems.append(
            Problem(
                where,
                f"у высшей степени {last.degree!r} задана верхняя граница {last.max} — "
                f"баллы выше неё не получат никакой степени; вероятно, в источнике "
                f"должно быть '>{last.max}'",
            )
        )

    return problems


def _check_subscale(block_id: str, subscale: Subscale) -> list[Problem]:
    if not subscale.thresholds:
        return []
    where = f"{block_id}/{subscale.id}"

    by_sex: dict[str | None, list[Threshold]] = {}
    for threshold in subscale.thresholds:
        by_sex.setdefault(threshold.sex, []).append(threshold)

    problems: list[Problem] = []
    for sex, group in sorted(by_sex.items(), key=lambda kv: kv[0] or ""):
        label = where if sex is None else f"{where} (пол: {sex})"
        problems.extend(_check_group(label, group))
    return problems


def validate_questionnaire(questionnaire: Questionnaire) -> list[Problem]:
    """Найти пересечения, разрывы и незакрытые верхние пороги."""
    problems: list[Problem] = []
    for block in questionnaire.blocks:
        for subscale in block.subscales:
            problems.extend(_check_subscale(block.id, subscale))
    return problems
```

- [ ] **Step 4: Запустить тесты**

```bash
uv run pytest tests/knowledge/test_validation.py -v
```

Ожидается: 12 PASS (6 параметризованных плюс 6 обычных).

- [ ] **Step 5: Написать инструмент импорта**

Файл `tools/import_questionnaire.py`:

```python
"""Разовый импорт спецификации опросника из xlsx в YAML-черновик.

Извлечение приблизительное: в исходном файле шкалы лежат в отдельной колонке,
часть шкал вписана прямо в текст вопроса, а подгруппы размечены слиянием ячеек.
Инструмент вытаскивает всё, что может, и помечает сомнительное строкой
"ПРОВЕРИТЬ". Результат дорабатывается руками один раз, после чего YAML
становится источником правды, а этот скрипт больше не нужен.

Запуск:
    uv run python tools/import_questionnaire.py \\
        Большой_интегральный_опросник.xlsx knowledge/questionnaire.draft.yaml
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

from openpyxl import load_workbook

SHEET_QUESTIONS = "ОПРОСНИК"
SHEET_KEY = "РЕЗУЛЬТАТ КЛЮЧ"

_SECTION = re.compile(r"^\s*(?:\d+\.\s*)?([А-ЯЁ][А-ЯЁ \-/()]{4,})\s*$")
_INLINE_SCALE = re.compile(r"^\s*(\d)\s*[-–]\s*(.+)$")


def slugify(title: str) -> str:
    table = str.maketrans(
        "абвгдеёжзийклмнопрстуфхцчшщъыьэюя",
        "abvgdeezziyklmnoprstufhccss_y_eua",
    )
    return re.sub(r"[^a-z0-9]+", "_", title.strip().lower().translate(table)).strip("_")


def split_inline_scale(text: str) -> tuple[str, list[dict]]:
    """Отделить шкалу, вписанную в текст вопроса переводами строки."""
    lines = [line for line in text.splitlines() if line.strip()]
    question_lines: list[str] = []
    options: list[dict] = []
    for line in lines:
        if (m := _INLINE_SCALE.match(line)) is not None:
            options.append({"score": int(m.group(1)), "label": m.group(2).strip()})
        else:
            question_lines.append(line.strip())
    return " ".join(question_lines), options


def main(xlsx: Path, out: Path) -> None:
    workbook = load_workbook(xlsx, data_only=True)
    sheet = workbook[SHEET_QUESTIONS]

    lines: list[str] = ['version: "1.0"', "blocks:"]
    current: str | None = None

    for row in sheet.iter_rows(min_row=1, max_col=8):
        a = row[0].value
        b = row[1].value
        h = row[7].value

        if isinstance(a, str) and _SECTION.match(a) and not b:
            title = _SECTION.match(a).group(1).strip().capitalize()
            current = slugify(title)
            lines += [
                f"  - id: {current}",
                f"    title: {title}",
                "    part: ПРОВЕРИТЬ  # организационная | клиническая | дополнительная",
                "    core: ПРОВЕРИТЬ  # true для ядра, false для дополнительных",
                "    scale: []  # ПРОВЕРИТЬ: перенести шкалу из колонки H",
                "    questions:",
            ]
            if isinstance(h, str) and h.strip():
                lines.append(f"    # шкала из колонки H: {h.strip()!r}")
            continue

        if current and isinstance(a, int) and isinstance(b, str):
            text, inline = split_inline_scale(b)
            lines.append(f"      - id: {current}.{a}")
            lines.append(f"        number: {a}")
            lines.append(f"        text: {text!r}")
            if inline:
                lines.append("        scale:")
                for option in inline:
                    lines.append(
                        f"          - {{score: {option['score']}, "
                        f"label: {option['label']!r}}}"
                    )

    lines += [
        "",
        "# ПРОВЕРИТЬ: подгруппы и пороги перенести с листа "
        f"{SHEET_KEY!r} вручную,",
        "# затем прогнать validate_questionnaire — он поймает пересечения и разрывы.",
    ]

    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"черновик записан: {out}")
    print("дальше: заполнить пометки ПРОВЕРИТЬ и перенести пороги с листа ключа")


if __name__ == "__main__":
    if len(sys.argv) != 3:
        raise SystemExit(__doc__)
    main(Path(sys.argv[1]), Path(sys.argv[2]))
```

- [ ] **Step 6: Прогнать импорт и убедиться, что черновик читается**

```bash
uv run python tools/import_questionnaire.py \
    Большой_интегральный_опросник.xlsx knowledge/questionnaire.draft.yaml
head -40 knowledge/questionnaire.draft.yaml
```

Ожидается: файл создан, в нём видны блоки и вопросы с пометками `ПРОВЕРИТЬ`. Черновик **не коммитим** — он рабочий материал; в репозиторий пойдёт доведённый вручную `knowledge/questionnaire.yaml` в следующей задаче.

- [ ] **Step 7: Коммит**

```bash
git add src/healthcoach/knowledge/validation.py tools/import_questionnaire.py tests/knowledge/test_validation.py
git commit -m "feat: валидатор порогов опросника и разовый импорт из xlsx"
```

---

### Task 4: Скоринг опросника

**Files:**
- Create: `src/healthcoach/scoring/__init__.py`
- Create: `src/healthcoach/scoring/questionnaire.py`
- Create: `tests/scoring/test_questionnaire_scoring.py`

**Interfaces:**
- Consumes: `Questionnaire`, `Block`, `Subscale`, `Threshold` из задачи 2
- Produces:
  - `Answers = dict[str, int]` — идентификатор вопроса в выбранный балл
  - `SubscaleScore(block_id: str, block_title: str, subscale_id: str, subscale_title: str, score: int, degree: str | None, answered: int, total: int)`
  - `score_questionnaire(q: Questionnaire, answers: Answers, sex: str) -> list[SubscaleScore]`
  - `ScoringError(Exception)`

**Правила.** Балл вне шкалы вопроса — ошибка, а не тихое обнуление. Незаполненные вопросы не считаются нулями: они уменьшают `answered`, и подгруппа, заполненная меньше чем на две трети, получает `degree = None` с сохранённой суммой — коуч увидит, что данных не хватило. Подгруппы, ни один вопрос которых не отвечен, в результат не попадают: это блоки, не выданные клиенту.

- [ ] **Step 1: Написать падающие тесты**

Файл `tests/scoring/test_questionnaire_scoring.py`:

```python
import pytest

from healthcoach.knowledge.questionnaire import (
    Block,
    Question,
    Questionnaire,
    ScaleOption,
    Subscale,
    Threshold,
)
from healthcoach.scoring.questionnaire import ScoringError, score_questionnaire

SCALE = (
    ScaleOption(0, "не актуально"),
    ScaleOption(1, "иногда"),
    ScaleOption(2, "средне"),
    ScaleOption(3, "сильно"),
)


def _block(thresholds: tuple[Threshold, ...], count: int = 6) -> Block:
    questions = tuple(
        Question(
            id=f"zheludok.{i}",
            number=i,
            text=f"Симптом {i}",
            scale=None,
            block_scale=SCALE,
        )
        for i in range(1, count + 1)
    )
    return Block(
        id="zheludok",
        title="Желудок и П/Ж",
        part="клиническая",
        core=True,
        scale=SCALE,
        questions=questions,
        subscales=(
            Subscale(
                id="весь",
                title="Весь блок",
                question_ids=tuple(q.id for q in questions),
                thresholds=thresholds,
            ),
        ),
    )


THRESHOLDS = (
    Threshold("низкая", 6, 10, None),
    Threshold("средняя", 11, 15, None),
    Threshold("высокая", 16, None, None),
)


def _questionnaire(**kwargs) -> Questionnaire:
    return Questionnaire(version="1.0", blocks=(_block(THRESHOLDS, **kwargs),))


def test_sums_answers_and_resolves_degree():
    q = _questionnaire()
    answers = {f"zheludok.{i}": 2 for i in range(1, 7)}  # сумма 12
    (result,) = score_questionnaire(q, answers, sex="ж")
    assert result.score == 12
    assert result.degree == "средняя"
    assert result.answered == 6
    assert result.total == 6
    assert result.block_title == "Желудок и П/Ж"


def test_score_below_lowest_threshold_has_no_degree():
    q = _questionnaire()
    answers = {f"zheludok.{i}": 0 for i in range(1, 7)}
    answers["zheludok.1"] = 3  # сумма 3, ниже низкой степени
    (result,) = score_questionnaire(q, answers, sex="ж")
    assert result.score == 3
    assert result.degree is None


def test_open_top_threshold_matches():
    q = _questionnaire()
    answers = {f"zheludok.{i}": 3 for i in range(1, 7)}  # сумма 18
    (result,) = score_questionnaire(q, answers, sex="ж")
    assert result.degree == "высокая"


def test_sex_specific_thresholds_selected():
    block = _block(
        (
            Threshold("низкая", 0, 5, "м"),
            Threshold("высокая", 6, None, "м"),
            Threshold("низкая", 0, 12, "ж"),
            Threshold("высокая", 13, None, "ж"),
        )
    )
    q = Questionnaire(version="1.0", blocks=(block,))
    answers = {f"zheludok.{i}": 2 for i in range(1, 7)}  # сумма 12

    (male,) = score_questionnaire(q, answers, sex="м")
    (female,) = score_questionnaire(q, answers, sex="ж")
    assert male.degree == "высокая"
    assert female.degree == "низкая"


def test_sparse_subscale_keeps_score_but_drops_degree():
    q = _questionnaire()
    answers = {"zheludok.1": 3, "zheludok.2": 3}  # отвечено 2 из 6
    (result,) = score_questionnaire(q, answers, sex="ж")
    assert result.score == 6
    assert result.answered == 2
    assert result.degree is None


def test_unanswered_subscale_omitted():
    q = _questionnaire()
    assert score_questionnaire(q, {}, sex="ж") == []


def test_answer_outside_scale_raises():
    q = _questionnaire()
    answers = {f"zheludok.{i}": 0 for i in range(1, 7)}
    answers["zheludok.3"] = 7
    with pytest.raises(ScoringError, match="zheludok.3"):
        score_questionnaire(q, answers, sex="ж")


def test_answer_for_unknown_question_raises():
    q = _questionnaire()
    with pytest.raises(ScoringError, match="нет в спецификации"):
        score_questionnaire(q, {"выдуманный.1": 1}, sex="ж")
```

- [ ] **Step 2: Запустить тесты и убедиться, что они падают**

```bash
uv run pytest tests/scoring/test_questionnaire_scoring.py -v
```

Ожидается: FAIL с `ModuleNotFoundError: No module named 'healthcoach.scoring'`.

- [ ] **Step 3: Реализовать скоринг**

Файл `src/healthcoach/scoring/__init__.py`:

```python
"""Детерминированные вычисления. Модуль не обращается к языковой модели."""
```

Файл `src/healthcoach/scoring/questionnaire.py`:

```python
"""Скоринг опросника по ключу коуча."""

from __future__ import annotations

from dataclasses import dataclass

from healthcoach.knowledge.questionnaire import (
    Block,
    Questionnaire,
    Subscale,
    Threshold,
)

Answers = dict[str, int]

MIN_ANSWERED_SHARE = 2 / 3
"""Ниже этой доли заполненности степень отклонения не выносится."""


class ScoringError(Exception):
    """Ответы не согласуются со спецификацией опросника."""


@dataclass(frozen=True)
class SubscaleScore:
    block_id: str
    block_title: str
    subscale_id: str
    subscale_title: str
    score: int
    degree: str | None
    answered: int
    total: int


def _contains(threshold: Threshold, score: int) -> bool:
    if threshold.min is not None and score < threshold.min:
        return False
    if threshold.max is not None and score > threshold.max:
        return False
    return True


def _degree(thresholds: tuple[Threshold, ...], score: int, sex: str) -> str | None:
    applicable = [t for t in thresholds if t.sex is None or t.sex == sex]
    for threshold in applicable:
        if _contains(threshold, score):
            return threshold.degree
    return None


def _validate(questionnaire: Questionnaire, answers: Answers) -> None:
    known: dict[str, set[int]] = {}
    for block in questionnaire.blocks:
        for question in block.questions:
            known[question.id] = {o.score for o in question.options()}

    for question_id, value in answers.items():
        if question_id not in known:
            raise ScoringError(f"вопроса {question_id!r} нет в спецификации опросника")
        if value not in known[question_id]:
            raise ScoringError(
                f"вопрос {question_id!r}: балл {value} вне шкалы "
                f"{sorted(known[question_id])}"
            )


def _score_subscale(
    block: Block, subscale: Subscale, answers: Answers, sex: str
) -> SubscaleScore | None:
    given = [answers[q] for q in subscale.question_ids if q in answers]
    if not given:
        return None

    total = len(subscale.question_ids)
    answered = len(given)
    score = sum(given)

    if answered / total >= MIN_ANSWERED_SHARE:
        degree = _degree(subscale.thresholds, score, sex)
    else:
        degree = None

    return SubscaleScore(
        block_id=block.id,
        block_title=block.title,
        subscale_id=subscale.id,
        subscale_title=subscale.title,
        score=score,
        degree=degree,
        answered=answered,
        total=total,
    )


def score_questionnaire(
    questionnaire: Questionnaire, answers: Answers, sex: str
) -> list[SubscaleScore]:
    """Посчитать суммы по подгруппам и вынести степени отклонения."""
    _validate(questionnaire, answers)

    results: list[SubscaleScore] = []
    for block in questionnaire.blocks:
        for subscale in block.subscales:
            scored = _score_subscale(block, subscale, answers, sex)
            if scored is not None:
                results.append(scored)
    return results
```

- [ ] **Step 4: Запустить тесты**

```bash
uv run pytest tests/scoring/test_questionnaire_scoring.py -v
```

Ожидается: 8 PASS.

- [ ] **Step 5: Коммит**

```bash
git add src/healthcoach/scoring tests/scoring
git commit -m "feat: скоринг опросника с полозависимыми порогами и контролем заполненности"
```

---

### Task 5: Модель референсов

**Files:**
- Create: `src/healthcoach/knowledge/references.py`
- Create: `knowledge/references/ferritin.yaml`
- Create: `tests/knowledge/test_references_model.py`

**Interfaces:**
- Consumes: ничего
- Produces:
  - `Interval(low: float | None, high: float | None)`, метод `contains(value: float) -> bool`
  - `Condition(sex: str | None, age_min: int | None, age_max: int | None, cycle_phase: str | None)`, метод `matches(sex, age, cycle_phase) -> bool`
  - `Target(condition: Condition, optimal: Interval, deficient: Interval | None, excessive: Interval | None)`
  - `Analyte(id, name, synonyms, units, lab_range, targets, interpret_with, note)`
  - `Derived(id, name, formula, optimal, note)`
  - `References(analytes: tuple[Analyte, ...], derived: tuple[Derived, ...])`
  - `References.analyte(analyte_id: str) -> Analyte | None`
  - `References.resolve(name: str) -> Analyte | None` — поиск по названию и синонимам без учёта регистра
  - `load_references(directory: Path) -> References`
  - `ReferenceError(Exception)`

- [ ] **Step 1: Написать падающие тесты**

Файл `tests/knowledge/test_references_model.py`:

```python
from pathlib import Path

import pytest

from healthcoach.knowledge.references import (
    Condition,
    Interval,
    ReferenceError,
    load_references,
)

REFS = Path(__file__).parents[2] / "knowledge" / "references"


def test_interval_contains_with_open_bounds():
    assert Interval(60, 90).contains(75)
    assert not Interval(60, 90).contains(59.9)
    assert Interval(None, 30).contains(5)
    assert Interval(80, None).contains(1000)


def test_condition_matches_sex_and_age():
    c = Condition(sex="ж", age_min=18, age_max=50, cycle_phase=None)
    assert c.matches(sex="ж", age=30, cycle_phase=None)
    assert not c.matches(sex="м", age=30, cycle_phase=None)
    assert not c.matches(sex="ж", age=55, cycle_phase=None)


def test_empty_condition_matches_anything():
    c = Condition(sex=None, age_min=None, age_max=None, cycle_phase=None)
    assert c.matches(sex="м", age=70, cycle_phase="лютеиновая")


def test_loads_ferritin_from_knowledge_base():
    refs = load_references(REFS)
    ferritin = refs.analyte("ферритин")
    assert ferritin is not None
    assert ferritin.units == "нг/мл"
    assert ferritin.lab_range == Interval(10, 120)
    assert "срб" in ferritin.interpret_with
    assert len(ferritin.targets) >= 2


def test_resolve_by_synonym_ignores_case():
    refs = load_references(REFS)
    assert refs.resolve("FERRITIN") is refs.analyte("ферритин")
    assert refs.resolve("  Ферритин ") is refs.analyte("ферритин")
    assert refs.resolve("несуществующий") is None


def test_duplicate_analyte_id_raises(tmp_path):
    for name in ("a.yaml", "b.yaml"):
        (tmp_path / name).write_text(
            "показатели:\n"
            "  - id: дубль\n"
            "    название: Дубль\n"
            "    единицы: ед\n"
            "    целевые:\n"
            "      - оптимум: [1, 2]\n",
            encoding="utf-8",
        )
    with pytest.raises(ReferenceError, match="дубль"):
        load_references(tmp_path)


def test_target_without_optimal_raises(tmp_path):
    (tmp_path / "x.yaml").write_text(
        "показатели:\n"
        "  - id: x\n"
        "    название: Икс\n"
        "    единицы: ед\n"
        "    целевые:\n"
        "      - условие: {пол: м}\n",
        encoding="utf-8",
    )
    with pytest.raises(ReferenceError, match="оптимум"):
        load_references(tmp_path)
```

Файл `knowledge/references/ferritin.yaml`:

```yaml
показатели:
  - id: ферритин
    название: Ферритин
    синонимы: [Ферритин, Ferritin, S-Ferritin]
    единицы: нг/мл
    лабораторный_интервал: [10, 120]
    трактовать_с: [срб]
    заметка: Растёт при воспалении — смотреть вместе с СРБ
    целевые:
      - условие: {пол: ж, возраст: [18, 50]}
        оптимум: [60, 90]
        дефицит: [null, 30]
      - условие: {пол: м}
        оптимум: [80, 150]
        дефицит: [null, 40]
      - оптимум: [60, 120]
        дефицит: [null, 30]
```

- [ ] **Step 2: Запустить тесты и убедиться, что они падают**

```bash
uv run pytest tests/knowledge/test_references_model.py -v
```

Ожидается: FAIL с `ModuleNotFoundError: No module named 'healthcoach.knowledge.references'`.

- [ ] **Step 3: Реализовать модель референсов**

Файл `src/healthcoach/knowledge/references.py`:

```python
"""Кастомные превентивные референсы коуча."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml


class ReferenceError(Exception):
    """Файл референсов некорректен."""


@dataclass(frozen=True)
class Interval:
    low: float | None
    high: float | None

    def contains(self, value: float) -> bool:
        if self.low is not None and value < self.low:
            return False
        if self.high is not None and value > self.high:
            return False
        return True


@dataclass(frozen=True)
class Condition:
    sex: str | None
    age_min: int | None
    age_max: int | None
    cycle_phase: str | None

    def matches(
        self, sex: str | None, age: int | None, cycle_phase: str | None
    ) -> bool:
        if self.sex is not None and self.sex != sex:
            return False
        if self.age_min is not None and (age is None or age < self.age_min):
            return False
        if self.age_max is not None and (age is None or age > self.age_max):
            return False
        if self.cycle_phase is not None and self.cycle_phase != cycle_phase:
            return False
        return True


@dataclass(frozen=True)
class Target:
    condition: Condition
    optimal: Interval
    deficient: Interval | None
    excessive: Interval | None


@dataclass(frozen=True)
class Analyte:
    id: str
    name: str
    synonyms: tuple[str, ...]
    units: str
    lab_range: Interval | None
    targets: tuple[Target, ...]
    interpret_with: tuple[str, ...]
    note: str | None


@dataclass(frozen=True)
class Derived:
    id: str
    name: str
    formula: str
    optimal: Interval
    note: str | None


@dataclass(frozen=True)
class References:
    analytes: tuple[Analyte, ...]
    derived: tuple[Derived, ...]
    _index: dict[str, Analyte] = field(default_factory=dict, repr=False, compare=False)

    def analyte(self, analyte_id: str) -> Analyte | None:
        for item in self.analytes:
            if item.id == analyte_id:
                return item
        return None

    def resolve(self, name: str) -> Analyte | None:
        """Найти показатель по идентификатору, названию или синониму."""
        return self._index.get(name.strip().casefold())


def _interval(raw, where: str) -> Interval | None:
    if raw is None:
        return None
    if not isinstance(raw, list) or len(raw) != 2:
        raise ReferenceError(f"{where}: интервал должен быть списком из двух значений")
    low, high = raw
    return Interval(
        low=None if low is None else float(low),
        high=None if high is None else float(high),
    )


def _condition(raw: dict | None) -> Condition:
    raw = raw or {}
    age = raw.get("возраст")
    if age is not None and (not isinstance(age, list) or len(age) != 2):
        raise ReferenceError("условие: 'возраст' должен быть списком [от, до]")
    return Condition(
        sex=raw.get("пол"),
        age_min=None if age is None or age[0] is None else int(age[0]),
        age_max=None if age is None or age[1] is None else int(age[1]),
        cycle_phase=raw.get("фаза_цикла"),
    )


def _target(raw: dict, where: str) -> Target:
    if "оптимум" not in raw:
        raise ReferenceError(f"{where}: у целевого значения нет ключа 'оптимум'")
    optimal = _interval(raw["оптимум"], where)
    assert optimal is not None
    return Target(
        condition=_condition(raw.get("условие")),
        optimal=optimal,
        deficient=_interval(raw.get("дефицит"), where),
        excessive=_interval(raw.get("избыток"), where),
    )


def _analyte(raw: dict) -> Analyte:
    analyte_id = str(raw["id"])
    where = f"показатель {analyte_id!r}"
    targets = tuple(_target(t, where) for t in raw["целевые"])
    if not targets:
        raise ReferenceError(f"{where}: нет ни одного целевого значения")
    return Analyte(
        id=analyte_id,
        name=str(raw["название"]),
        synonyms=tuple(str(s) for s in raw.get("синонимы", ())),
        units=str(raw["единицы"]),
        lab_range=_interval(raw.get("лабораторный_интервал"), where),
        targets=targets,
        interpret_with=tuple(str(s) for s in raw.get("трактовать_с", ())),
        note=raw.get("заметка"),
    )


def _derived(raw: dict) -> Derived:
    where = f"производный {raw['id']!r}"
    optimal = _interval(raw["оптимум"], where)
    assert optimal is not None
    return Derived(
        id=str(raw["id"]),
        name=str(raw["название"]),
        formula=str(raw["формула"]),
        optimal=optimal,
        note=raw.get("заметка"),
    )


def load_references(directory: Path) -> References:
    """Прочитать все YAML-файлы референсов из папки."""
    analytes: list[Analyte] = []
    derived: list[Derived] = []

    for path in sorted(directory.glob("*.yaml")):
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        try:
            analytes.extend(_analyte(a) for a in raw.get("показатели", ()))
            derived.extend(_derived(d) for d in raw.get("производные", ()))
        except (KeyError, TypeError) as exc:
            raise ReferenceError(f"{path.name}: {exc}") from exc

    ids = [a.id for a in analytes] + [d.id for d in derived]
    duplicates = sorted({i for i in ids if ids.count(i) > 1})
    if duplicates:
        raise ReferenceError(f"повторяющиеся идентификаторы показателей: {duplicates}")

    index: dict[str, Analyte] = {}
    for analyte in analytes:
        for key in (analyte.id, analyte.name, *analyte.synonyms):
            index[key.strip().casefold()] = analyte

    return References(analytes=tuple(analytes), derived=tuple(derived), _index=index)
```

- [ ] **Step 4: Запустить тесты**

```bash
uv run pytest tests/knowledge/test_references_model.py -v
```

Ожидается: 7 PASS.

- [ ] **Step 5: Коммит**

```bash
git add src/healthcoach/knowledge/references.py knowledge/references tests/knowledge/test_references_model.py
git commit -m "feat: модель кастомных референсов с условиями по полу, возрасту и фазе цикла"
```

---

### Task 6: Сверка показателя с целевым коридором

**Files:**
- Create: `src/healthcoach/scoring/references.py`
- Create: `tests/scoring/test_reference_matching.py`

**Interfaces:**
- Consumes: `References`, `Analyte`, `Target`, `Interval` из задачи 5
- Produces:
  - `Subject(sex: str, age: int, cycle_phase: str | None)`
  - `Measurement(analyte_id: str, value: float, units: str)`
  - `AnalyteVerdict(analyte_id, title, value, units, status, target, lab_range, note, rule_missing)`
  - `select_target(analyte: Analyte, subject: Subject) -> Target | None`
  - `check_measurements(refs: References, measurements: list[Measurement], subject: Subject) -> list[AnalyteVerdict]`

**Статусы.** `"дефицит"`, `"ниже целевого"`, `"в целевом"`, `"выше целевого"`, `"избыток"`, `"правило не задано"`, `"единицы не сопоставлены"`. Дефицит и избыток проверяются первыми как более тяжёлые.

**Про единицы.** Ядро не конвертирует. Если единицы измерения не совпадают с единицами референса, выносится статус `"единицы не сопоставлены"` и показатель не трактуется. Конвертация — забота модуля `documents` из плана 2, до того как значение доходит сюда.

**Про выбор целевого.** Побеждает первое целевое значение, чьё условие подошло. Порядок в YAML задаёт приоритет: частные условия пишутся выше, запасное без условия — последним.

- [ ] **Step 1: Написать падающие тесты**

Файл `tests/scoring/test_reference_matching.py`:

```python
from pathlib import Path

from healthcoach.knowledge.references import Interval, load_references
from healthcoach.scoring.references import (
    Measurement,
    Subject,
    check_measurements,
    select_target,
)

REFS = Path(__file__).parents[2] / "knowledge" / "references"


def _refs():
    return load_references(REFS)


def test_selects_target_by_sex_and_age():
    ferritin = _refs().analyte("ферритин")
    woman = select_target(ferritin, Subject(sex="ж", age=32, cycle_phase=None))
    assert woman.optimal == Interval(60, 90)

    man = select_target(ferritin, Subject(sex="м", age=32, cycle_phase=None))
    assert man.optimal == Interval(80, 150)


def test_falls_back_to_unconditional_target():
    ferritin = _refs().analyte("ферритин")
    older_woman = select_target(ferritin, Subject(sex="ж", age=64, cycle_phase=None))
    assert older_woman.optimal == Interval(60, 120)


def test_deficit_status():
    verdicts = check_measurements(
        _refs(),
        [Measurement("ферритин", 18, "нг/мл")],
        Subject(sex="ж", age=32, cycle_phase=None),
    )
    (verdict,) = verdicts
    assert verdict.status == "дефицит"
    assert verdict.target == Interval(60, 90)
    assert verdict.lab_range == Interval(10, 120)
    assert verdict.rule_missing is False


def test_below_target_but_not_deficit():
    (verdict,) = check_measurements(
        _refs(),
        [Measurement("ферритин", 45, "нг/мл")],
        Subject(sex="ж", age=32, cycle_phase=None),
    )
    assert verdict.status == "ниже целевого"


def test_within_target():
    (verdict,) = check_measurements(
        _refs(),
        [Measurement("ферритин", 75, "нг/мл")],
        Subject(sex="ж", age=32, cycle_phase=None),
    )
    assert verdict.status == "в целевом"


def test_above_target():
    (verdict,) = check_measurements(
        _refs(),
        [Measurement("ферритин", 130, "нг/мл")],
        Subject(sex="ж", age=32, cycle_phase=None),
    )
    assert verdict.status == "выше целевого"


def test_boundary_values_are_inside_target():
    subject = Subject(sex="ж", age=32, cycle_phase=None)
    low, high = check_measurements(
        _refs(),
        [Measurement("ферритин", 60, "нг/мл"), Measurement("ферритин", 90, "нг/мл")],
        subject,
    )
    assert low.status == "в целевом"
    assert high.status == "в целевом"


def test_unknown_analyte_is_reported_not_dropped():
    (verdict,) = check_measurements(
        _refs(),
        [Measurement("гомоцистеин", 12, "мкмоль/л")],
        Subject(sex="ж", age=32, cycle_phase=None),
    )
    assert verdict.status == "правило не задано"
    assert verdict.rule_missing is True
    assert verdict.value == 12


def test_unit_mismatch_is_not_interpreted():
    (verdict,) = check_measurements(
        _refs(),
        [Measurement("ферритин", 18, "мкг/л")],
        Subject(sex="ж", age=32, cycle_phase=None),
    )
    assert verdict.status == "единицы не сопоставлены"
    assert verdict.rule_missing is True


def test_resolves_analyte_by_synonym():
    (verdict,) = check_measurements(
        _refs(),
        [Measurement("Ferritin", 18, "нг/мл")],
        Subject(sex="ж", age=32, cycle_phase=None),
    )
    assert verdict.analyte_id == "ферритин"
    assert verdict.status == "дефицит"
```

- [ ] **Step 2: Запустить тесты и убедиться, что они падают**

```bash
uv run pytest tests/scoring/test_reference_matching.py -v
```

Ожидается: FAIL с `ModuleNotFoundError: No module named 'healthcoach.scoring.references'`.

- [ ] **Step 3: Реализовать сверку**

Файл `src/healthcoach/scoring/references.py`:

```python
"""Сверка измерений с целевыми коридорами коуча."""

from __future__ import annotations

from dataclasses import dataclass

from healthcoach.knowledge.references import Analyte, Interval, References, Target

STATUS_DEFICIT = "дефицит"
STATUS_BELOW = "ниже целевого"
STATUS_WITHIN = "в целевом"
STATUS_ABOVE = "выше целевого"
STATUS_EXCESS = "избыток"
STATUS_NO_RULE = "правило не задано"
STATUS_UNIT_MISMATCH = "единицы не сопоставлены"


@dataclass(frozen=True)
class Subject:
    sex: str
    age: int
    cycle_phase: str | None = None


@dataclass(frozen=True)
class Measurement:
    analyte_id: str
    value: float
    units: str


@dataclass(frozen=True)
class AnalyteVerdict:
    analyte_id: str
    title: str
    value: float
    units: str
    status: str
    target: Interval | None
    lab_range: Interval | None
    note: str | None
    rule_missing: bool


def select_target(analyte: Analyte, subject: Subject) -> Target | None:
    """Первое целевое значение, чьё условие подошло. Порядок задаёт приоритет."""
    for target in analyte.targets:
        if target.condition.matches(subject.sex, subject.age, subject.cycle_phase):
            return target
    return None


def _status(target: Target, value: float) -> str:
    if target.deficient is not None and target.deficient.contains(value):
        return STATUS_DEFICIT
    if target.excessive is not None and target.excessive.contains(value):
        return STATUS_EXCESS
    if target.optimal.contains(value):
        return STATUS_WITHIN
    if target.optimal.low is not None and value < target.optimal.low:
        return STATUS_BELOW
    return STATUS_ABOVE


def _unresolved(measurement: Measurement, status: str) -> AnalyteVerdict:
    return AnalyteVerdict(
        analyte_id=measurement.analyte_id,
        title=measurement.analyte_id,
        value=measurement.value,
        units=measurement.units,
        status=status,
        target=None,
        lab_range=None,
        note=None,
        rule_missing=True,
    )


def check_measurements(
    references: References, measurements: list[Measurement], subject: Subject
) -> list[AnalyteVerdict]:
    """Сверить измерения с референсами. Ничего не отбрасывать молча."""
    verdicts: list[AnalyteVerdict] = []

    for measurement in measurements:
        analyte = references.resolve(measurement.analyte_id)
        if analyte is None:
            verdicts.append(_unresolved(measurement, STATUS_NO_RULE))
            continue

        if measurement.units.strip().casefold() != analyte.units.strip().casefold():
            verdicts.append(
                AnalyteVerdict(
                    analyte_id=analyte.id,
                    title=analyte.name,
                    value=measurement.value,
                    units=measurement.units,
                    status=STATUS_UNIT_MISMATCH,
                    target=None,
                    lab_range=analyte.lab_range,
                    note=(
                        f"референс задан в единицах {analyte.units!r}, "
                        f"измерение пришло в {measurement.units!r}"
                    ),
                    rule_missing=True,
                )
            )
            continue

        target = select_target(analyte, subject)
        if target is None:
            verdicts.append(
                AnalyteVerdict(
                    analyte_id=analyte.id,
                    title=analyte.name,
                    value=measurement.value,
                    units=measurement.units,
                    status=STATUS_NO_RULE,
                    target=None,
                    lab_range=analyte.lab_range,
                    note="нет целевого значения для этого пола и возраста",
                    rule_missing=True,
                )
            )
            continue

        verdicts.append(
            AnalyteVerdict(
                analyte_id=analyte.id,
                title=analyte.name,
                value=measurement.value,
                units=measurement.units,
                status=_status(target, measurement.value),
                target=target.optimal,
                lab_range=analyte.lab_range,
                note=analyte.note,
                rule_missing=False,
            )
        )

    return verdicts
```

- [ ] **Step 4: Запустить тесты**

```bash
uv run pytest tests/scoring/test_reference_matching.py -v
```

Ожидается: 10 PASS.

- [ ] **Step 5: Коммит**

```bash
git add src/healthcoach/scoring/references.py tests/scoring/test_reference_matching.py
git commit -m "feat: сверка измерений с целевыми коридорами и явные статусы неизвестного"
```

---

### Task 7: Производные показатели

**Files:**
- Create: `src/healthcoach/scoring/derived.py`
- Create: `knowledge/references/derived.yaml`
- Create: `tests/scoring/test_derived.py`

**Interfaces:**
- Consumes: `References`, `Derived`, `Interval` из задачи 5; `Measurement`, `AnalyteVerdict` из задачи 6
- Produces:
  - `evaluate_formula(formula: str, values: dict[str, float]) -> float`
  - `FormulaError(Exception)`
  - `compute_derived(refs: References, measurements: list[Measurement]) -> list[AnalyteVerdict]`

**Про безопасность формул.** Формулы разбираются через `ast` с белым списком узлов: только имена, числа и четыре арифметических действия. Никакого `eval` над произвольной строкой — база знаний это данные, а данные не должны уметь выполнять код. Кириллические идентификаторы в формулах допустимы: `кальций / калий` — корректное выражение Python.

- [ ] **Step 1: Написать падающие тесты**

Файл `tests/scoring/test_derived.py`:

```python
from pathlib import Path

import pytest

from healthcoach.knowledge.references import Interval, load_references
from healthcoach.scoring.derived import FormulaError, compute_derived, evaluate_formula
from healthcoach.scoring.references import Measurement

REFS = Path(__file__).parents[2] / "knowledge" / "references"


def test_evaluate_simple_ratio():
    assert evaluate_formula("кальций / калий", {"кальций": 10.0, "калий": 4.0}) == 2.5


def test_evaluate_respects_arithmetic():
    values = {"a": 2.0, "b": 3.0, "c": 4.0}
    assert evaluate_formula("a + b * c", values) == 14.0


def test_missing_operand_raises():
    with pytest.raises(FormulaError, match="калий"):
        evaluate_formula("кальций / калий", {"кальций": 10.0})


def test_division_by_zero_raises():
    with pytest.raises(FormulaError, match="деление на ноль"):
        evaluate_formula("a / b", {"a": 1.0, "b": 0.0})


def test_function_call_rejected():
    with pytest.raises(FormulaError, match="недопустимая конструкция"):
        evaluate_formula("__import__('os').system('ls')", {})


def test_attribute_access_rejected():
    with pytest.raises(FormulaError, match="недопустимая конструкция"):
        evaluate_formula("a.__class__", {"a": 1.0})


def test_computes_calcium_potassium_ratio():
    (verdict,) = compute_derived(
        load_references(REFS),
        [Measurement("кальций", 10.0, "мг/дл"), Measurement("калий", 4.0, "ммоль/л")],
    )
    assert verdict.analyte_id == "кальций_калий"
    assert verdict.value == 2.5
    assert verdict.status == "в целевом"
    assert verdict.target == Interval(2.0, 4.0)


def test_derived_outside_target():
    (verdict,) = compute_derived(
        load_references(REFS),
        [Measurement("кальций", 10.0, "мг/дл"), Measurement("калий", 2.0, "ммоль/л")],
    )
    assert verdict.value == 5.0
    assert verdict.status == "выше целевого"


def test_derived_skipped_when_operand_absent():
    assert compute_derived(
        load_references(REFS), [Measurement("кальций", 10.0, "мг/дл")]
    ) == []
```

Файл `knowledge/references/derived.yaml`:

```yaml
показатели:
  - id: кальций
    название: Кальций
    синонимы: [Кальций, Calcium, Ca]
    единицы: мг/дл
    целевые:
      - оптимум: [9.2, 10.0]

  - id: калий
    название: Калий
    синонимы: [Калий, Potassium, K]
    единицы: ммоль/л
    целевые:
      - оптимум: [4.0, 4.5]

производные:
  - id: кальций_калий
    название: Соотношение кальций/калий
    формула: кальций / калий
    оптимум: [2.0, 4.0]
    заметка: Смещение вверх — маркер стрессовой нагрузки
```

- [ ] **Step 2: Запустить тесты и убедиться, что они падают**

```bash
uv run pytest tests/scoring/test_derived.py -v
```

Ожидается: FAIL с `ModuleNotFoundError: No module named 'healthcoach.scoring.derived'`.

- [ ] **Step 3: Реализовать вычисление производных**

Файл `src/healthcoach/scoring/derived.py`:

```python
"""Производные показатели: соотношения и индексы."""

from __future__ import annotations

import ast
import operator

from healthcoach.knowledge.references import References
from healthcoach.scoring.references import (
    STATUS_ABOVE,
    STATUS_BELOW,
    STATUS_WITHIN,
    AnalyteVerdict,
    Measurement,
)

_OPS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
}


class FormulaError(Exception):
    """Формулу производного показателя невозможно вычислить."""


def _eval(node: ast.AST, values: dict[str, float]) -> float:
    if isinstance(node, ast.BinOp) and type(node.op) in _OPS:
        left = _eval(node.left, values)
        right = _eval(node.right, values)
        if isinstance(node.op, ast.Div) and right == 0:
            raise FormulaError("деление на ноль")
        return _OPS[type(node.op)](left, right)
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub):
        return -_eval(node.operand, values)
    if isinstance(node, ast.Name):
        if node.id not in values:
            raise FormulaError(f"нет значения для операнда {node.id!r}")
        return values[node.id]
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
        return float(node.value)
    raise FormulaError(f"недопустимая конструкция в формуле: {type(node).__name__}")


def evaluate_formula(formula: str, values: dict[str, float]) -> float:
    """Вычислить формулу. Разрешены только имена, числа и арифметика."""
    try:
        tree = ast.parse(formula, mode="eval")
    except SyntaxError as exc:
        raise FormulaError(f"формула не разобрана: {formula!r}") from exc
    return _eval(tree.body, values)


def compute_derived(
    references: References, measurements: list[Measurement]
) -> list[AnalyteVerdict]:
    """Посчитать производные показатели по имеющимся измерениям.

    Производный, для которого не хватает операндов, пропускается молча —
    это не пробел в данных, а просто несобранный набор анализов.
    """
    values: dict[str, float] = {}
    for measurement in measurements:
        analyte = references.resolve(measurement.analyte_id)
        key = analyte.id if analyte is not None else measurement.analyte_id
        values[key] = measurement.value

    verdicts: list[AnalyteVerdict] = []
    for derived in references.derived:
        try:
            value = evaluate_formula(derived.formula, values)
        except FormulaError:
            continue

        if derived.optimal.contains(value):
            status = STATUS_WITHIN
        elif derived.optimal.low is not None and value < derived.optimal.low:
            status = STATUS_BELOW
        else:
            status = STATUS_ABOVE

        verdicts.append(
            AnalyteVerdict(
                analyte_id=derived.id,
                title=derived.name,
                value=round(value, 4),
                units="",
                status=status,
                target=derived.optimal,
                lab_range=None,
                note=derived.note,
                rule_missing=False,
            )
        )

    return verdicts
```

- [ ] **Step 4: Запустить тесты**

```bash
uv run pytest tests/scoring/test_derived.py -v
```

Ожидается: 9 PASS.

- [ ] **Step 5: Коммит**

```bash
git add src/healthcoach/scoring/derived.py knowledge/references/derived.yaml tests/scoring/test_derived.py
git commit -m "feat: производные показатели с безопасным разбором формул через ast"
```

---

### Task 8: Сборка единого списка находок

**Files:**
- Create: `src/healthcoach/scoring/findings.py`
- Create: `tests/scoring/test_findings.py`

**Interfaces:**
- Consumes: `SubscaleScore` из задачи 4; `AnalyteVerdict`, `Subject`, `Measurement` из задачи 6; `compute_derived` из задачи 7; `Questionnaire` и `References` из задач 2 и 5
- Produces:
  - `Finding(kind, subject_id, title, value, units, status, target, lab_range, note, rule_missing)` где `kind` ∈ `{"показатель", "производный", "опросник"}`
  - `collect_findings(questionnaire, references, answers, measurements, subject) -> list[Finding]`

**Порядок.** Находки сортируются по значимости: сначала требующие внимания (дефицит, избыток, высокая степень), затем умеренные отклонения, затем норма, и в самом конце — то, для чего правило не задано. Это порядок, в котором их удобно читать и коучу, и модели.

- [ ] **Step 1: Написать падающие тесты**

Файл `tests/scoring/test_findings.py`:

```python
from pathlib import Path

from healthcoach.knowledge.questionnaire import (
    Block,
    Question,
    Questionnaire,
    ScaleOption,
    Subscale,
    Threshold,
)
from healthcoach.knowledge.references import load_references
from healthcoach.scoring.findings import collect_findings
from healthcoach.scoring.references import Measurement, Subject

REFS = Path(__file__).parents[2] / "knowledge" / "references"

SCALE = (ScaleOption(0, "нет"), ScaleOption(1, "иногда"), ScaleOption(2, "часто"))


def _questionnaire() -> Questionnaire:
    questions = tuple(
        Question(
            id=f"nadpochechniki.{i}",
            number=i,
            text=f"Симптом {i}",
            scale=None,
            block_scale=SCALE,
        )
        for i in range(1, 4)
    )
    block = Block(
        id="nadpochechniki",
        title="Надпочечники",
        part="клиническая",
        core=True,
        scale=SCALE,
        questions=questions,
        subscales=(
            Subscale(
                id="весь",
                title="Весь блок",
                question_ids=tuple(q.id for q in questions),
                thresholds=(
                    Threshold("низкая", 1, 2, None),
                    Threshold("средняя", 3, 4, None),
                    Threshold("высокая", 5, None, None),
                ),
            ),
        ),
    )
    return Questionnaire(version="1.0", blocks=(block,))


SUBJECT = Subject(sex="ж", age=32, cycle_phase=None)


def test_collects_all_three_kinds():
    findings = collect_findings(
        _questionnaire(),
        load_references(REFS),
        answers={f"nadpochechniki.{i}": 2 for i in range(1, 4)},
        measurements=[
            Measurement("ферритин", 18, "нг/мл"),
            Measurement("кальций", 10.0, "мг/дл"),
            Measurement("калий", 4.0, "ммоль/л"),
        ],
        subject=SUBJECT,
    )
    kinds = {f.kind for f in findings}
    assert kinds == {"показатель", "производный", "опросник"}


def test_questionnaire_finding_carries_degree_as_status():
    findings = collect_findings(
        _questionnaire(),
        load_references(REFS),
        answers={f"nadpochechniki.{i}": 2 for i in range(1, 4)},  # сумма 6
        measurements=[],
        subject=SUBJECT,
    )
    (finding,) = findings
    assert finding.kind == "опросник"
    assert finding.subject_id == "nadpochechniki/весь"
    assert finding.title == "Надпочечники"
    assert finding.status == "высокая"
    assert finding.value == 6


def test_severe_findings_come_first_and_unknown_last():
    findings = collect_findings(
        _questionnaire(),
        load_references(REFS),
        answers={f"nadpochechniki.{i}": 0 for i in range(1, 4)},  # норма
        measurements=[
            Measurement("гомоцистеин", 12, "мкмоль/л"),  # правило не задано
            Measurement("ферритин", 18, "нг/мл"),  # дефицит
            Measurement("кальций", 9.5, "мг/дл"),  # в целевом
            Measurement("калий", 4.2, "ммоль/л"),  # в целевом
        ],
        subject=SUBJECT,
    )
    statuses = [f.status for f in findings]
    assert statuses[0] == "дефицит"
    assert statuses[-1] == "правило не задано"
    assert "в пределах нормы" in statuses  # находка опросника не потерялась


def test_questionnaire_without_degree_still_reported():
    findings = collect_findings(
        _questionnaire(),
        load_references(REFS),
        answers={"nadpochechniki.1": 0, "nadpochechniki.2": 0, "nadpochechniki.3": 0},
        measurements=[],
        subject=SUBJECT,
    )
    (finding,) = findings
    assert finding.status == "в пределах нормы"
    assert finding.value == 0
```

- [ ] **Step 2: Запустить тесты и убедиться, что они падают**

```bash
uv run pytest tests/scoring/test_findings.py -v
```

Ожидается: FAIL с `ModuleNotFoundError: No module named 'healthcoach.scoring.findings'`.

- [ ] **Step 3: Реализовать сборку находок**

Файл `src/healthcoach/scoring/findings.py`:

```python
"""Единый список находок — вход для интерпретации."""

from __future__ import annotations

from dataclasses import dataclass

from healthcoach.knowledge.questionnaire import Questionnaire
from healthcoach.knowledge.references import Interval, References
from healthcoach.scoring.derived import compute_derived
from healthcoach.scoring.questionnaire import Answers, score_questionnaire
from healthcoach.scoring.references import (
    STATUS_ABOVE,
    STATUS_BELOW,
    STATUS_DEFICIT,
    STATUS_EXCESS,
    STATUS_NO_RULE,
    STATUS_UNIT_MISMATCH,
    STATUS_WITHIN,
    AnalyteVerdict,
    Measurement,
    Subject,
    check_measurements,
)

KIND_ANALYTE = "показатель"
KIND_DERIVED = "производный"
KIND_QUESTIONNAIRE = "опросник"

STATUS_NORMAL = "в пределах нормы"

_SEVERITY = {
    STATUS_DEFICIT: 0,
    STATUS_EXCESS: 0,
    "высокая": 0,
    "тяжёлая": 0,
    "очень тяжёлая": 0,
    STATUS_BELOW: 1,
    STATUS_ABOVE: 1,
    "средняя": 1,
    "умеренная": 1,
    "низкая": 2,
    STATUS_WITHIN: 3,
    STATUS_NORMAL: 3,
    STATUS_UNIT_MISMATCH: 4,
    STATUS_NO_RULE: 5,
}


@dataclass(frozen=True)
class Finding:
    kind: str
    subject_id: str
    title: str
    value: float
    units: str
    status: str
    target: Interval | None
    lab_range: Interval | None
    note: str | None
    rule_missing: bool


def _from_verdict(verdict: AnalyteVerdict, kind: str) -> Finding:
    return Finding(
        kind=kind,
        subject_id=verdict.analyte_id,
        title=verdict.title,
        value=verdict.value,
        units=verdict.units,
        status=verdict.status,
        target=verdict.target,
        lab_range=verdict.lab_range,
        note=verdict.note,
        rule_missing=verdict.rule_missing,
    )


def collect_findings(
    questionnaire: Questionnaire,
    references: References,
    answers: Answers,
    measurements: list[Measurement],
    subject: Subject,
) -> list[Finding]:
    """Собрать находки из опросника, показателей и производных в один список."""
    findings: list[Finding] = []

    for scored in score_questionnaire(questionnaire, answers, subject.sex):
        title = (
            scored.block_title
            if scored.subscale_id == "весь"
            else f"{scored.block_title} — {scored.subscale_title}"
        )
        findings.append(
            Finding(
                kind=KIND_QUESTIONNAIRE,
                subject_id=f"{scored.block_id}/{scored.subscale_id}",
                title=title,
                value=scored.score,
                units="баллов",
                status=scored.degree or STATUS_NORMAL,
                target=None,
                lab_range=None,
                note=(
                    None
                    if scored.answered == scored.total
                    else f"отвечено {scored.answered} из {scored.total} вопросов"
                ),
                rule_missing=False,
            )
        )

    for verdict in check_measurements(references, measurements, subject):
        findings.append(_from_verdict(verdict, KIND_ANALYTE))

    for verdict in compute_derived(references, measurements):
        findings.append(_from_verdict(verdict, KIND_DERIVED))

    findings.sort(key=lambda f: (_SEVERITY.get(f.status, 3), f.kind, f.title))
    return findings
```

- [ ] **Step 4: Запустить тесты**

```bash
uv run pytest tests/scoring/test_findings.py -v
```

Ожидается: 4 PASS.

- [ ] **Step 5: Прогнать всё ядро целиком**

```bash
uv run pytest -v
```

Ожидается: все тесты проходят.

- [ ] **Step 6: Коммит**

```bash
git add src/healthcoach/scoring/findings.py tests/scoring/test_findings.py
git commit -m "feat: единый список находок с сортировкой по значимости"
```

---

### Task 9: Эталонный набор по ключу опросника

**Files:**
- Create: `knowledge/questionnaire.yaml`
- Create: `tests/knowledge/test_real_questionnaire.py`

**Interfaces:**
- Consumes: `load_questionnaire`, `validate_questionnaire`, `score_questionnaire`
- Produces: `knowledge/questionnaire.yaml` — доведённая вручную спецификация реального опросника; проверенная эталонными тестами

**Что делает эта задача.** Черновик из задачи 3 доводится руками до полного YAML: проставляются `part` и `core`, переносятся шкалы из колонки H, а с листа «РЕЗУЛЬТАТ КЛЮЧ» переносятся подгруппы и пороги. Дальше валидатор из задачи 3 прогоняется по реальному файлу — он обязан поймать оборванные пороги Candida. Найденное обсуждается с коучем и фиксируется в YAML с комментарием о расхождении с исходником.

- [ ] **Step 1: Довести черновик до полного YAML**

```bash
cp knowledge/questionnaire.draft.yaml knowledge/questionnaire.yaml
```

Дальше вручную по каждому блоку:

1. Заменить `part: ПРОВЕРИТЬ` на `организационная`, `клиническая` или `дополнительная` — соответственно секциям `ОРГАНИЗАЦИОННАЯ ЧАСТЬ`, `КЛИНИЧЕСКАЯ ЧАСТЬ` и `ДОПОЛНИТЕЛЬНЫЕ ОПРОСНИКИ` в исходном листе.
2. Заменить `core: ПРОВЕРИТЬ` на `true` для организационной и клинической частей, `false` для дополнительных опросников.
3. Заполнить `scale` из закомментированной строки с содержимым колонки H.
4. Добавить в каждый блок секцию `subscales` с порогами из листа `РЕЗУЛЬТАТ КЛЮЧ`. Для блоков без подгрупп — одна подгруппа `id: весь`.

Для блоков с подгруппами на листе ключа они уже размечены: «Питание» (А. Часть 1, Б. Часть 2), «Эссенциальные нутриенты» (А, Б), «Женское здоровье» (А и Б репродуктивный период, В менопауза), «Системное воспаление» (А, Б), QEESI (А—Д), «Candida» (А—В), DASS (депрессия, тревожность, стресс).

Для QEESI и Candida пороги задаются дважды, с `sex: м` и `sex: ж`.

- [ ] **Step 2: Написать тест, который валидирует реальный файл**

Файл `tests/knowledge/test_real_questionnaire.py`:

```python
from pathlib import Path

from healthcoach.knowledge.questionnaire import load_questionnaire
from healthcoach.knowledge.validation import validate_questionnaire
from healthcoach.scoring.questionnaire import score_questionnaire

SPEC = Path(__file__).parents[2] / "knowledge" / "questionnaire.yaml"


def test_real_questionnaire_loads():
    q = load_questionnaire(SPEC)
    assert len(q.blocks) >= 20


def test_core_and_optional_blocks_present():
    q = load_questionnaire(SPEC)
    assert any(b.core for b in q.blocks)
    assert any(not b.core for b in q.blocks)
    parts = {b.part for b in q.blocks}
    assert parts == {"организационная", "клиническая", "дополнительная"}


def test_every_question_belongs_to_a_subscale():
    q = load_questionnaire(SPEC)
    for block in q.blocks:
        covered = {qid for sub in block.subscales for qid in sub.question_ids}
        missing = {question.id for question in block.questions} - covered
        assert not missing, f"блок {block.id}: вопросы вне подгрупп: {sorted(missing)}"


def test_no_threshold_problems_remain():
    """Пороги приведены в порядок; расхождения с исходником зафиксированы в YAML."""
    problems = validate_questionnaire(load_questionnaire(SPEC))
    assert problems == [], "\n".join(f"{p.where}: {p.message}" for p in problems)


def test_gastro_block_reference_case():
    """Эталон по листу ключа: Желудок и П/Ж, сумма 12 — средняя степень."""
    q = load_questionnaire(SPEC)
    block = q.block("zheludok_i_p_zh")
    answers: dict[str, int] = {}
    remaining = 12
    for question in block.questions:
        top = max(o.score for o in question.options())
        take = min(top, remaining)
        answers[question.id] = take
        remaining -= take
    assert remaining == 0

    scored = {s.subscale_id: s for s in score_questionnaire(q, answers, sex="ж")}
    assert scored["весь"].score == 12
    assert scored["весь"].degree == "средняя"
```

- [ ] **Step 3: Запустить тесты и разобрать падения**

```bash
uv run pytest tests/knowledge/test_real_questionnaire.py -v
```

Ожидается на первом прогоне: падение `test_no_threshold_problems_remain` с сообщением про верхнюю границу у блока Candida. Это ожидаемо — валидатор нашёл опечатку в исходном xlsx.

Действие: показать коучу найденные расхождения, согласовать правильные пороги (для Candida по смыслу это `>140` для мужчин и `>180` для женщин), внести в `knowledge/questionnaire.yaml` и добавить рядом комментарий:

```yaml
        # Расхождение с исходным xlsx: там верхняя степень записана как '<140',
        # что оставляет баллы выше 140 без степени. Согласовано с коучем: '>140'.
```

Если идентификатор блока `zheludok_i_p_zh` в вашем файле получился другим — поправить его в тесте на фактический.

- [ ] **Step 4: Запустить тесты повторно**

```bash
uv run pytest tests/knowledge/test_real_questionnaire.py -v
```

Ожидается: 5 PASS.

- [ ] **Step 5: Прогнать весь набор**

```bash
uv run pytest -v
```

Ожидается: всё зелёное.

- [ ] **Step 6: Коммит**

```bash
git add knowledge/questionnaire.yaml tests/knowledge/test_real_questionnaire.py
git commit -m "feat: спецификация реального опросника с эталонными тестами по ключу"
```

- [ ] **Step 7: Убрать черновик импорта**

```bash
rm -f knowledge/questionnaire.draft.yaml
```

Черновик больше не нужен: источник правды — `knowledge/questionnaire.yaml`.

---

### Task 10: Справочник специальностей и врачей

**Files:**
- Create: `src/healthcoach/knowledge/specialists.py`
- Create: `knowledge/specialists.yaml`
- Create: `tests/knowledge/test_specialists.py`

**Interfaces:**
- Consumes: ничего
- Produces:
  - `Doctor(name: str, contacts: str, format: str, city: str | None, note: str | None)`
  - `Specialty(id: str, name: str, when: str, doctors: tuple[Doctor, ...])`
  - `Specialists(specialties: tuple[Specialty, ...])`
  - `Specialists.specialty(specialty_id: str) -> Specialty | None`
  - `Specialists.public_view() -> tuple[dict[str, str], ...]` — специальности **без врачей**
  - `load_specialists(path: Path) -> Specialists`
  - `SpecialistsError(Exception)`

**Ключевое решение.** Контакты врачей не должны попадать ни в клиентский PDF, ни в пакет, уходящий модели. Вместо того чтобы полагаться на дисциплину в вызывающем коде, граница закреплена типом: `public_view()` возвращает только идентификатор, название и описание «когда направлять». Всё, что уходит наружу, берётся из этого метода, а полный объект остаётся на экране коуча. Тест это проверяет.

Наполнение справочника — разовый ручной перенос из телеграм-чата: Telegram Desktop → Экспорт истории чата → JSON, затем содержимое раскладывается по этому YAML.

- [ ] **Step 1: Написать падающие тесты**

Файл `tests/knowledge/test_specialists.py`:

```python
from pathlib import Path

import pytest

from healthcoach.knowledge.specialists import SpecialistsError, load_specialists

SPEC = Path(__file__).parents[2] / "knowledge" / "specialists.yaml"


def test_loads_specialties():
    s = load_specialists(SPEC)
    endo = s.specialty("эндокринолог")
    assert endo is not None
    assert endo.name == "Эндокринолог"
    assert "щитовидн" in endo.when.lower()


def test_doctors_attached_to_specialty():
    s = load_specialists(SPEC)
    endo = s.specialty("эндокринолог")
    assert len(endo.doctors) >= 1
    assert endo.doctors[0].contacts


def test_public_view_omits_doctors_entirely():
    s = load_specialists(SPEC)
    public = s.public_view()

    assert public
    for entry in public:
        assert set(entry) == {"id", "название", "когда"}

    serialized = repr(public)
    for specialty in s.specialties:
        for doctor in specialty.doctors:
            assert doctor.name not in serialized
            assert doctor.contacts not in serialized


def test_unknown_specialty_returns_none():
    assert load_specialists(SPEC).specialty("нет_такой") is None


def test_duplicate_specialty_id_raises(tmp_path):
    path = tmp_path / "s.yaml"
    path.write_text(
        "специальности:\n"
        "  - id: дубль\n"
        "    название: Дубль\n"
        "    когда: Всегда\n"
        "  - id: дубль\n"
        "    название: Дубль ещё раз\n"
        "    когда: Всегда\n",
        encoding="utf-8",
    )
    with pytest.raises(SpecialistsError, match="дубль"):
        load_specialists(path)


def test_specialty_without_when_raises(tmp_path):
    path = tmp_path / "s.yaml"
    path.write_text(
        "специальности:\n  - id: x\n    название: Икс\n",
        encoding="utf-8",
    )
    with pytest.raises(SpecialistsError, match="когда"):
        load_specialists(path)
```

Файл `knowledge/specialists.yaml` — стартовое наполнение, дополняется коучем:

```yaml
специальности:
  - id: эндокринолог
    название: Эндокринолог
    когда: >-
      Отклонения щитовидной железы, углеводного обмена, надпочечников;
      подозрение на инсулинорезистентность.
    врачи:
      - имя: Заполнить из телеграм-чата
        контакты: "@nickname"
        формат: онлайн
        город: null
        заметка: Заглушка стартового наполнения — заменить реальными данными

  - id: гастроэнтеролог
    название: Гастроэнтеролог
    когда: >-
      Устойчивые жалобы по блокам желудка, тонкого и толстого кишечника,
      печени и желчного пузыря.
    врачи: []

  - id: гинеколог
    название: Гинеколог
    когда: >-
      Отклонения по блоку женского здоровья, нарушения цикла,
      вопросы репродуктивного периода и менопаузы.
    врачи: []

  - id: terapevt
    название: Терапевт
    когда: >-
      Общая картина без явной системной привязки; нужна маршрутизация
      и базовое обследование.
    врачи: []
```

- [ ] **Step 2: Запустить тесты и убедиться, что они падают**

```bash
uv run pytest tests/knowledge/test_specialists.py -v
```

Ожидается: FAIL с `ModuleNotFoundError: No module named 'healthcoach.knowledge.specialists'`.

- [ ] **Step 3: Реализовать справочник**

Файл `src/healthcoach/knowledge/specialists.py`:

```python
"""Справочник специальностей и доверенных врачей коуча.

Контакты врачей никогда не покидают экран коуча: наружу — в клиентский отчёт
и в пакет для языковой модели — отдаётся только public_view().
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml


class SpecialistsError(Exception):
    """Справочник специалистов некорректен."""


@dataclass(frozen=True)
class Doctor:
    name: str
    contacts: str
    format: str
    city: str | None
    note: str | None


@dataclass(frozen=True)
class Specialty:
    id: str
    name: str
    when: str
    doctors: tuple[Doctor, ...]


@dataclass(frozen=True)
class Specialists:
    specialties: tuple[Specialty, ...]

    def specialty(self, specialty_id: str) -> Specialty | None:
        for item in self.specialties:
            if item.id == specialty_id:
                return item
        return None

    def public_view(self) -> tuple[dict[str, str], ...]:
        """Специальности без врачей — безопасно отдавать наружу."""
        return tuple(
            {"id": s.id, "название": s.name, "когда": s.when} for s in self.specialties
        )


def _doctor(raw: dict, where: str) -> Doctor:
    for key in ("имя", "контакты", "формат"):
        if key not in raw:
            raise SpecialistsError(f"{where}: у врача нет ключа {key!r}")
    return Doctor(
        name=str(raw["имя"]),
        contacts=str(raw["контакты"]),
        format=str(raw["формат"]),
        city=raw.get("город"),
        note=raw.get("заметка"),
    )


def _specialty(raw: dict) -> Specialty:
    if "id" not in raw:
        raise SpecialistsError("у специальности нет ключа 'id'")
    where = f"специальность {raw['id']!r}"
    for key in ("название", "когда"):
        if key not in raw:
            raise SpecialistsError(f"{where}: нет ключа {key!r}")
    return Specialty(
        id=str(raw["id"]),
        name=str(raw["название"]),
        when=str(raw["когда"]).strip(),
        doctors=tuple(_doctor(d, where) for d in (raw.get("врачи") or ())),
    )


def load_specialists(path: Path) -> Specialists:
    """Прочитать справочник специальностей из YAML."""
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if "специальности" not in raw:
        raise SpecialistsError(f"{path}: нет ключа 'специальности'")

    specialties = tuple(_specialty(s) for s in raw["специальности"])
    ids = [s.id for s in specialties]
    duplicates = sorted({i for i in ids if ids.count(i) > 1})
    if duplicates:
        raise SpecialistsError(f"повторяющиеся идентификаторы специальностей: {duplicates}")

    return Specialists(specialties=specialties)
```

- [ ] **Step 4: Запустить тесты**

```bash
uv run pytest tests/knowledge/test_specialists.py -v
```

Ожидается: 6 PASS.

- [ ] **Step 5: Прогнать весь набор**

```bash
uv run pytest -v
```

Ожидается: всё зелёное.

- [ ] **Step 6: Коммит**

```bash
git add src/healthcoach/knowledge/specialists.py knowledge/specialists.yaml tests/knowledge/test_specialists.py
git commit -m "feat: справочник специальностей с типовой границей между публичной и приватной частью"
```

---

## Что дальше

План 1 закрывает раздел 6 спецификации целиком, кроме слоя 2 (`knowledge/context.md`):
это проза, которую пишет коуч, и она создаётся в плане 3, где впервые используется —
на шаге интерпретации. Загружать её кодом не требуется, файл читается как есть.

Также закрыты пункты раздела 13 про скоринг опросника, референсы и производные показатели.
Тесты на парсинг PDF и конвертацию единиц относятся к плану 2, тест на обезличивание — к плану 3.

**План 2 — приём данных.** Генератор автономного HTML-опросника с сохранением прогресса, импорт присланных ответов, чтение PDF через pdfplumber, адаптер `OCREngine`, нормализация названий показателей и конвертация единиц, хранилище SQLite и экран сверки цифр.

**План 3 — интерпретация и отчёт.** Обезличивание с обязательным тестом на утечку, адаптер `LLMProvider` поверх `claude -p`, сборка черновика с привязкой к находкам, экран правки и утверждения, HTML-шаблон и печать PDF через WeasyPrint, графики динамики, портфолио клиента.

---

Plan complete and saved to `docs/superpowers/plans/2026-08-08-healthcoach-core.md`. Two execution options:

**1. Subagent-Driven (recommended)** — свежий субагент на задачу, ревью между задачами, быстрая итерация

**2. Inline Execution** — исполнение задач в текущей сессии через executing-plans, пакетами с контрольными точками
