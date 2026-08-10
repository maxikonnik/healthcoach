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

from healthcoach.knowledge.references import Interval
from healthcoach.report.sections import SECTIONS
from healthcoach.scoring.findings import KIND_QUESTIONNAIRE

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


NOTHING = "—"
"""Чем печатается отсутствующая клетка таблицы. Тот же прочерк, которым
`llm/payload.py` печатает находку без значения."""


def _number(value: float) -> str:
    """Число так, как его печатают точки на графике: без хвоста «.0»."""
    return f"{value:g}"


def _interval_text(interval: Interval | None) -> str:
    """Коридор словами клиента: «60–90», «от 60», «до 30», прочерк.

    Границы, заданной с одной стороны, в базе знаний хватает («дефицит:
    [null, 30]»), а печатать «None–30» клиенту нельзя. Больше правил тут
    нет: чего в находке не посчитано, то и не печатается.
    """
    if interval is None:
        return NOTHING
    if interval.low is not None and interval.high is not None:
        return f"{_number(interval.low)}–{_number(interval.high)}"
    if interval.low is not None:
        return f"от {_number(interval.low)}"
    if interval.high is not None:
        return f"до {_number(interval.high)}"
    return NOTHING


def _indicator_rows(findings) -> list[dict[str, str]]:
    """Таблица ключевых показателей — числа, которые посчитал код.

    Спецификация, раздел 10, пункт 4: значение, лабораторный интервал,
    целевой коридор коуча. До этой таблицы отчёт не печатал ни одного
    числа из `ReportData.findings`: значения доходили до клиента только
    если модель перепечатала их в своём тексте, а `lab_range` не доходил
    вовсе — его не видела даже модель. Опечатка модели («180 нг/мл» вместо
    «18») печаталась бы без единого возражения.

    Находки опросника пропущены: у них не измерение, а степень и сумма
    баллов, и о них говорит «карта систем».

    Заметки в таблице нет намеренно: заметка коуча — рабочая подсказка
    себе, вплоть до фамилии и телефона врача. Наружу она не идёт
    (`privacy/findings.py`), и колонки для неё здесь нет.
    """
    rows = []
    for finding in findings:
        if finding.kind == KIND_QUESTIONNAIRE:
            continue
        value = NOTHING if finding.value is None else _number(finding.value)
        rows.append(
            {
                "title": finding.title,
                "value": f"{value} {finding.units}".strip(),
                "target": _interval_text(finding.target),
                "lab_range": _interval_text(finding.lab_range),
                "status": finding.status,
                "taken_on": finding.taken_on.strftime("%d.%m.%Y") if finding.taken_on else NOTHING,
            }
        )
    return rows


def _header_period(data) -> str:
    """Текст шапки: дата среза, а когда значения отчёта из разных дат — охват.

    Одна дата — тот же текст, что печатался всегда («Срез от X»); менять
    его нельзя, иначе отчёт по одному срезу перестал бы быть побайтово тем
    же документом, что печатался раньше (`data.covers_several_dates` для
    этого и заведено). Несколько дат — клиент должен видеть, что за чем
    стоит, а не читать пятимесячный анализ как сегодняшний.

    Формулировка называет вещи своими именами: «Анализы сданы с … по …».
    Отчёт читает не коуч, а клиент, и прежнее «Данные с … по …» не
    отличало дату забора крови от даты, когда отчёт был сделан.

    Диапазон берётся из дат самих находок (`Finding.taken_on`), а не из
    отдельного поля `ReportData`: это те же даты, что уходят в колонку
    таблицы показателей, — раздваивать источник незачем. Находки
    опросника из него исключены, как и из самой таблицы: их дата — дата
    среза, к которому подшита анкета, а шапка говорит про сдачу анализов.
    """
    if not data.covers_several_dates:
        return f"Срез от {data.taken_on.strftime('%d.%m.%Y')}"
    dates = sorted(
        {
            f.taken_on
            for f in data.findings
            if f.taken_on is not None and f.kind != KIND_QUESTIONNAIRE
        }
    )
    if not dates:
        return f"Срез от {data.taken_on.strftime('%d.%m.%Y')}"
    return (
        f"Анализы сданы с {dates[0].strftime('%d.%m.%Y')} "
        f"по {dates[-1].strftime('%d.%m.%Y')}"
    )


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
    return template.render(
        data=data,
        charts=charts,
        titles=titles,
        paragraphs=paragraphs,
        indicators=_indicator_rows(data.findings),
        header_period=_header_period(data),
    )
