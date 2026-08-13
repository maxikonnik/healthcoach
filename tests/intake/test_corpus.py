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
    REFUSAL_EMPTY_DOCUMENT,
    REFUSAL_FORMAT,
    REFUSAL_HEADER_COLUMNS,
    REFUSAL_NOT_A_TABLE,
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
    assert report.refused_by == {REFUSAL_FORMAT: 1, REFUSAL_NOT_A_TABLE: 1}
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


def test_scan_corpus_counts_rows_whose_units_agree_with_the_resolved_analyte(
    corpus_dir, references
):
    """`resolved` говорит, что строка с чем-то сопоставилась, но не с чем.

    На ревью уточнённая попытка в resolve.py была выключена — «Лимфоциты,
    абсолютное количество» снова находило процентный показатель, — и табло
    показало ровно те же числа: неверное сопоставление ему невидимо, а
    значит, каждое число в журнале мерило меньше, чем обещало.

    Единицы — независимая проверка того же события: строка, ушедшая к
    чужому показателю, почти всегда расходится с ним в единицах. Здесь обе
    строки — глюкоза, обе сопоставлены, но у второй единицы бланка
    показателю не принадлежат, и она в новый счёт не идёт.
    """
    (corpus_dir / "01.jpg").write_bytes(b"\xff\xd8\xff")

    engine = _ScriptedEngine(
        {
            "01.jpg": [
                *_HEADER,
                *_row("Глюкоза", "5.5", "ммоль/л", "3.3-5.5", 0.80),
                *_row("Глюкоза", "99", "мг/дл", "3.3-5.5", 0.70),
            ]
        }
    )

    report = scan_corpus(corpus_dir, references, engine)

    assert report.rows == 2
    assert report.resolved == 2
    assert report.units_agreed == 1


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


def test_not_a_table_and_empty_document_refusals_are_classified_by_their_real_messages(
    corpus_dir, references
):
    """Task 4 плана расколола прежний класс «шапка-не-найдена» на два:
    связный текст без шапки таблицы (УЗИ, протокол) и документ вовсе без
    текста (пустой PDF, нечитаемое фото). Ту же ловушку, что и тест выше
    про «шапка-колонки», здесь можно повторить дословно: переименуй
    формулировку в lab_table.py — и оба класса молча съедут в «иное»,
    поэтому классификация проверяется на настоящем отказе, полученном через
    DocumentError, а не на выдуманной строке.
    """
    (corpus_dir / "12.jpg").write_bytes(b"\xff\xd8\xff")
    (corpus_dir / "13.jpg").write_bytes(b"\xff\xd8\xff")

    engine = _ScriptedEngine(
        {
            # Связный текст — заключение УЗИ, а не таблица показателей.
            "12.jpg": [
                TextLine("Заключение: без патологии", x=0.10, y=0.90),
                TextLine("Печень не увеличена", x=0.10, y=0.80),
            ],
            # Распознавание не вернуло ни одного наблюдения.
            "13.jpg": [],
        }
    )

    report = scan_corpus(corpus_dir, references, engine)

    assert report.refused_by == {
        REFUSAL_NOT_A_TABLE: 1,
        REFUSAL_EMPTY_DOCUMENT: 1,
    }
    by_label = {o.label: o.refusal for o in report.outcomes}
    assert by_label == {"01": REFUSAL_NOT_A_TABLE, "02": REFUSAL_EMPTY_DOCUMENT}


def test_inexactly_recognised_header_is_counted_apart_from_accepted(
    corpus_dir, references
):
    """Документ, чья шапка опознана по расстоянию редактирования, разобран —
    но не принят: измерений он не создаёт, пока коуч не подтвердит догадку
    (Task 6 плана). Считать его принятым значило бы приписать инструменту
    уверенность, которой у него нет; считать отказом — скрыть, что разбор
    его понял. Отдельный счёт «под подтверждение».
    """
    (corpus_dir / "20.jpg").write_bytes(b"\xff\xd8\xff")
    (corpus_dir / "21.jpg").write_bytes(b"\xff\xd8\xff")

    engine = _ScriptedEngine(
        {
            # «Ел.» вместо «Ед.» — опечатка распознавания в самой шапке.
            "20.jpg": [
                TextLine("Показатель", x=0.10, y=0.90),
                TextLine("Результат", x=0.40, y=0.90),
                TextLine("Ел.", x=0.65, y=0.90),
                TextLine("Референсные", x=0.85, y=0.90),
                *_row("Глюкоза", "5.5", "ммоль/л", "3.3-5.5", 0.80),
            ],
            "21.jpg": [*_HEADER, *_row("Глюкоза", "5.5", "ммоль/л", "3.3-5.5", 0.80)],
        }
    )

    report = scan_corpus(corpus_dir, references, engine)

    assert report.accepted == 1
    assert report.confirmable == 1
    assert report.refused_by == {}
    by_label = {o.label: (o.accepted, o.confirmable) for o in report.outcomes}
    assert by_label == {"01": (False, True), "02": (True, False)}
    # Строки разобраны и сопоставлены — разбор их понял, просто не сохранил.
    assert report.rows == 2
    assert report.resolved == 2
    assert "под подтверждение" in format_report(report)


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


def test_format_report_never_prints_a_row_that_did_not_split_into_name_and_value():
    """Обещание README «ни значений, ни исходного текста строк» держится и
    здесь — на строках, которые разбор не сумел разделить.

    Прежнее рассуждение было неверным: из отчёта исключался `unparsed`, а
    утечка приходила разобранными строками. Когда значение написано слитно
    с пометкой лаборатории («8.8++»), числом оно не считается, разбор
    ищет число дальше по строке, и в `raw_name` остаётся вся строка целиком
    — вместе с результатом пациентки, а иногда и с адресом, вычитанным
    распознаванием из колонтитула. Отчёт печатал это дословно.

    Такие записи считаются числом и не печатаются вовсе; настоящие названия
    показателей — печатаются, в том числе с цифрами внутри: список нужен
    коучу, чтобы видеть, чего не хватает её базе знаний.

    Строки здесь выдуманы — по форме тех, что нашлись в корпусе, но без
    единой настоящей цифры и без настоящего адреса: корпус в репозиторий не
    попадает ни файлами, ни цитатами.
    """
    report = CorpusReport(
        outcomes=(
            FileOutcome(
                label="01", accepted=True, refusal=None, rows=4, unparsed=0, resolved=0
            ),
        ),
        accepted=1,
        refused_by={},
        rows=4,
        resolved=0,
        unresolved_names={
            "Выдуманное антитело (кол.) 88.8++ МЕ/мл": 2,
            "Адрес: 00000, г. Выдуманск, Z9": 1,
            "Т3 свободный": 1,
        },
    )

    text = format_report(report)

    assert "88.8" not in text
    assert "антитело" not in text
    assert "00000" not in text
    assert "Выдуманск" not in text
    # Название показателя с цифрой внутри — не строка бланка, оно остаётся.
    assert "Т3 свободный" in text
    # Скрытое не исчезает бесследно: коуч видит, сколько названий не показано.
    assert "2" in text


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
    #
    # Разбор ревью (задачи 1-6): пустая ячейка «прочего» больше не убивает
    # строку, служебный отсев не глотает результат, начинающийся на то же
    # слово. Строк стало 684 вместо 656, сопоставлено 518 вместо 505,
    # нераспознанных — 973 вместо 1002. accepted не изменилось: шапок с
    # «прочим» не на последнем месте в корпусе нет, а 27 документов
    # по-прежнему отказываются с «шапка не найдена».
    #
    # Уборка (пункт 2): АлАТ/АсАТ заведены синонимами алт/аст, «T3
    # свободный» (латинская T) — синонимом т3_свободный, «Билирубин
    # общий»/«Билирубин прямой» заведены новыми показателями (это не
    # билирубин непрямой — три разные величины). Сопоставлено 528 строк
    # вместо 518. accepted не изменилось — эти правки только про базу
    # знаний, не про разбор шапки/строк.
    #
    # Уборка (пункт 3): гомоцистеин освобождён от роли заглушки в тестах
    # и заведён показателем (id гомоцистеин, синоним Homocysteine,
    # мкмоль/л, интервал [4.44, 13.56]). Печатается в корпусе четырежды —
    # сопоставлено 532 строки вместо 528.
    #
    # Уборка (запятая): распознавание пробует сперва полное написание
    # вместе с хвостом после запятой и только потом обрезанное. Десять
    # строк «X, абсолютное количество» перестали находить процентный
    # показатель и падать с «единицы не сопоставлены», пять строк «X #»
    # (абсолютный счёт другой лаборатории) впервые нашлись вовсе —
    # сопоставлено 537 строк вместо 532. accepted не изменилось.
    #
    # Task 4 расколола отказ «шапка не найдена» на два честных сообщения
    # (см. lab_table.py): «не похоже на таблицу» для документа со связным
    # текстом без шапки (заключения УЗИ, протоколы, рекомендации) и
    # «не нашлось текста» для документа вовсе без текста (пустой PDF,
    # нечитаемое фото). По корпусу все 27 бывших «шапка-не-найдена»
    # оказались первого рода — REFUSAL_NOT_A_TABLE: 27, REFUSAL_EMPTY_DOCUMENT: 0.
    # В корпусе нет ни одного документа, из которого распознавание не
    # вернуло бы вовсе никакого текста — путь пустого документа существует
    # для реальных случаев (пустой скан, нечитаемое фото), которых среди
    # 77 файлов не оказалось. accepted и resolved не изменились: это правка
    # сообщения и его класса, а не разбора.
    #
    # Task 6 завела неточное совпадение слов шапки под подтверждение коуча.
    # Два из трёх оставшихся отказов «шапка-колонки» — «Ел. изм.» вместо
    # «Ед. изм.» и «Референскыю» вместо «Референсные» — теперь разбираются,
    # но не как принятые: они считаются отдельно (confirmable), потому что
    # измерений без согласия коуча не создают. accepted остаётся 40, отказ
    # «шапка-колонки» падает с 3 до 1 (третий — «En. изм.», латинские буквы
    # вместо «Ед.»: на слове из двух букв неверны обе, и неточное совпадение
    # туда справедливо не дотягивается). resolved не изменилось: обе новые
    # шапки — фотографии, чьи строки база знаний не узнаёт (10 строк, 0
    # сопоставлений), и их вклад в табло виден только в rows.
    #
    # Разбор финального ревью, пункт 3: к порогам добавлен `units_agreed` —
    # строки, которые сопоставились и у которых единицы бланка принадлежат
    # найденному показателю. `resolved` не видит неверного сопоставления:
    # с выключенной уточнённой попыткой в resolve.py «Лимфоциты,
    # абсолютное количество» снова уходят к процентному показателю, а табло
    # показывает те же 40/537. Замер на сегодня — 460 из 537; остальные 77
    # сопоставленных строк пришли с бланков без колонки единиц (это
    # законно) или в написании, которого у показателя не объявлено.
    #
    # Пункты 2 и 4 ревью на эти числа не влияют: «Наименование»/«Референс»
    # и точный отказ по недочитанной шапке переставили семь документов из
    # класса «не-таблица» (27 → 20) в «шапка-колонки» (1 → 8) — им теперь
    # называют непонятое слово («флаг») вместо «это не таблица анализов», —
    # а «абс.» в корпусе не встречается вовсе (см. решение в журнале).
    min_accepted = 40
    min_confirmable = 2
    min_resolved = 537
    min_units_agreed = 460

    knowledge_dir = Path(__file__).parents[2] / "knowledge"
    references = load_references(knowledge_dir / "references")
    engine = _CachingEngine(AppleVisionEngine(), samples_dir / ".ocr-cache")
    report = scan_corpus(samples_dir, references, engine)

    # Числа берутся в локальные переменные до assert намеренно. pytest
    # переписывает утверждение и на падении печатает, откуда взялось левое
    # значение: `assert 39 >= 40 + where 39 = CorpusReport(…).accepted` — то
    # есть repr всего отчёта, вместе с `unresolved_names`, где лежат целые
    # строки бланка с результатами пациенток. Красная сборка выкладывала бы
    # их в лог. Сравнение голых чисел печатает только числа.
    accepted, confirmable = report.accepted, report.confirmable
    resolved, rows, units_agreed = report.resolved, report.rows, report.units_agreed

    assert accepted >= min_accepted, (
        f"принято {accepted} документов из {len(report.outcomes)}, "
        f"нужно не меньше {min_accepted}"
    )
    assert confirmable >= min_confirmable, (
        f"под подтверждение разобрано {confirmable} документов, "
        f"нужно не меньше {min_confirmable}"
    )
    assert resolved >= min_resolved, (
        f"сопоставлено {resolved} строк из {rows}, "
        f"нужно не меньше {min_resolved}"
    )
    assert units_agreed >= min_units_agreed, (
        f"единицы сошлись с найденным показателем у {units_agreed} строк из "
        f"{resolved} сопоставленных, нужно не меньше {min_units_agreed} — "
        "похоже, строка стала находить не тот показатель"
    )
