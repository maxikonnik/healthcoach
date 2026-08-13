"""Табло качества распознавания: прогон разбора по всему корпусу образцов.

Раньше «стало лучше» проверить было нечем — числа приходилось считать
глазами по логу. Этот модуль считает их сам: сколько документов разбор
принимает, на чём отказывает и сколько строк узнаёт база знаний. Каждая
следующая задача плана поднимает пороги в тесте по факту нового прогона,
а не выдумывает их заново.

Отчёт для человека печатает только номера файлов, числа и названия
показателей — ни значений измерений, ни исходного текста строк, ни имён
файлов: в именах файлов корпуса стоят фамилии пациентов. Строки,
которые разбор не распознал (`LabTable.unparsed`), в отчёт не попадают
вовсе: там может быть что угодно с бланка, включая персональные данные,
пока служебные строки не отсеяны (см. Task 3 плана).

Но и разобранная строка приносит с собой не только название: когда
разделить название и значение не удалось, вся строка остаётся в
`raw_name` — вместе с результатом пациентки. Поэтому названия перед
печатью просеиваются (`_is_whole_row`), а не выводятся как есть.
"""

from __future__ import annotations

import re
import sys
from collections import Counter
from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from pathlib import Path

from healthcoach.intake.documents import DocumentError, read_document
from healthcoach.intake.measurements import UNRESOLVED, prepare_measurements
from healthcoach.intake.ocr import OCREngine
from healthcoach.knowledge.references import References, load_references
from healthcoach.knowledge.units import units_match

REFUSAL_HEADER_COLUMNS = "шапка-колонки"
REFUSAL_NOT_A_TABLE = "не-таблица"
REFUSAL_EMPTY_DOCUMENT = "документ-пуст"
REFUSAL_FORMAT = "формат"
REFUSAL_OTHER = "иное"

_SKIP_PREFIXES = ("~$", ".")
"""Не документы, пропускаются молча: временные замки Office (`~$…`) и
точечные служебные файлы/папки macOS (`.DS_Store`, кэш распознавания и
подобное) — рекурсия в них не заходит вовсе."""


@dataclass(frozen=True)
class FileOutcome:
    """Итог разбора одного файла корпуса."""

    label: str
    """Номер файла в порядке обхода корпуса, а не его имя.

    В именах файлов корпуса стоят фамилии пациентов и номер карты, а отчёт
    описан в README как безопасный к показу. Номер для чтения табло стоит
    столько же, а фамилии не несёт; найти сам файл коуч может по номеру:
    `python -m healthcoach.intake.corpus 7`."""
    accepted: bool
    refusal: str | None
    rows: int
    unparsed: int
    resolved: int
    confirmable: bool = False
    """Шапка опознана неточно (по расстоянию редактирования): документ
    разобран, но измерений сам по себе не создаёт — сперва коуч смотрит на
    догадку и соглашается с ней (Task 6 плана). `accepted` у такого файла
    False: приписать его к принятым значило бы записать инструменту
    уверенность, которой у него нет; отказом он тоже не назван — разбор его
    понял, и `refusal` остаётся None."""


@dataclass(frozen=True)
class CorpusReport:
    """Табло по всему корпусу: свод `FileOutcome` плюс агрегаты."""

    outcomes: tuple[FileOutcome, ...]
    accepted: int
    """Документы, которые инструмент разбирает и сохраняет сам, ничего не
    спрашивая. Файлы под подтверждение сюда не входят — см. `confirmable`."""
    refused_by: Mapping[str, int]
    rows: int
    resolved: int
    unresolved_names: Mapping[str, int]
    """Название показателя с бланка → сколько раз встретилось.

    Здесь лежит то, что разбор счёл названием, — а это не всегда только
    название: строка, не разделившаяся на название и значение, приходит
    сюда целиком, вместе с результатом. Само поле хранит всё как есть (по
    нему считают, а не показывают); отсеивает такие записи печать —
    см. `_is_whole_row` и `format_report`."""
    confirmable: int = 0
    """Документы, разобранные только благодаря неточному совпадению слов
    шапки. Их строки и сопоставления посчитаны в `rows` и `resolved` — разбор
    их правда прочитал, — но в базу они попадают лишь с согласия коуча."""
    units_agreed: int = 0
    """Строки, которые не только сопоставились, но сопоставились с тем, с
    чем надо: единицы бланка принадлежат найденному показателю
    (`units_match`).

    `resolved` считает, что строка нашла показатель, и не считает, какой:
    на ревью уточнённая попытка в resolve.py была выключена — «Лимфоциты,
    абсолютное количество» снова уходило к процентному показателю, — и
    табло показало те же самые 40/537. Инструмент, который не видит
    неверного сопоставления, мерил меньше, чем обещал каждым своим числом.

    Единицы — независимая проверка того же события: у чужого показателя они
    почти всегда другие (проценты против 10⁹/л). Счёт заведомо ниже
    `resolved` — бланк без колонки единиц законен, и его строки сюда не
    попадают вовсе, — но он падает ровно тогда, когда распознавание
    портится, а этого от него и надо."""


_VALUE_TOKEN = re.compile(r"^[<>≤≥]?\d+(?:[.,]\d+)?[+\-*↑↓hHlL]*[,;:.]?$")
"""Как выглядит значение с бланка, стоящее отдельным словом.

Число, при нём — необязательный знак сравнения слева и пометки лаборатории
справа: «8.8++», «8.8-», «8.8*», «8.8--», «<8.8», «88888,» (формы взяты из
корпуса, цифры выдуманы — сам корпус в репозиторий не попадает даже
цитатой). Именно такое слово внутри «названия» и означает, что строка не
разделилась: разбор берёт значением первое слово, которое целиком число
(см. `_NUMBER` в lab_table.py), а «8.8++» целиком числом не является —
поиск уходит дальше по строке, и результат остаётся в названии.

Цифра сама по себе признаком не служит: «Т3 свободный», «Витамин B12»,
«СА 19-9» — настоящие названия показателей, и в них цифра приклеена к
буквам или к другой цифре через дефис. Поэтому диапазон («0-2», «19-9»)
здесь значением намеренно не считается: правило, ловящее диапазоны, съело
бы и «СА 19-9», и «ГОСТ Р ИСО 9001-2015», а список названий коуч читает как
рабочий — вычищать из него настоящие названия нельзя."""


def _is_whole_row(name: str) -> bool:
    """Не название показателя, а целая строка бланка вместе со значением.

    Такое «название» печатать нельзя: в нём стоит результат пациентки, а
    иногда и адрес или фамилия, вычитанные распознаванием из колонтитула.
    В отчёте оно превращается в число (см. `format_report`)."""
    return any(_VALUE_TOKEN.match(word) for word in name.split())


def _classify_refusal(message: str) -> str:
    """Класс отказа по тексту `DocumentError`.

    Единственное место в проекте, которое знает эти подстроки. Сообщения
    рождаются в documents.py и lab_table.py; если формулировка там
    поменяется, здесь отказ молча провалится в REFUSAL_OTHER — и тест на
    классификацию (tests/intake/test_corpus.py) это ловит, а не пропускает:
    он берёт не выдуманную строку, а настоящий отказ разбора плохой шапки.

    Признак отказа по колонкам — «строка-шапка», а не формулировка одной
    из причин: причин уже две (слово шапки не опознано; колонка свободного
    текста стоит не последней), и обе называют саму строку-шапку.

    Отказ «шапка не найдена вовсе» (Task 4 плана) разделён на два класса по
    тому же принципу — по подстроке настоящего сообщения коучу, не по
    выдуманной строке: в документе был связный текст, но ни одна строка не
    подошла под шапку таблицы (REFUSAL_NOT_A_TABLE — заключения, протоколы,
    рекомендации), или текста не нашлось вовсе (REFUSAL_EMPTY_DOCUMENT —
    пустой PDF, нечитаемое фото). Порядок проверок важен: сообщение
    REFUSAL_EMPTY_DOCUMENT тоже говорит «не нашлось текста», а не «не
    похоже на таблицу», так что подстроки не пересекаются.
    """
    if "не поддерживается" in message:
        return REFUSAL_FORMAT
    if "строка-шапка" in message:
        return REFUSAL_HEADER_COLUMNS
    if "не нашлось текста" in message:
        return REFUSAL_EMPTY_DOCUMENT
    if "не похоже на таблицу" in message:
        return REFUSAL_NOT_A_TABLE
    return REFUSAL_OTHER


def _iter_documents(folder: Path) -> Iterator[Path]:
    """Файлы корпуса по всем подпапкам, в стабильном порядке.

    Собственная рекурсия, а не `Path.rglob`, — чтобы не заходить внутрь
    пропущенных папок вовсе: `rglob("*")` в pathlib, в отличие от shell,
    отдаёт и точечные файлы, и всё, что лежит внутри точечных папок
    (например, кэш распознавания рядом с корпусом).
    """
    for entry in sorted(folder.iterdir()):
        if entry.name.startswith(_SKIP_PREFIXES):
            continue
        if entry.is_dir():
            yield from _iter_documents(entry)
        elif entry.is_file():
            yield entry


def scan_corpus(
    folder: Path, references: References, engine: OCREngine | None
) -> CorpusReport:
    """Прогнать разбор по всем файлам папки и посчитать табло."""
    outcomes: list[FileOutcome] = []
    refused_by: Counter[str] = Counter()
    unresolved_names: Counter[str] = Counter()
    total_rows = 0
    total_resolved = 0
    total_units_agreed = 0

    for number, path in enumerate(_iter_documents(folder), start=1):
        label = f"{number:02d}"
        try:
            document = read_document(path, engine)
        except DocumentError as exc:
            refusal = _classify_refusal(str(exc))
            refused_by[refusal] += 1
            outcomes.append(
                FileOutcome(
                    label=label,
                    accepted=False,
                    refusal=refusal,
                    rows=0,
                    unparsed=0,
                    resolved=0,
                )
            )
            continue

        prepared = prepare_measurements(references, document.table)
        resolved = sum(1 for m in prepared if m.analyte_id != UNRESOLVED)
        # Единицы берутся из самой записи бланка, а не из `measurement.units`:
        # там они уже канонизированы найденным показателем, и сверять их с
        # ним значило бы сверять его с самим собой.
        for row, measurement in zip(document.table.rows, prepared, strict=True):
            if measurement.analyte_id == UNRESOLVED:
                unresolved_names[measurement.raw_name] += 1
                continue
            analyte = references.analyte(measurement.analyte_id)
            if analyte is not None and units_match(analyte, row.units):
                total_units_agreed += 1

        total_rows += len(document.table.rows)
        total_resolved += resolved
        confirmable = document.table.needs_confirmation
        outcomes.append(
            FileOutcome(
                label=label,
                accepted=not confirmable,
                refusal=None,
                rows=len(document.table.rows),
                unparsed=len(document.table.unparsed),
                resolved=resolved,
                confirmable=confirmable,
            )
        )

    return CorpusReport(
        outcomes=tuple(outcomes),
        accepted=sum(1 for o in outcomes if o.accepted),
        refused_by=dict(refused_by),
        rows=total_rows,
        resolved=total_resolved,
        unresolved_names=dict(unresolved_names),
        confirmable=sum(1 for o in outcomes if o.confirmable),
        units_agreed=total_units_agreed,
    )


def format_report(report: CorpusReport) -> str:
    """Собрать отчёт для человека: таблица по файлам плюс сводка.

    Только номера файлов, числа и названия показателей — как договорено в
    Task 1 плана. Ни значений, ни исходного текста строк, ни имён файлов
    (в них стоят фамилии пациентов) здесь нет.

    Список нераспознанных названий — рабочий список коуча: по нему видно,
    чего не хватает базе знаний. Поэтому он печатается, но из него убраны
    записи, в которых стоит не название, а вся строка бланка со значением
    (`_is_whole_row`): их коуч видит числом. Показать их значило бы
    напечатать результат пациентки, а разделить название и значение уже
    после разбора — угадать границу там, где разбор её не нашёл.
    """
    lines: list[str] = []
    lines.append("=== по файлам: № | итог | строк | нераспознано | сопоставлено ===")
    for outcome in report.outcomes:
        if outcome.accepted:
            status = "ok"
        elif outcome.confirmable:
            status = "под подтверждение"
        else:
            status = f"отказ ({outcome.refusal})"
        lines.append(
            f"  {outcome.label} | {status} | {outcome.rows} | "
            f"{outcome.unparsed} | {outcome.resolved}"
        )

    total = len(report.outcomes)
    lines.append("")
    lines.append("=== итог ===")
    lines.append(f"  принято: {report.accepted} из {total}")
    if report.confirmable:
        lines.append(
            f"  под подтверждение: {report.confirmable} "
            "(шапка опознана неточно — импорт только с согласия коуча)"
        )
    refused_total = total - report.accepted - report.confirmable
    lines.append(f"  отказ: {refused_total}")

    if report.refused_by:
        lines.append("")
        lines.append("=== классы отказов ===")
        for refusal, count in sorted(
            report.refused_by.items(), key=lambda item: (-item[1], item[0])
        ):
            lines.append(f"  {count}× {refusal}")

    lines.append("")
    lines.append(f"=== сопоставлено с базой знаний: {report.resolved} строк ===")
    lines.append(
        f"  из них единицы бланка принадлежат найденному показателю: "
        f"{report.units_agreed}"
    )

    unresolved_total = report.rows - report.resolved
    lines.append("")
    lines.append(
        f"=== не сопоставлено: {unresolved_total} строк, "
        f"{len(report.unresolved_names)} различных названий ==="
    )
    printable = {
        name: count
        for name, count in report.unresolved_names.items()
        if not _is_whole_row(name)
    }
    for name, count in sorted(printable.items(), key=lambda item: (-item[1], item[0])):
        lines.append(f"  {count}× {name}")

    hidden = len(report.unresolved_names) - len(printable)
    if hidden:
        lines.append(
            f"  ещё {hidden} не напечатаны: строка не разделилась на название "
            "и значение, и печатать её целиком нельзя — в ней результат"
        )

    return "\n".join(lines)


def main() -> None:
    """Печать табло по настоящему корпусу — `python -m healthcoach.intake.corpus`.

    С номером файла (`python -m healthcoach.intake.corpus 7`) вместо табло
    печатает путь одного файла — того, что стоит в отчёте под этим номером.
    Имена файлов из табло убраны (в них фамилии пациентов), но найти файл,
    к которому относится строка отчёта, коучу всё равно нужно; поиск по
    одному номеру она делает сама и осознанно.
    """
    from healthcoach.intake.ocr import AppleVisionEngine

    repo_root = Path(__file__).resolve().parents[3]
    samples_dir = repo_root / "samples"
    if not samples_dir.is_dir():
        print(f"папки {samples_dir} нет — смотреть табло не по чему")
        raise SystemExit(1)

    if len(sys.argv) > 1:
        wanted = sys.argv[1].lstrip("0")
        for number, path in enumerate(_iter_documents(samples_dir), start=1):
            if str(number) == wanted:
                print(path)
                return
        print(f"файла под номером {sys.argv[1]} в корпусе нет")
        raise SystemExit(1)

    references = load_references(repo_root / "knowledge" / "references")
    try:
        engine: OCREngine | None = AppleVisionEngine()
    except Exception:
        engine = None

    report = scan_corpus(samples_dir, references, engine)
    print(format_report(report))


if __name__ == "__main__":
    sys.exit(main() or 0)
