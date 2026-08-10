from datetime import date, datetime

import pytest

from healthcoach.knowledge.coach import Coach
from healthcoach.knowledge.references import Interval
from healthcoach.report.data import Point, ReportData, Series
from healthcoach.report.pdf import PdfBuildError, report_pdf
from healthcoach.storage.drafts import DraftSection


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
