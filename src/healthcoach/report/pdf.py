"""Печать отчёта в PDF.

WeasyPrint загружает системные библиотеки через dlopen в момент импорта.
На macOS они ставятся homebrew в каталог, которого нет в путях поиска по
умолчанию, и импорт падает с «cannot load library 'libgobject-2.0-0'».
Поэтому путь добавляется здесь, до импорта, — коуч не должен настраивать
окружение руками, чтобы получить отчёт.
"""

from __future__ import annotations

import html
import os
import re
from pathlib import Path

from healthcoach.report.sections import SECTIONS

LIBRARY_PATHS = ("/opt/homebrew/lib", "/usr/local/lib")
"""Куда homebrew кладёт pango и его зависимости: Apple Silicon и Intel."""

_BOLD_RE = re.compile(r"\*\*(.+?)\*\*")
_ITALIC_RE = re.compile(r"\*(.+?)\*")


class PdfBuildError(Exception):
    """PDF собрать не удалось."""


def _prepare_library_path() -> None:
    existing = os.environ.get("DYLD_FALLBACK_LIBRARY_PATH", "")
    parts = [p for p in LIBRARY_PATHS if Path(p).is_dir()]
    if not parts:
        return
    existing_parts = existing.split(":") if existing else []
    if all(p in existing_parts for p in parts):
        return  # уже подготовлено этим же процессом — не плодить дубли
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


def _format_paragraph(paragraph: str) -> str:
    """Экранировать абзац и перевести `**bold**`/`*italic*` модели в теги.

    Порядок обязателен: сначала экранирование HTML, потом разметка.
    Модель пишет текст, который печатается без просмотра человеком —
    если конвертировать раньше экранирования, всё, что в нём есть,
    вплоть до `<script>`, станет живой разметкой в документе, который
    берёт в руки клиент. Одиночные звёздочки, оставшиеся без пары, —
    не разметка, а мусор («2 * 3»), и в печать не идут.
    """
    escaped = html.escape(paragraph)
    escaped = _BOLD_RE.sub(r"<strong>\1</strong>", escaped)
    escaped = _ITALIC_RE.sub(r"<em>\1</em>", escaped)
    return escaped.replace("*", "")


def _format_paragraphs(text: str) -> list[str]:
    """Разбить текст раздела на абзацы, не склеивая и не теряя их."""
    return [_format_paragraph(p.strip()) for p in text.split("\n") if p.strip()]


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

    titles = {section.id: section.title for section in SECTIONS}
    paragraphs = {section.section_id: _format_paragraphs(section.text) for section in data.sections}
    template = templates.get_template("report_pdf.html")
    return template.render(data=data, charts=charts, titles=titles, paragraphs=paragraphs)
