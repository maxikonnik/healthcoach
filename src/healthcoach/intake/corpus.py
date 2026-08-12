"""Табло качества распознавания: прогон разбора по всему корпусу образцов.

Раньше «стало лучше» проверить было нечем — числа приходилось считать
глазами по логу. Этот модуль считает их сам: сколько документов разбор
принимает, на чём отказывает и сколько строк узнаёт база знаний. Каждая
следующая задача плана поднимает пороги в тесте по факту нового прогона,
а не выдумывает их заново.

Отчёт для человека печатает только имена файлов, числа и названия
показателей — ни значений измерений, ни исходного текста строк. Строки,
которые разбор не распознал (`LabTable.unparsed`), в отчёт не попадают
вовсе: там может быть что угодно с бланка, включая персональные данные,
пока служебные строки не отсеяны (см. Task 3 плана).
"""

from __future__ import annotations

import sys
from collections import Counter
from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from pathlib import Path

from healthcoach.intake.documents import DocumentError, read_document
from healthcoach.intake.measurements import UNRESOLVED, prepare_measurements
from healthcoach.intake.ocr import OCREngine
from healthcoach.knowledge.references import References, load_references

REFUSAL_HEADER_COLUMNS = "шапка-колонки"
REFUSAL_HEADER_MISSING = "шапка-не-найдена"
REFUSAL_FORMAT = "формат"
REFUSAL_OTHER = "иное"

_SKIP_PREFIXES = ("~$", ".")
"""Не документы, пропускаются молча: временные замки Office (`~$…`) и
точечные служебные файлы/папки macOS (`.DS_Store`, кэш распознавания и
подобное) — рекурсия в них не заходит вовсе."""


@dataclass(frozen=True)
class FileOutcome:
    """Итог разбора одного файла корпуса."""

    name: str
    """Имя файла — только для локального отчёта, не сохраняется никуда."""
    accepted: bool
    refusal: str | None
    rows: int
    unparsed: int
    resolved: int


@dataclass(frozen=True)
class CorpusReport:
    """Табло по всему корпусу: свод `FileOutcome` плюс агрегаты."""

    outcomes: tuple[FileOutcome, ...]
    accepted: int
    refused_by: Mapping[str, int]
    rows: int
    resolved: int
    unresolved_names: Mapping[str, int]
    """Название показателя с бланка → сколько раз встретилось. Названия
    показателей персональными данными не являются (в отличие от значений
    или необработанных строк), поэтому в отчёт идут как есть."""


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
    """
    if "не поддерживается" in message:
        return REFUSAL_FORMAT
    if "строка-шапка" in message:
        return REFUSAL_HEADER_COLUMNS
    if "не найдена шапка" in message:
        return REFUSAL_HEADER_MISSING
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

    for path in _iter_documents(folder):
        try:
            document = read_document(path, engine)
        except DocumentError as exc:
            refusal = _classify_refusal(str(exc))
            refused_by[refusal] += 1
            outcomes.append(
                FileOutcome(
                    name=path.name,
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
        for measurement in prepared:
            if measurement.analyte_id == UNRESOLVED:
                unresolved_names[measurement.raw_name] += 1

        total_rows += len(document.table.rows)
        total_resolved += resolved
        outcomes.append(
            FileOutcome(
                name=path.name,
                accepted=True,
                refusal=None,
                rows=len(document.table.rows),
                unparsed=len(document.table.unparsed),
                resolved=resolved,
            )
        )

    return CorpusReport(
        outcomes=tuple(outcomes),
        accepted=sum(1 for o in outcomes if o.accepted),
        refused_by=dict(refused_by),
        rows=total_rows,
        resolved=total_resolved,
        unresolved_names=dict(unresolved_names),
    )


def format_report(report: CorpusReport) -> str:
    """Собрать отчёт для человека: таблица по файлам плюс сводка.

    Только имена файлов, числа и названия показателей — как договорено в
    Task 1 плана. Ни значений, ни исходного текста строк здесь нет.
    """
    lines: list[str] = []
    lines.append("=== по файлам: имя | итог | строк | нераспознано | сопоставлено ===")
    for outcome in report.outcomes:
        status = "ok" if outcome.accepted else f"отказ ({outcome.refusal})"
        lines.append(
            f"  {outcome.name} | {status} | {outcome.rows} | "
            f"{outcome.unparsed} | {outcome.resolved}"
        )

    total = len(report.outcomes)
    lines.append("")
    lines.append("=== итог ===")
    lines.append(f"  принято: {report.accepted} из {total}")
    refused_total = total - report.accepted
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

    unresolved_total = report.rows - report.resolved
    lines.append("")
    lines.append(
        f"=== не сопоставлено: {unresolved_total} строк, "
        f"{len(report.unresolved_names)} различных названий ==="
    )
    for name, count in sorted(
        report.unresolved_names.items(), key=lambda item: (-item[1], item[0])
    ):
        lines.append(f"  {count}× {name}")

    return "\n".join(lines)


def main() -> None:
    """Печать табло по настоящему корпусу — `python -m healthcoach.intake.corpus`."""
    from healthcoach.intake.ocr import AppleVisionEngine

    repo_root = Path(__file__).resolve().parents[3]
    samples_dir = repo_root / "samples"
    if not samples_dir.is_dir():
        print(f"папки {samples_dir} нет — смотреть табло не по чему")
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
