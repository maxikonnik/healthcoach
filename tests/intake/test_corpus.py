"""Табло качества распознавания: сборка отчёта и порог по реальному корпусу.

Сборка отчёта проверяется на выдуманном крошечном корпусе — без обращения
к samples/, работает всегда. Порог по реальному корпусу — отдельным тестом
с маркером `samples`, пропускается, если папки нет.
"""

from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

import pytest

from healthcoach.intake.corpus import (
    REFUSAL_FORMAT,
    REFUSAL_HEADER_COLUMNS,
    REFUSAL_HEADER_MISSING,
    CorpusReport,
    FileOutcome,
    format_report,
    scan_corpus,
)
from healthcoach.intake.ocr import OCREngine, TextLine
from healthcoach.knowledge.references import load_references

_HEADER = (
    TextLine("Показатель", x=0.10, y=0.90),
    TextLine("Результат", x=0.40, y=0.90),
    TextLine("Ед.", x=0.65, y=0.90),
    TextLine("Референсные", x=0.85, y=0.90),
)


def _row(name: str, value: str, units: str, reference: str, y: float) -> list[TextLine]:
    return [
        TextLine(name, x=0.10, y=y),
        TextLine(value, x=0.40, y=y),
        TextLine(units, x=0.65, y=y),
        TextLine(reference, x=0.85, y=y),
    ]


class _ScriptedEngine:
    """Движок распознавания, отдающий заранее известный ответ по имени файла."""

    def __init__(self, by_name: dict[str, list[TextLine]]) -> None:
        self._by_name = by_name

    def read(self, path: Path) -> list[TextLine]:
        return self._by_name[path.name]


@pytest.fixture
def references(tmp_path):
    directory = tmp_path / "knowledge-references"
    directory.mkdir()
    (directory / "glucose.yaml").write_text(
        """\
показатели:
  - id: глюкоза
    название: Глюкоза
    синонимы: [Глюкоза]
    единицы: ммоль/л
    целевые:
      - оптимум: [3.3, 5.5]
""",
        encoding="utf-8",
    )
    return load_references(directory)


@pytest.fixture
def corpus_dir(tmp_path):
    directory = tmp_path / "corpus"
    directory.mkdir()
    return directory


def test_scan_corpus_counts_accepted_refused_rows_and_resolution(corpus_dir, references):
    (corpus_dir / "01.jpg").write_bytes(b"\xff\xd8\xff")

    nested = corpus_dir / "клиент"
    nested.mkdir()
    (nested / "02.jpg").write_bytes(b"\xff\xd8\xff")

    (corpus_dir / "03.jpg").write_bytes(b"\xff\xd8\xff")
    (corpus_dir / "заметки.txt").write_text("не документ", encoding="utf-8")
    (corpus_dir / "~$черновик.xlsx").write_bytes(b"")
    (corpus_dir / ".DS_Store").write_bytes(b"")

    engine = _ScriptedEngine(
        {
            "01.jpg": [*_HEADER, *_row("Глюкоза", "5.5", "ммоль/л", "3.3-5.5", 0.80)],
            "02.jpg": [
                *_HEADER,
                *_row("Выдуманный показатель", "10", "ед", "1-2", 0.80),
            ],
            "03.jpg": [TextLine("просто текст без шапки", x=0.10, y=0.50)],
        }
    )

    report = scan_corpus(corpus_dir, references, engine)

    assert report.accepted == 2
    assert report.refused_by == {REFUSAL_FORMAT: 1, REFUSAL_HEADER_MISSING: 1}
    assert report.rows == 2
    assert report.resolved == 1
    assert report.unresolved_names == {"Выдуманный показатель": 1}

    # Файлы нумеруются в порядке обхода: 01.jpg, 03.jpg, заметки.txt,
    # клиент/02.jpg. Замок Office и .DS_Store номера не получают вовсе.
    assert [outcome.label for outcome in report.outcomes] == ["01", "02", "03", "04"]

    assert report.outcomes[0] == FileOutcome(
        label="01", accepted=True, refusal=None, rows=1, unparsed=0, resolved=1
    )
    assert report.outcomes[3] == FileOutcome(
        label="04", accepted=True, refusal=None, rows=1, unparsed=0, resolved=0
    )

    refused_outcome = report.outcomes[2]
    assert refused_outcome.accepted is False
    assert refused_outcome.refusal == REFUSAL_FORMAT


def test_report_identifies_files_by_number_not_by_name(corpus_dir, references):
    """В именах файлов корпуса стоят фамилии пациентов и номер карты.

    Отчёт табло описан в README как безопасный к показу; имя файла делало
    это неправдой. Номер в порядке обхода стоит столько же, а фамилии не
    несёт — найти сам файл коуч может по номеру
    (`python -m healthcoach.intake.corpus 1`).
    """
    (corpus_dir / "Тестова М. А. 1975 карта 12345 ОАК.jpg").write_bytes(b"\xff\xd8\xff")
    engine = _ScriptedEngine(
        {
            "Тестова М. А. 1975 карта 12345 ОАК.jpg": [
                *_HEADER,
                *_row("Глюкоза", "5.5", "ммоль/л", "3.3-5.5", 0.80),
            ]
        }
    )

    report = scan_corpus(corpus_dir, references, engine)

    assert [outcome.label for outcome in report.outcomes] == ["01"]
    text = format_report(report)
    assert "Тестова" not in text
    assert "12345" not in text
    assert "01" in text


def test_scan_corpus_skips_office_locks_and_hidden_cache_directories(corpus_dir, references):
    """Замки Office и точечные служебные файлы/папки — не документы."""
    (corpus_dir / "~$temp.xlsx").write_bytes(b"")
    (corpus_dir / ".DS_Store").write_bytes(b"")
    hidden = corpus_dir / ".ocr-cache"
    hidden.mkdir()
    (hidden / "01.jpg.json").write_text("[]", encoding="utf-8")

    report = scan_corpus(corpus_dir, references, _ScriptedEngine({}))

    assert report.outcomes == ()
    assert report.accepted == 0
    assert report.refused_by == {}


def test_scan_corpus_on_empty_folder_is_an_empty_report(corpus_dir, references):
    report = scan_corpus(corpus_dir, references, _ScriptedEngine({}))
    assert report == CorpusReport(
        outcomes=(), accepted=0, refused_by={}, rows=0, resolved=0, unresolved_names={}
    )


def _header_only(*words: str) -> list[TextLine]:
    """Документ из одной строки-шапки: колонки по возрастанию x."""
    return [
        TextLine(word, x=0.10 + 0.15 * i, y=0.90) for i, word in enumerate(words)
    ]


def test_header_refusals_are_classified_by_their_real_messages(corpus_dir, references):
    """Класс «шапка-колонки» ставится по настоящему тексту отказа.

    Раньше эту подстроку не проверял ни один тест: переименуй формулировку
    в lab_table.py — и все отказы по шапке молча съезжали в «иное», а табло
    показывало бы, что колонки распознаются прекрасно. Здесь отказ рождается
    там же, где в жизни, — из разбора настоящей плохой шапки, и до классов
    доходит своим ходом, через DocumentError.
    """
    (corpus_dir / "10.jpg").write_bytes(b"\xff\xd8\xff")
    (corpus_dir / "11.jpg").write_bytes(b"\xff\xd8\xff")

    engine = _ScriptedEngine(
        {
            # Слово «Норма» словарю неизвестно — колонку опознать нечем.
            "10.jpg": _header_only("Показатель", "Результат", "Ед.", "Норма"),
            # «Комментарий» опознан, но стоит не последним — свободный
            # текст сдвинул бы все колонки за собой.
            "11.jpg": _header_only(
                "Показатель", "Результат", "Комментарий", "Ед.", "Референсные"
            ),
        }
    )

    report = scan_corpus(corpus_dir, references, engine)

    assert report.refused_by == {REFUSAL_HEADER_COLUMNS: 2}
    assert all(o.refusal == REFUSAL_HEADER_COLUMNS for o in report.outcomes)


def test_format_report_prints_numbers_counts_and_indicator_names_only():
    """Отчёт для человека — только номера файлов, числа и названия показателей."""
    report = CorpusReport(
        outcomes=(
            FileOutcome(
                label="01", accepted=True, refusal=None, rows=2, unparsed=1, resolved=1
            ),
            FileOutcome(
                label="02",
                accepted=False,
                refusal=REFUSAL_FORMAT,
                rows=0,
                unparsed=0,
                resolved=0,
            ),
        ),
        accepted=1,
        refused_by={REFUSAL_FORMAT: 1},
        rows=2,
        resolved=1,
        unresolved_names={"Выдуманный показатель": 1},
    )

    text = format_report(report)

    assert "01" in text
    assert "02" in text
    assert REFUSAL_FORMAT in text
    assert "принято" in text
    assert "1 из 2" in text
    assert "Выдуманный показатель" in text


class _CachingEngine:
    """Кэширует распознавание фотографии на диске, внутри самой папки корпуса.

    Полный прогон OCR по фотографиям samples/ — минуты живого распознавания
    (см. Task 1 плана); гонять их заново при каждом прогоне обычного набора
    тестов неразумно. Кэш живёт в `samples/.ocr-cache/` — она сама целиком
    вне репозитория, как и весь `samples/`, и по чувствительности не хуже
    самих фотографий, из которых посчитана. Ключ — имя файла и его
    mtime/размер: замена фотографии на диске обесценивает старую запись
    сама собой, без явной инвалидации.
    """

    def __init__(self, inner: OCREngine, cache_dir: Path) -> None:
        self._inner = inner
        self._cache_dir = cache_dir
        self._cache_dir.mkdir(exist_ok=True)

    def read(self, path: Path) -> list[TextLine]:
        stat = path.stat()
        cache_file = (
            self._cache_dir / f"{path.name}.{stat.st_mtime_ns}.{stat.st_size}.json"
        )
        if cache_file.is_file():
            raw = json.loads(cache_file.read_text(encoding="utf-8"))
            return [TextLine(**item) for item in raw]
        observations = self._inner.read(path)
        cache_file.write_text(
            json.dumps([asdict(o) for o in observations], ensure_ascii=False),
            encoding="utf-8",
        )
        return observations


@pytest.mark.samples
def test_corpus_scoreboard_meets_baseline(samples_dir):
    """Прогон по настоящему корпусу не хуже сегодняшних чисел.

    Пороги — замер из docs/superpowers/plans/2026-08-13-healthcoach-recognition.md
    на начало работы над планом (77 файлов в samples/). Каждая следующая
    задача плана поднимает эти числа по факту нового прогона; понижать их
    нельзя без отдельного решения (см. «Тест» в Task 1 плана).
    """
    from healthcoach.intake.ocr import AppleVisionEngine

    # Task 2 подняла порог: словарь шапки принял «Единицы», «Ед.изм.» без
    # пробела, «Реф.», «пределы», «значения» и роль «прочее» для
    # «Комментарий»/«Предыдущий»; отказ «шапка-колонки» упал с 14 до 3
    # (остались три OCR-опечатки в самой шапке — задача 6).
    #
    # Task 3 отсеяла служебные строки («Страница», «№ заказа», «Адрес
    # пациента», «ПЕЧАТЬ:», заголовки триместров, «Дата рождения»):
    # accepted и resolved не изменились (служебная строка никогда не была
    # показателем — она либо ложно становилась строкой измерения, либо
    # засоряла unparsed), а нераспознанных строк стало 638 вместо 755,
    # различных названий — 293 вместо 309. Пороги здесь ниже не подняты,
    # потому что план меряет accepted/resolved, а не размер unparsed.
    #
    # Task 5 завела справочники показателей по корпусу (69 показателей в
    # шести файлах, без целевых коридоров): сопоставлено 505 строк из 656
    # вместо 18. accepted не изменилось — база знаний решает, узнан ли
    # показатель, а не примут ли документ.
    min_accepted = 40
    min_resolved = 505

    knowledge_dir = Path(__file__).parents[2] / "knowledge"
    references = load_references(knowledge_dir / "references")
    engine = _CachingEngine(AppleVisionEngine(), samples_dir / ".ocr-cache")
    report = scan_corpus(samples_dir, references, engine)

    assert report.accepted >= min_accepted, (
        f"принято {report.accepted} документов из {len(report.outcomes)}, "
        f"нужно не меньше {min_accepted}"
    )
    assert report.resolved >= min_resolved, (
        f"сопоставлено {report.resolved} строк из {report.rows}, "
        f"нужно не меньше {min_resolved}"
    )
