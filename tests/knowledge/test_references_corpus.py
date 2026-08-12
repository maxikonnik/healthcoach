"""Справочники показателей, заведённые по корпусу образцов.

Файлы в `knowledge/references/` — рабочая база знаний коуча, а не фикстура:
её читает и приложение, и отчёт. Поэтому проверяется она сама, а не копия
в tmp_path.

Главное, что здесь охраняется, — три свойства, без которых заведённый
показатель приносит вред, а не пользу:

1. Папка загружается целиком. Одна опечатка в YAML — и `load_references`
   бросает исключение на старте приложения, то есть коуч теряет все
   справочники сразу, а не один.
2. Ни одно написание не принадлежит двум показателям. `resolve_analyte`
   неоднозначность не разрешает: он возвращает обоих кандидатов, и вместо
   значения коуч получает вопрос «который из двух?». Проверка идёт через
   сам `resolve_analyte`, а не через сравнение строк, потому что он чистит
   название (`_clean`) перед сравнением: «Гемоглобин, г/л» и «Гемоглобин
   (HGB)» — одно и то же написание с его точки зрения.
3. У каждого показателя объявлены единицы. Пустые единицы означали бы, что
   любое измерение уходит в «единицы не сопоставлены».

Целевых коридоров в заведённых по корпусу файлах нет и быть не должно —
решение 1 плана: коридор это врачебное суждение коуча. Отдельный тест
показывает, во что такой показатель превращается на экране находок.
"""

from __future__ import annotations

import json
from collections import Counter
from dataclasses import asdict
from pathlib import Path

import pytest
import yaml

from healthcoach.intake.corpus import scan_corpus
from healthcoach.intake.measurements import prepare_measurements
from healthcoach.intake.ocr import OCREngine, TextLine
from healthcoach.intake.resolve import resolve_analyte
from healthcoach.knowledge.references import load_references
from healthcoach.scoring.references import (
    STATUS_NO_RULE,
    Measurement,
    Subject,
    check_measurements,
)

REFERENCES_DIR = Path(__file__).parents[2] / "knowledge" / "references"

CORPUS_FILES = (
    "blood_count.yaml",
    "biochemistry.yaml",
    "thyroid.yaml",
    "lipids.yaml",
    "iron.yaml",
    "vitamins.yaml",
)
"""Файлы, заведённые по корпусу образцов (Task 5 плана).

Отделены от `ferritin.yaml` и `derived.yaml`: те написаны коучем и целевые
коридоры в них есть по праву. В этих — нет и не должно быть.
"""


@pytest.fixture(scope="module")
def references():
    return load_references(REFERENCES_DIR)


def _raw(name: str) -> dict:
    return yaml.safe_load((REFERENCES_DIR / name).read_text(encoding="utf-8")) or {}


def test_references_folder_loads_whole(references):
    """Вся папка читается разом — включая файлы, заведённые по корпусу."""
    assert references.analytes


@pytest.mark.parametrize("name", CORPUS_FILES)
def test_corpus_file_exists_and_declares_analytes(name):
    assert (REFERENCES_DIR / name).is_file(), f"нет файла {name}"
    assert _raw(name).get("показатели"), f"{name}: ни одного показателя"


def test_analyte_ids_are_unique(references):
    ids = [a.id for a in references.analytes] + [d.id for d in references.derived]
    duplicates = sorted({i for i in ids if ids.count(i) > 1})
    assert not duplicates, f"повторяющиеся идентификаторы: {duplicates}"


def test_no_spelling_belongs_to_two_analytes(references):
    """Каждое объявленное написание однозначно указывает на свой показатель.

    Проверяется ровно тем механизмом, которым пользуется загрузка выгрузки:
    `resolve_analyte`. Если два показателя претендуют на одно написание, он
    возвращает обоих и не выбирает — измерение уходит коучу вопросом.
    """
    clashes = []
    for analyte in references.analytes:
        for spelling in (analyte.id, analyte.name, *analyte.synonyms):
            resolution = resolve_analyte(references, spelling)
            if resolution.analyte is not analyte:
                claimed = ", ".join(a.id for a in resolution.candidates) or "никому"
                clashes.append(f"{analyte.id}: {spelling!r} → {claimed}")
    assert not clashes, "написание принадлежит не своему показателю:\n" + "\n".join(
        clashes
    )


def test_no_spelling_collides_on_either_matching_attempt(references):
    """Ни одно написание не занято дважды — ни в уточнённой, ни в общей форме.

    `resolve_analyte` пробует сперва полное написание (вместе с хвостом
    после запятой), и только не найдя — обрезанное по первой запятой. Тест
    выше идёт через сам `resolve_analyte` и поэтому столкновения во второй,
    запасной, форме не видит: уточнённая попытка успевает вернуть ответ
    раньше. А оно опасно — стоит написанию с запятой попасть в базу знаний
    («Лимфоциты, абсолютное количество»), и его обрезок «лимфоциты» отберёт
    у настоящих лимфоцитов их собственное имя на запасной попытке.
    """
    from healthcoach.intake.resolve import _clean, _clean_qualified

    for clean, form in ((_clean_qualified, "уточнённой"), (_clean, "общей")):
        owners: dict[str, list[str]] = {}
        for analyte in references.analytes:
            for spelling in (analyte.id, analyte.name, *analyte.synonyms):
                key = clean(spelling)
                if not key:
                    continue
                owners.setdefault(key, []).append(analyte.id)
        clashes = {
            key: sorted(set(ids)) for key, ids in owners.items() if len(set(ids)) > 1
        }
        assert not clashes, f"в {form} форме написание занято дважды: {clashes}"


def test_percentage_and_absolute_variants_never_share_a_spelling(references):
    """Доля и абсолютный счёт одной клеточной линии — разные показатели.

    Синоним, объявленный у обоих, делает оба неоднозначными: `resolve_analyte`
    вернёт двух кандидатов и не выберет. Хуже другое — если бы написание
    абсолютного счёта досталось процентному показателю, абсолютный счёт
    клиента поехал бы в отчёт под подписью «%».
    """
    pairs = (
        ("лимфоциты", "лимфоциты_абс"),
        ("моноциты", "моноциты_абс"),
        ("нейтрофилы", "нейтрофилы_абс"),
        ("эозинофилы", "эозинофилы_абс"),
        ("базофилы", "базофилы_абс"),
        ("незрелые_гранулоциты_процент", "незрелые_гранулоциты"),
    )
    for percent_id, absolute_id in pairs:
        percent = references.resolve(percent_id)
        absolute = references.resolve(absolute_id)
        assert percent is not None, f"нет показателя {percent_id}"
        assert absolute is not None, f"нет показателя {absolute_id}"
        assert percent.units == "%", f"{percent_id}: единицы {percent.units!r}"
        assert absolute.units != "%", f"{absolute_id}: единицы {absolute.units!r}"

        shared = {s.casefold() for s in percent.synonyms} & {
            s.casefold() for s in absolute.synonyms
        }
        assert not shared, f"{percent_id}/{absolute_id}: общее написание {shared}"


def test_every_analyte_declares_units(references):
    without = [a.id for a in references.analytes if not a.units.strip()]
    assert not without, f"показатели без единиц: {without}"


def test_unit_spellings_are_distinct_within_analyte(references):
    """Написание единиц не объявлено дважды у одного показателя.

    Повтор безвреден для сравнения, но означает, что список писали не глядя,
    — а именно этот список решает, примут ли строку бланка.
    """
    from healthcoach.knowledge.units import normalize_units

    repeated = {}
    for analyte in references.analytes:
        spellings = [analyte.units, *analyte.unit_aliases]
        counts = Counter(normalize_units(u) for u in spellings)
        extra = sorted(u for u, n in counts.items() if n > 1)
        if extra:
            repeated[analyte.id] = extra
    assert not repeated, f"единицы объявлены дважды: {repeated}"


@pytest.mark.parametrize("name", CORPUS_FILES)
def test_corpus_files_declare_no_targets(name):
    """Решение 1 плана: показатели завожу я, целевые коридоры — коуч.

    Придуманный коридор — это выдуманная медицина в отчёте клиента.
    Показатель без коридора всё равно полезен, см. тест ниже.
    """
    with_targets = [
        a.get("id") for a in _raw(name).get("показатели", ()) if a.get("целевые")
    ]
    assert not with_targets, f"{name}: целевые коридоры заведены у {with_targets}"


def test_analyte_without_target_lands_in_no_rule(references):
    """Показатель без коридора попадает в рабочий список коуча, а не пропадает.

    Название берётся из базы знаний (не с бланка клиента), лабораторный
    интервал показывается, статус — «правило не задано», `rule_missing`
    поднят: на экране находок это блок «нет правила в базе знаний».
    """
    hemoglobin = references.resolve("гемоглобин")
    assert hemoglobin is not None
    assert hemoglobin.targets == ()

    verdicts = check_measurements(
        references,
        [Measurement(analyte_id="гемоглобин", value=118.0, units="г/л")],
        Subject(sex="ж", age=41),
    )

    (verdict,) = verdicts
    assert verdict.status == STATUS_NO_RULE
    assert verdict.rule_missing is True
    assert verdict.target is None
    assert verdict.title == "Гемоглобин"
    assert verdict.title_from_document is False
    assert verdict.value == 118.0


def test_corpus_analytes_resolve_from_live_blank_spellings(references):
    """Написания, какими они приходят с бланка, а не какими записаны в YAML.

    `_clean` срезает код номенклатуры, скобочные уточнения и всё после
    первой запятой — эти строки обязаны находиться без отдельных синонимов.
    """
    expected = {
        "Гемоглобин, г/л": "гемоглобин",
        "Гемоглобин (HGB, Hb)": "гемоглобин",
        "Тромбоциты (PLT)": "тромбоциты",
        "Общее количество эритроцитов (RBC)": "эритроциты",
        "Скорость оседания эритроцитов (СОЭ)": "соэ",
        "Аланинаминотрансфераза (АЛТ) (венозная кровь)": "алт",
        "Общий белок (венозная кровь)": "общий_белок",
        "Магний (кровь, фотометрия)": "магний",
        "Натрий (Na+) (сыворотка крови)": "натрий",
        "Абсолютное содержание лимфоцитов": "лимфоциты_абс",
        "Фолиевая кислота (Folic acid)": "фолиевая_кислота",
        "Антитела к тиреопероксидазе (Anti-TPO) Ig G,": "ат_тпо",
        # Четырёхбуквенные написания той же лаборатории: «АлАТ»/«АсАТ»
        # (не «АЛТ»/«АСТ» — другая буква в середине, `_clean` их не
        # уравнивает).
        "АлАТ": "алт",
        "АсАТ": "аст",
        # Латинская «T» вместо кириллической «Т» — печать другой
        # лаборатории, тот же показатель.
        "T3 свободный": "т3_свободный",
        "Билирубин общий": "билирубин_общий",
        "Билирубин прямой": "билирубин_прямой",
        # Хвост после запятой называет величину, а не единицы: у одной
        # клеточной линии печатаются обе строки, доля и абсолютный счёт.
        "Лимфоциты (LYMPH), %": "лимфоциты",
        "Лимфоциты (LYMPH), абсолютное количество": "лимфоциты_абс",
        "Моноциты (MON), абсолютное количество": "моноциты_абс",
        "Нейтрофилы (Ne), абсолютное количество": "нейтрофилы_абс",
        "Эозинофилы (Ео), абсолютное количество": "эозинофилы_абс",
        "Базофилы (Ва), абсолютное количество": "базофилы_абс",
        # «#» и «%» другой лаборатории — те же две величины.
        "Лимфоциты (LY) #": "лимфоциты_абс",
        "Незрелые гранулоциты (IG) #": "незрелые_гранулоциты",
        "Незрелые гранулоциты IG, %": "незрелые_гранулоциты_процент",
    }
    for raw_name, analyte_id in expected.items():
        resolution = resolve_analyte(references, raw_name)
        assert resolution.is_certain, f"{raw_name!r} не распознан"
        assert resolution.analyte.id == analyte_id, (
            f"{raw_name!r} → {resolution.analyte.id}, ожидался {analyte_id}"
        )


def test_declared_unit_spellings_are_accepted(references):
    """Написания единиц из корпуса проходят сверку `units_match`.

    Строгую: без неё строка отвергается с «единицы не сопоставлены», и
    заведённый показатель не приносит ничего.
    """
    from healthcoach.knowledge.units import units_match

    corpus_units = {
        "гемоглобин": ("г/л",),
        "лейкоциты": ("10⁹/л", "x10*9/л", "10*9/литр", "10^9/Л", "109/л"),
        "эритроциты": ("10¹²/л", "x10*12/л", "10*12/литр", "10^12/л"),
        "соэ": ("мм/час", "мм/ч"),
        "ттг": ("мкМЕ/мл", "мЕд/л", "мМЕ/л"),
        "инсулин": ("мкМЕ/мл", "мкЕд/мл", "МКМЕ/мл"),
        "mcv": ("фл", "фл."),
        "алт": ("Ед/л",),
    }
    for analyte_id, spellings in corpus_units.items():
        analyte = references.resolve(analyte_id)
        assert analyte is not None, f"нет показателя {analyte_id}"
        for spelling in spellings:
            assert units_match(analyte, spelling), (
                f"{analyte_id}: единицы {spelling!r} не сопоставлены"
            )


def test_millimoles_are_not_declared_a_synonym_of_milligrams(references):
    """Единицы разной размерности синонимами не объявлены.

    `units_match` арифметики не делает: объявить мг/дл синонимом мг/л
    значило бы сравнить с коридором число, отличающееся в десять раз, и
    сделать это молча. Такая единица обязана остаться несопоставленной.
    """
    from healthcoach.knowledge.units import units_match

    crp = references.resolve("срб")
    assert crp is not None
    assert crp.units == "мг/л"
    assert not units_match(crp, "мг/дл")


class _CachingEngine:
    """Тот же дисковый кэш распознавания, что и в табло качества.

    Отдельная копия, а не импорт из tests/intake/test_corpus.py: пакета из
    тестов нет (`__init__.py` не заведены), и импортировать соседний модуль
    по пути значило бы завязать справочники на файл, который живёт своей
    жизнью. Кэш общий — папка `samples/.ocr-cache/` та же, — поэтому второй
    прогон по корпусу распознаванием не занимается вовсе.
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


MIN_RESOLVED_ROWS = 537
"""Абсолютное число строк корпуса, которое база знаний узнаёт — основной порог.

Раньше порогом была доля (`resolved / rows`), и это наказывало прогресс.
Правка разбора спасла строки, которые раньше умирали до попытки
сопоставления, — и это строгое улучшение (505 → 518 сопоставленных строк,
ни одна не потеряна), но заодно выросло и общее число строк (656 → 684):
у доли растёт не только числитель, но и знаменатель, так что она просела
0.77 → 0.76 и зажгла красный тест на чистом прогрессе. Абсолютное число
сопоставленных строк такой болезни не подвержено — оно может только расти
вместе с прогрессом, и это порог, который проверяется здесь.

Порог поднимает каждая следующая задача плана по факту прогона; понижать его
нельзя без отдельного решения — ровно как пороги табло в
tests/intake/test_corpus.py.

Уборка (пункт 2 отчёта): АлАТ/АсАТ/«T3 свободный» (лат.) заведены
синонимами уже известных показателей, «Билирубин общий»/«Билирубин прямой»
— новыми показателями. Сопоставлено 528 строк вместо 518.

Уборка (пункт 3 отчёта): гомоцистеин освобождён от роли заглушки в тестах
и заведён показателем — печатается в корпусе четырежды, сопоставлено 532
строки вместо 528.

Уборка (запятая): хвост после запятой больше не отбрасывается вслепую —
сперва пробуется полное написание, и только не найдя, обрезанное. Десять
строк «X, абсолютное количество» лейкоцитарной формулы перестали выдавать
себя за процентный показатель, пять строк «X #» нашлись впервые —
сопоставлено 537 строк вместо 532.
"""


@pytest.mark.samples
def test_corpus_resolution_share_and_no_ambiguity(samples_dir):
    """По настоящему корпусу: узнаётся большинство строк и ни одна — надвое.

    Второе важнее первого. Неоднозначность означает, что два показателя
    заявили одно написание: коуч получит вопрос «который из двух?» вместо
    значения, и заметит это не на тесте, а на живой выгрузке.

    Доля (`share`) печатается в сообщении об ошибке как диагностика — не
    как условие: см. комментарий у MIN_RESOLVED_ROWS.
    """
    from healthcoach.intake.documents import DocumentError, read_document
    from healthcoach.intake.ocr import AppleVisionEngine

    references = load_references(REFERENCES_DIR)
    engine = _CachingEngine(AppleVisionEngine(), samples_dir / ".ocr-cache")

    report = scan_corpus(samples_dir, references, engine)
    share = report.resolved / report.rows
    assert report.resolved >= MIN_RESOLVED_ROWS, (
        f"сопоставлено {report.resolved} строк из {report.rows} "
        f"({share:.2f}), нужно не меньше {MIN_RESOLVED_ROWS} строк"
    )

    ambiguous: list[str] = []
    for path in sorted(samples_dir.rglob("*")):
        if not path.is_file() or path.name.startswith(("~$", ".")):
            continue
        try:
            document = read_document(path, engine)
        except DocumentError:
            continue
        for measurement in prepare_measurements(references, document.table):
            resolution = resolve_analyte(references, measurement.raw_name)
            if resolution.is_ambiguous:
                claimed = ", ".join(a.id for a in resolution.candidates)
                ambiguous.append(f"{measurement.raw_name!r} → {claimed}")
    assert not ambiguous, "название подошло двум показателям:\n" + "\n".join(
        sorted(set(ambiguous))
    )
