"""Единый вход: файл выгрузки — в записи бланка.

PDF читается текстовым слоем, фотография — через движок распознавания.
Дальше оба идут одним путём: строки текста разбираются по шапке таблицы.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from healthcoach.intake.lab_table import LabTable, parse_lab_lines
from healthcoach.intake.ocr import OCREngine, rows_from_observations
from healthcoach.intake.pdf import read_pdf_lines
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
    """Прочитать выгрузку и разобрать её в записи бланка."""
    suffix = path.suffix.casefold()

    if suffix == ".pdf":
        lines = read_pdf_lines(path)
        source = SOURCE_PDF
    elif suffix in PHOTO_SUFFIXES:
        if engine is None:
            raise DocumentError(
                f"{path.name}: для фотографии нужно распознавание, движок не задан"
            )
        lines = rows_from_observations(engine.read(path))
        source = SOURCE_PHOTO
    else:
        raise DocumentError(f"{path.name}: формат {suffix!r} не поддерживается")

    return ReadDocument(
        source=source, lines=tuple(lines), table=parse_lab_lines(lines)
    )
