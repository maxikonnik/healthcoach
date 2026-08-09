"""Единый вход: файл выгрузки — в записи бланка.

PDF читается текстовым слоем, фотография — через движок распознавания.
Дальше оба идут одним путём: строки текста разбираются по шапке таблицы.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from healthcoach.intake.lab_table import LabTable, LabTableError, parse_lab_lines
from healthcoach.intake.ocr import OCREngine, OCRError, rows_from_observations
from healthcoach.intake.pdf import PdfError, read_pdf_lines
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
    """Прочитать выгрузку и разобрать её в записи бланка.

    Единый вход — единый тип ошибки: PdfError, OCRError и LabTableError
    заворачиваются в DocumentError с исходной причиной в `__cause__`.
    Иначе коуч, ловящий один лишь DocumentError на едином входе, получал
    бы необработанное исключение на самом обычном случае — сфотографиро-
    ванном бланке, сохранённом как PDF без текстового слоя.
    """
    suffix = path.suffix.casefold()

    if suffix == ".pdf":
        try:
            lines = read_pdf_lines(path)
        except PdfError as exc:
            raise DocumentError(f"{path.name}: {exc}") from exc
        source = SOURCE_PDF
    elif suffix in PHOTO_SUFFIXES:
        if engine is None:
            raise DocumentError(
                f"{path.name}: для фотографии нужно распознавание, движок не задан"
            )
        try:
            lines = rows_from_observations(engine.read(path))
        except OCRError as exc:
            raise DocumentError(f"{path.name}: {exc}") from exc
        source = SOURCE_PHOTO
    else:
        raise DocumentError(f"{path.name}: формат {suffix!r} не поддерживается")

    try:
        table = parse_lab_lines(lines)
    except LabTableError as exc:
        raise DocumentError(f"{path.name}: {exc}") from exc

    return ReadDocument(source=source, lines=tuple(lines), table=table)
