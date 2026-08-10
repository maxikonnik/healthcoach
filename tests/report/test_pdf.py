from datetime import date, datetime
from pathlib import Path

import pytest
from fastapi.templating import Jinja2Templates

from healthcoach.knowledge.coach import Coach
from healthcoach.knowledge.references import Interval
from healthcoach.report.data import Point, ReportData, Series
from healthcoach.report.pdf import PdfBuildError, render_report_html, report_pdf
from healthcoach.report.sections import SECTIONS
from healthcoach.scoring.findings import (
    KIND_ANALYTE,
    KIND_DERIVED,
    KIND_QUESTIONNAIRE,
    Finding,
)
from healthcoach.storage.drafts import DraftSection

TEMPLATES_DIR = Path(__file__).parents[2] / "src" / "healthcoach" / "app" / "templates"


def _section(section_id: str, text: str) -> DraftSection:
    return DraftSection(
        id=1, snapshot_id=1, section_id=section_id,
        generated=text, edited="", finding_ids=(),
    )


def _data(sections=None, series=(), findings=(), covers_several_dates=False) -> ReportData:
    return ReportData(
        client_name="Соловьёва Ирина Анатольевна",
        client_code="CL-0001",
        taken_on=date(2026, 9, 1),
        coach=Coach(name="Иконникова Екатерина", title="нутрициолог", signature=""),
        sections=tuple(sections or [_section("запрос", "Текст запроса.")]),
        findings=tuple(findings),
        series=series,
        approved_at=datetime(2026, 9, 2, 10, 0),
        covers_several_dates=covers_several_dates,
    )


def _finding(**overrides) -> Finding:
    base = dict(
        kind=KIND_ANALYTE,
        subject_id="ферритин",
        title="Ферритин",
        value=18.0,
        units="нг/мл",
        status="дефицит",
        target=Interval(60, 90),
        lab_range=Interval(10, 120),
        note=None,
        rule_missing=False,
    )
    base.update(overrides)
    return Finding(**base)


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


def _all_sections():
    return [_section(s.id, f"Текст раздела «{s.id}».") for s in SECTIONS]


def _rendered_with(findings, covers_several_dates=False):
    data = _data(
        sections=_all_sections(), findings=findings, covers_several_dates=covers_several_dates
    )
    templates = Jinja2Templates(directory=str(TEMPLATES_DIR))
    return render_report_html(data, templates)


def test_key_indicators_table_prints_the_numbers_the_code_computed():
    """Спецификация, раздел 10, пункт 4: значение, лабораторный интервал,
    целевой коридор коуча.

    До этой таблицы отчёт не печатал ни одного числа из `data.findings`:
    значение доходило до клиента, только если модель перепечатала его в
    своём тексте, а `lab_range` не доходил вовсе — его не видела даже
    модель. Опечатка модели («180 нг/мл» вместо «18») печаталась бы без
    единого возражения.
    """
    html = _rendered_with([_finding()])

    assert "Ферритин" in html
    assert "18 нг/мл" in html
    assert "60–90" in html
    assert "10–120" in html
    assert "дефицит" in html


def test_key_indicators_table_stands_in_the_indicators_section_under_the_text():
    html = _rendered_with([_finding()])

    indicators_index = SECTIONS.index(next(s for s in SECTIONS if s.id == "показатели"))
    start = html.index(SECTIONS[indicators_index].title)
    end = html.index(SECTIONS[indicators_index + 1].title, start)
    section = html[start:end]

    assert '<table class="indicators">' in section
    assert html.count('<table class="indicators">') == 1
    assert section.index("Текст раздела «показатели».") < section.index("<table")


def test_key_indicators_table_covers_derived_findings_too():
    """Раздел «показатели» стоит и на производных — они такие же числа."""
    html = _rendered_with(
        [
            _finding(),
            _finding(
                kind=KIND_DERIVED,
                subject_id="кальций_калий",
                title="Соотношение кальций/калий",
                value=5.25,
                units="",
                status="выше целевого",
                target=Interval(2.0, 4.0),
                lab_range=None,
            ),
        ]
    )
    assert "Соотношение кальций/калий" in html
    assert "5.25" in html
    assert "2–4" in html


def test_questionnaire_findings_are_not_rows_of_the_indicators_table():
    """У опросника не измерение, а степень и сумма баллов: о них говорит
    «карта систем», и в таблице показателей им места нет."""
    html = _rendered_with(
        [
            _finding(
                kind=KIND_QUESTIONNAIRE,
                subject_id="obraz_zizni/весь",
                title="ОБРАЗ ЖИЗНИ",
                value=8,
                units="баллов",
                status="высокая",
                target=None,
                lab_range=None,
                answered=10,
                total=10,
            )
        ]
    )
    assert '<table class="indicators">' not in html
    assert "8 баллов" not in html


def test_missing_pieces_of_a_finding_print_a_dash_not_an_invented_number():
    """Чего код не посчитал, того таблица не выдумывает."""
    html = _rendered_with(
        [
            _finding(
                value=None,
                status="значение не распознано",
                target=None,
                lab_range=None,
                rule_missing=True,
            )
        ]
    )
    assert "<td>— нг/мл</td>" in html
    assert html.count("<td>—</td>") == 2
    assert "значение не распознано" in html


def test_a_half_open_corridor_prints_a_bound_not_the_word_none():
    """«дефицит: [null, 30]» — правильная запись в базе знаний, и печатать
    её как «None–30» клиенту нельзя."""
    html = _rendered_with([_finding(target=Interval(60, None), lab_range=Interval(None, 30))])
    assert "None" not in html
    assert "от 60" in html
    assert "до 30" in html


def test_hostile_finding_text_cannot_break_the_markup_of_the_table():
    """Маска на текст бланка стоит в сборке отчёта; шаблон — второй слой."""
    html = _rendered_with([_finding(title='<script>alert("взлом")</script>')])
    assert "<script>" not in html
    assert "&lt;script&gt;" in html


def test_multi_paragraph_section_prints_a_paragraph_per_paragraph():
    """Раздел на несколько абзацев не должен печататься одной простынёй.

    Ничто этого не держало: склеивание разбиения в один блок проходило
    весь набор.
    """
    html = _rendered("Первый абзац.\nВторой абзац.\nТретий абзац.")
    assert "<p>Первый абзац.</p>" in html
    assert "<p>Второй абзац.</p>" in html
    assert "<p>Третий абзац.</p>" in html


def test_render_drops_a_series_without_dynamics_even_when_the_engine_would_draw(
    monkeypatch,
):
    """Первый из трёх сторожей графика — отбор в `render_report_html`.

    Их три: отбор здесь, отказ `chart_svg` по одной точке и условие в
    шаблоне. Пока каждый проверялся только через общий результат, любой
    из трёх можно было снять поодиночке — двое оставшихся держали набор
    зелёным. Здесь движок печати заведомо согласен рисовать, так что
    отвечает ровно отбор.
    """
    import healthcoach.report.charts as charts

    monkeypatch.setattr(charts, "chart_svg", lambda series, **kw: "<svg>подделка</svg>")
    data = _data(sections=_all_sections(), series=(_series_without_dynamics(),))
    templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

    html = render_report_html(data, templates)

    assert "<svg" not in html
    assert "Витамин Д, нг/мл" not in html


def test_a_series_the_engine_refused_prints_neither_figure_nor_caption(monkeypatch):
    """Третий сторож — условие в шаблоне.

    Ряд динамику имеет, а график по нему не построился. Без условия
    шаблон напечатал бы пустую фигуру с подписью «Ферритин, нг/мл» —
    подпись к графику, которого нет.
    """
    import healthcoach.report.charts as charts

    def refuse(series, **kw):
        raise charts.ChartError("построить нельзя")

    monkeypatch.setattr(charts, "chart_svg", refuse)
    data = _data(sections=_all_sections(), series=(_series_with_dynamics(),))
    templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

    html = render_report_html(data, templates)

    assert "<svg" not in html
    assert "Ферритин, нг/мл" not in html


def test_signature_is_printed_after_the_last_section_when_set():
    sections = [_section(s.id, f"Текст раздела «{s.id}».") for s in SECTIONS]
    data = ReportData(
        client_name="Соловьёва Ирина Анатольевна",
        client_code="CL-0001",
        taken_on=date(2026, 9, 1),
        coach=Coach(name="Иконникова Екатерина", title="нутрициолог", signature="С уважением, Екатерина"),
        sections=tuple(sections),
        findings=(),
        series=(),
        approved_at=datetime(2026, 9, 2, 10, 0),
    )
    templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

    html = render_report_html(data, templates)

    last_section_title = SECTIONS[-1].title
    assert "С уважением, Екатерина" in html
    assert html.index(last_section_title) < html.index("С уважением, Екатерина")
    assert html.index("С уважением, Екатерина") < html.index("не является медицинским")


def test_signature_prints_nothing_extra_when_blank():
    """coach.yaml поставляется с пустой подписью — лишнего заголовка или пустой строки быть не должно."""
    data = _data()
    templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

    html = render_report_html(data, templates)

    assert 'class="signature"' not in html


def _rendered(text: str) -> str:
    data = _data(sections=[_section("запрос", text)])
    templates = Jinja2Templates(directory=str(TEMPLATES_DIR))
    return render_report_html(data, templates)


def test_bold_markdown_becomes_strong():
    html = _rendered("**Ферритин: 18,0 нг/мл**")
    assert "<strong>Ферритин: 18,0 нг/мл</strong>" in html
    assert "**" not in html


def test_italic_markdown_becomes_em():
    html = _rendered("*курсив*")
    assert "<em>курсив</em>" in html


def test_lone_asterisk_does_not_survive():
    html = _rendered("5 * 3 = 15")
    assert "*" not in html


def test_html_is_escaped_before_markdown_is_converted():
    """Модель пишет то, что не проверено человеком, — экранирование обязано быть первым шагом.

    Иначе `<script>` из текста модели станет живой разметкой в документе,
    который берёт в руки клиент.
    """
    html = _rendered("<script>alert(1)</script> **жирный**")
    assert "<script>alert(1)</script>" not in html
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in html
    assert "<strong>жирный</strong>" in html


def test_plain_paragraph_is_unchanged():
    html = _rendered("Обычный текст без разметки.")
    assert "<p>Обычный текст без разметки.</p>" in html


# Task 7: даты в клиентском PDF.


def test_single_date_report_has_no_date_column_and_the_old_header():
    """Хард-требование: отчёт по одному сроку не меняется ни в чём.

    Мутация «сделать колонку безусловной» ломает именно этот тест — им
    проверено то немногое, что должно остаться прежним побайтово.
    """
    html = _rendered_with([_finding(taken_on=date(2026, 8, 20))], covers_several_dates=False)

    assert "Дата сдачи" not in html
    assert "Срез от 01.09.2026" in html
    assert "Анализы сданы" not in html


def test_multi_date_report_shows_a_date_per_row_and_the_span_in_the_header():
    html = _rendered_with(
        [
            _finding(taken_on=date(2026, 3, 1)),
            _finding(
                subject_id="витамин_д",
                title="Витамин Д",
                value=22.0,
                units="нг/мл",
                status="в пределах нормы",
                target=Interval(30, 60),
                lab_range=Interval(10, 100),
                taken_on=date(2026, 8, 25),
            ),
        ],
        covers_several_dates=True,
    )

    # Клиент не коуч: «Дата» и «Данные с» ни о чём ему не говорили — из
    # шапки нельзя было понять, дата это забора крови или изготовления
    # отчёта.
    assert "<th>Дата сдачи анализа</th>" in html
    assert "<td>01.03.2026</td>" in html
    assert "<td>25.08.2026</td>" in html
    assert "Анализы сданы с 01.03.2026 по 25.08.2026" in html
    assert "Срез от" not in html


def test_pdf_builds_for_a_single_date_report():
    import io

    import pdfplumber

    data = _data(sections=_all_sections(), findings=[_finding(taken_on=date(2026, 8, 20))])
    templates = Jinja2Templates(directory=str(TEMPLATES_DIR))
    html = render_report_html(data, templates)

    pdf = report_pdf(html)

    with pdfplumber.open(io.BytesIO(pdf)) as doc:
        text = "\n".join(page.extract_text() or "" for page in doc.pages)
    assert "Срез от 01.09.2026" in text
    assert "Дата" not in text


def test_pdf_builds_for_a_multi_date_report_with_the_date_column():
    import io

    import pdfplumber

    data = _data(
        sections=_all_sections(),
        findings=[
            _finding(taken_on=date(2026, 3, 1)),
            _finding(
                subject_id="витамин_д",
                title="Витамин Д",
                value=22.0,
                units="нг/мл",
                status="в пределах нормы",
                target=Interval(30, 60),
                lab_range=Interval(10, 100),
                taken_on=date(2026, 8, 25),
            ),
        ],
        covers_several_dates=True,
    )
    templates = Jinja2Templates(directory=str(TEMPLATES_DIR))
    html = render_report_html(data, templates)

    pdf = report_pdf(html)

    with pdfplumber.open(io.BytesIO(pdf)) as doc:
        text = "\n".join(page.extract_text() or "" for page in doc.pages)
    assert "Анализы сданы с 01.03.2026 по 25.08.2026" in text
    assert "Дата сдачи анализа" in text


def test_header_span_names_the_lab_dates_only_not_the_questionnaire_date():
    """Шапка обещает клиенту даты сдачи анализов — значит дата анкеты её
    не расширяет. Анкета несёт дату своего среза (правило 3), и попади
    она в диапазон, «анализы сданы с 01.03» было бы неправдой."""
    from healthcoach.scoring.findings import KIND_QUESTIONNAIRE

    html = _rendered_with(
        [
            _finding(taken_on=date(2026, 8, 20)),
            _finding(
                subject_id="витамин_д",
                title="Витамин Д",
                value=22.0,
                units="нг/мл",
                taken_on=date(2026, 8, 25),
            ),
            _finding(
                kind=KIND_QUESTIONNAIRE,
                subject_id="obraz_zizni/весь",
                title="ОБРАЗ ЖИЗНИ",
                value=8.0,
                units="баллов",
                status="в пределах нормы",
                target=None,
                lab_range=None,
                taken_on=date(2026, 3, 1),
            ),
        ],
        covers_several_dates=True,
    )

    assert "Анализы сданы с 20.08.2026 по 25.08.2026" in html
    assert "01.03.2026" not in html
