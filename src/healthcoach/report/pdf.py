"""Печать отчёта в PDF.

WeasyPrint загружает системные библиотеки через dlopen в момент импорта.
На macOS они ставятся homebrew в каталог, которого нет в путях поиска по
умолчанию, и импорт падает с «cannot load library 'libgobject-2.0-0'».
Поэтому путь добавляется здесь, до импорта, — коуч не должен настраивать
окружение руками, чтобы получить отчёт.
"""

from __future__ import annotations

import os
from pathlib import Path

from healthcoach.report.sections import SECTIONS

LIBRARY_PATHS = ("/opt/homebrew/lib", "/usr/local/lib")
"""Куда homebrew кладёт pango и его зависимости: Apple Silicon и Intel."""


class PdfBuildError(Exception):
    """PDF собрать не удалось."""


def _prepare_library_path() -> None:
    existing = os.environ.get("DYLD_FALLBACK_LIBRARY_PATH", "")
    parts = [p for p in LIBRARY_PATHS if Path(p).is_dir()]
    if not parts:
        return
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
    template = templates.get_template("report_pdf.html")
    return template.render(data=data, charts=charts, titles=titles)
