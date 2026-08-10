from datetime import date, datetime
from pathlib import Path

import pytest
from fastapi.templating import Jinja2Templates

from healthcoach.knowledge.coach import Coach
from healthcoach.knowledge.references import Interval
from healthcoach.report.data import Point, ReportData, Series
from healthcoach.report.pdf import PdfBuildError, render_report_html, report_pdf
from healthcoach.report.sections import SECTIONS
from healthcoach.storage.drafts import DraftSection

TEMPLATES_DIR = Path(__file__).parents[2] / "src" / "healthcoach" / "app" / "templates"


def _section(section_id: str, text: str) -> DraftSection:
    return DraftSection(
        id=1, snapshot_id=1, section_id=section_id,
        generated=text, edited="", finding_ids=(),
    )


def _data(sections=None, series=()) -> ReportData:
    return ReportData(
        client_name="Соловьёва Ирина Анатольевна",
        client_code="CL-0001",
        taken_on=date(2026, 9, 1),
        coach=Coach(name="Иконникова Екатерина", title="нутрициолог", signature=""),
        sections=tuple(sections or [_section("запрос", "Текст запроса.")]),
        findings=(),
        series=series,
        approved_at=datetime(2026, 9, 2, 10, 0),
    )


def test_pdf_is_produced():
    pdf = report_pdf("<html><body><p>тест</p></body></html>")
    assert pdf[:5] == b"%PDF-"
    assert len(pdf) > 500


def test_library_path_does_not_grow_without_bound(monkeypatch):
    """Долго живущее приложение вызывает report_pdf много раз в одном процессе.

    Переменная окружения наследуется каждым дочерним процессом, включая
    провайдера `claude -p` — раздувать её на каждый вызов нельзя.
    """
    import os

    monkeypatch.setenv("DYLD_FALLBACK_LIBRARY_PATH", "/some/other/path")
    report_pdf("<html><body><p>x</p></body></html>")
    after_first_call = os.environ["DYLD_FALLBACK_LIBRARY_PATH"]

    for _ in range(4):
        report_pdf("<html><body><p>x</p></body></html>")

    assert os.environ["DYLD_FALLBACK_LIBRARY_PATH"] == after_first_call
    assert after_first_call.count("/some/other/path") == 1


def test_cyrillic_survives_the_print():
    """Кириллица в PDF — то, ради чего выбран этот движок."""
    import pdfplumber, io

    pdf = report_pdf(
        '<html><head><meta charset="utf-8"></head><body>'
        "<p>Соловьёва Ирина — ферритин 18,0 нг/мл</p></body></html>"
    )
    with pdfplumber.open(io.BytesIO(pdf)) as doc:
        text = doc.pages[0].extract_text() or ""
    assert "Соловьёва" in text
    assert "нг/мл" in text


def test_page_breaks_are_honoured():
    """Отчёт на 5–10 страниц: разрывы должны работать, иначе это простыня."""
    import pdfplumber, io

    body = '<p>первая</p><div style="break-before:page"><p>вторая</p></div>'
    pdf = report_pdf(f'<html><head><meta charset="utf-8"></head><body>{body}</body></html>')
    with pdfplumber.open(io.BytesIO(pdf)) as doc:
        assert len(doc.pages) == 2


def test_broken_html_is_reported_not_swallowed():
    with pytest.raises(PdfBuildError):
        report_pdf(None)


def _series_with_dynamics() -> Series:
    return Series(
        analyte_id="ферритин",
        title="Ферритин",
        units="нг/мл",
        points=(
            Point(taken_on=date(2026, 3, 1), value=18.0),
            Point(taken_on=date(2026, 9, 1), value=45.0),
        ),
        target=Interval(low=30.0, high=200.0),
    )


def _series_without_dynamics() -> Series:
    return Series(
        analyte_id="витамин_д",
        title="Витамин Д",
        units="нг/мл",
        points=(Point(taken_on=date(2026, 9, 1), value=22.0),),
        target=None,
    )


def test_render_report_html_prints_every_section_the_title_page_and_disclaimer():
    """Прогоняет данные через реальный шаблон, а не HTML, написанный вручную.

    Каждый заголовок и текст раздела должны дойти до печати — брифовский
    словарь `titles` не должен быть закрыт заглушкой, а разделы не должны
    молча теряться.
    """
    sections = [_section(s.id, f"Текст раздела «{s.id}».") for s in SECTIONS]
    data = _data(sections=sections)
    templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

    html = render_report_html(data, templates)

    assert data.client_name in html
    assert data.coach.name in html
    for section in SECTIONS:
        assert section.title in html
        assert f"Текст раздела «{section.id}»." in html
    assert "не является медицинским" in html
    assert "Утверждён 02.09.2026" in html


def test_dynamics_chart_only_appears_in_the_dynamics_section():
    """График — только в «динамике» и только для ряда, где есть динамика.

    Ряд с одной точкой не должен породить фигуру: рисовать линию по одной
    точке значит показать клиенту динамику, которой нет.
    """
    sections = [_section(s.id, f"Текст раздела «{s.id}».") for s in SECTIONS]
    data = _data(sections=sections, series=(_series_with_dynamics(), _series_without_dynamics()))
    templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

    html = render_report_html(data, templates)

    assert html.count("<svg") == 1
    assert "Ферритин, нг/мл" in html
    assert "Витамин Д, нг/мл" not in html

    dynamics_index = SECTIONS.index(next(s for s in SECTIONS if s.id == "динамика"))
    dyn_start = html.index(SECTIONS[dynamics_index].title)
    next_title = SECTIONS[dynamics_index + 1].title
    dyn_end = html.index(next_title, dyn_start)

    assert "<svg" in html[dyn_start:dyn_end]
    assert "<svg" not in html[:dyn_start]
    assert "<svg" not in html[dyn_end:]
