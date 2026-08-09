"""Чтение строк текста из PDF-выгрузки.

Извлекаются строки, а не таблицы: разлинованные таблицы есть лишь у
части лабораторий, а у остальных извлечение таблиц даёт мусор — одну
склеенную колонку или три десятка пустых. Текстовые строки чисты у всех.
"""

from __future__ import annotations

from pathlib import Path

import pdfplumber


class PdfError(Exception):
    """PDF не прочитан."""


def read_pdf_lines(path: Path) -> list[str]:
    """Все строки текста документа, страница за страницей."""
    lines: list[str] = []
    try:
        with pdfplumber.open(path) as pdf:
            for page in pdf.pages:
                lines.extend((page.extract_text() or "").splitlines())
    except Exception as exc:  # pdfplumber поднимает разные типы
        raise PdfError(f"{path.name}: файл не прочитан как PDF ({exc})") from exc
    return lines
