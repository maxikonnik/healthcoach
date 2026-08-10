import re
import xml.etree.ElementTree as ET
from datetime import date

import pytest

from healthcoach.knowledge.references import Interval
from healthcoach.report.charts import (
    PADDING_BOTTOM,
    PADDING_LEFT,
    PADDING_RIGHT,
    PADDING_TOP,
    ChartError,
    chart_svg,
)
from healthcoach.report.data import Point, Series


def _series(values, target=Interval(60, 90)):
    points = tuple(
        Point(taken_on=date(2026, m, 1), value=v) for m, v in zip(range(3, 12), values)
    )
    return Series(
        analyte_id="ферритин", title="Ферритин", units="нг/мл",
        points=points, target=target,
    )


def test_svg_is_well_formed():
    svg = chart_svg(_series([18.0, 45.0, 70.0]))
    root = ET.fromstring(svg)
    assert root.tag.endswith("svg")


def test_a_point_per_measurement():
    svg = chart_svg(_series([18.0, 45.0, 70.0]))
    assert svg.count("<circle") == 3


def test_values_and_units_are_visible():
    svg = chart_svg(_series([18.0, 45.0]))
    assert "18" in svg
    assert "45" in svg
    assert "нг/мл" in svg


def test_target_corridor_is_drawn():
    svg = chart_svg(_series([18.0, 45.0], target=Interval(60, 90)))
    assert "<rect" in svg


def test_chart_without_a_target_still_draws():
    svg = chart_svg(_series([18.0, 45.0], target=None))
    ET.fromstring(svg)
    assert svg.count("<circle") == 2


def test_a_single_point_is_refused():
    """Одна точка — не динамика; нарисовать её значит соврать клиенту."""
    with pytest.raises(ChartError, match="одной точке"):
        chart_svg(_series([18.0]))


def test_equal_values_do_not_divide_by_zero():
    svg = chart_svg(_series([50.0, 50.0, 50.0], target=None))
    ET.fromstring(svg)
    assert svg.count("<circle") == 3


def test_points_stay_inside_the_plot_box():
    """Точка за краем поля молча исчезнет при печати.

    Границы — это поле рисования (за вычетом отступов под подписи), а не
    весь холст: точка может формально лежать внутри canvas и всё равно
    вылезать поверх подписи оси или дат.
    """
    width, height = 400, 150
    svg = chart_svg(_series([18.0, 45.0, 200.0]), width=width, height=height)
    for cx, cy in re.findall(r'<circle cx="([\d.]+)" cy="([\d.]+)"', svg):
        assert PADDING_LEFT <= float(cx) <= width - PADDING_RIGHT
        assert PADDING_TOP <= float(cy) <= height - PADDING_BOTTOM


def test_dates_are_shown_for_the_ends():
    svg = chart_svg(_series([18.0, 45.0, 70.0]))
    assert "03.2026" in svg
    assert "05.2026" in svg


def test_hostile_title_cannot_break_the_markup():
    """Название приходит из базы знаний коуча, но экранируется как чужое."""
    series = Series(
        analyte_id="x", title='<script>alert("взлом")</script>', units="ед",
        points=(Point(date(2026, 3, 1), 1.0), Point(date(2026, 4, 1), 2.0)),
        target=None,
    )
    svg = chart_svg(series)
    assert "<script>" not in svg
    ET.fromstring(svg)


def test_y_decreases_as_value_increases():
    """Растущий ряд должен идти вверх на бумаге, а не вниз."""
    svg = chart_svg(_series([18.0, 45.0, 70.0]))
    ys = [float(cy) for _, cy in re.findall(r'<circle cx="([\d.]+)" cy="([\d.]+)"', svg)]
    assert ys[0] > ys[1] > ys[2]


def test_x_strictly_increases_across_points():
    """Точки идут по времени слева направо, а не складываются в одну колонку."""
    svg = chart_svg(_series([18.0, 45.0, 70.0]))
    xs = [float(cx) for cx, _ in re.findall(r'<circle cx="([\d.]+)" cy="([\d.]+)"', svg)]
    assert xs[0] < xs[1] < xs[2]


def test_band_edges_align_with_corresponding_values():
    """Верх полосы — это верхняя граница коридора, низ — нижняя.

    Перепутанные края дают либо отрицательную высоту (полоса невалидна и
    молча исчезает при печати), либо полосу с координатами, не совпадающими
    с точками тех же значений.
    """
    target = Interval(60, 90)
    series = _series([60.0, 90.0, 75.0], target=target)
    svg = chart_svg(series)

    rect = re.search(r'<rect x="[\d.]+" y="([\d.]+)" width="[\d.]+" height="([\d.]+)"', svg)
    assert rect is not None
    rect_top = float(rect.group(1))
    rect_height = float(rect.group(2))
    assert rect_height >= 0
    rect_bottom = rect_top + rect_height

    circles = re.findall(r'<circle cx="([\d.]+)" cy="([\d.]+)"', svg)
    cy_at_low = float(circles[0][1])   # значение 60.0 — нижняя граница коридора
    cy_at_high = float(circles[1][1])  # значение 90.0 — верхняя граница коридора

    assert rect_top == pytest.approx(cy_at_high, abs=0.5)
    assert rect_bottom == pytest.approx(cy_at_low, abs=0.5)


def test_kalium_axis_labels_bracket_real_values():
    """Ось не должна врать: подписи — это правда о коридоре, а не отступ.

    Коридор калия [4.0, 4.5] по данным knowledge/references/derived.yaml,
    точки 4.1 и 4.3.
    """
    series = _series([4.1, 4.3], target=Interval(4.0, 4.5))
    svg = chart_svg(series)
    labels = [
        float(m) for m in re.findall(r'<text x="4" y="[\d.]+"[^>]*>([-\d.]+)</text>', svg)
    ]
    assert len(labels) == 2
    top_label, bottom_label = labels
    assert bottom_label <= 4.1 and 4.3 <= top_label


def test_point_position_matches_printed_axis_on_ferritin_scale():
    """Позиция точки должна совпадать с тем, что напечатано на оси.

    Ось читается между самими подписями, а не между краями поля: между
    краями лежит размах с запасом (`_scale`), а подписаны им границы
    данных (`_data_bounds`), и клиент, приложивший линейку к подписям,
    получал не то число, что стоит у точки. Прежняя версия этого теста
    мерила между краями поля и проходила только потому, что коридор калия
    шириной ровно 0.5 гасил расхождение. На настоящих данных ферритина —
    точки 18 и 45, коридор 60–90 — та же проверка читала для точки с
    подписью «18» значение 24, то есть промах в 120 допусков.

    Допуск 0.05 нг/мл — доля процента от размаха.
    """
    values = [18.0, 45.0]
    series = _series(values, target=Interval(60, 90))
    svg = chart_svg(series)

    labels = [
        (float(y), float(text))
        for y, text in re.findall(
            r'<text x="4" y="([\d.]+)"[^>]*>([-\d.]+)</text>', svg
        )
    ]
    assert len(labels) == 2
    (top_y, top_label), (bottom_y, bottom_label) = labels
    circles = re.findall(r'<circle cx="([\d.]+)" cy="([\d.]+)"', svg)

    for (_, cy), value in zip(circles, values):
        frac = (float(cy) - top_y) / (bottom_y - top_y)
        read_value = top_label - frac * (top_label - bottom_label)
        assert read_value == pytest.approx(value, abs=0.05)


def test_small_values_axis_labels_are_distinct():
    """0.05 и 0.09 не должны обе округлиться до одной и той же подписи «0»."""
    series = _series([0.05, 0.09], target=None)
    svg = chart_svg(series)
    labels = re.findall(r'<text x="4" y="[\d.]+"[^>]*>([-\d.]+)</text>', svg)
    assert len(labels) == 2
    assert labels[0] != labels[1]
    assert "0" not in labels and "0.0" not in labels


def test_a_bound_just_below_zero_is_printed_as_zero_not_negative_zero():
    """Подпись «-0.0» — минус там, где минуса нет.

    Прежняя версия брала коридор [0.0, 1.0]: при таком размахе подпись
    печатается с одним знаком, «-0» не возникает вовсе, и снятие минуса
    можно было выключить целиком — тест оставался зелёным. Минус
    появляется только когда граница отрицательна, но округляется в ноль:
    −0.04 при размахе 5 печатается как «-0.0».
    """
    series = _series([-0.04, 5.0], target=None)
    svg = chart_svg(series)
    labels = re.findall(r'<text x="4" y="[\d.]+"[^>]*>([-\d.]+)</text>', svg)
    assert labels == ["5.0", "0.0"]


def test_hostile_units_cannot_break_the_markup():
    """Единицы приходят из базы знаний коуча — и экранируются как чужое.

    Та же причина, что у названия: YAML коуч правит руками, а SVG уходит
    в документ, который берёт в руки клиент.
    """
    series = Series(
        analyte_id="x", title="Показатель",
        units='</text><script>alert("взлом")</script>',
        points=(Point(date(2026, 3, 1), 1.0), Point(date(2026, 4, 1), 2.0)),
        target=None,
    )
    svg = chart_svg(series)
    assert "<script>" not in svg
    ET.fromstring(svg)


def test_an_inverted_corridor_is_refused_before_it_reaches_the_chart():
    """`оптимум: [90, 60]` — опечатка коуча, и она не должна дойти до печати.

    Полоса коридора получала высоту −116.7; движок печати выбрасывает
    невалидную геометрию, и клиент видел график без коридора, а нигде
    ни одной ошибки. Интервал не создаётся вовсе.
    """
    with pytest.raises(ValueError, match="перевёрнут"):
        Interval(90, 60)


def test_half_open_corridor_still_draws_a_band():
    """Открытый коридор (например, «дефицит: от X») не должен прятать зону.

    ferritin.yaml уже использует такие интервалы; молчаливая пустота без
    полосы не показывает клиенту, где проходит граница.
    """
    series = _series([65.0, 80.0], target=Interval(60, None))
    svg = chart_svg(series)
    assert "<rect" in svg
