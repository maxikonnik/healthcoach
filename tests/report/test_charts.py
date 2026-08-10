import re
import xml.etree.ElementTree as ET
from datetime import date

import pytest

from healthcoach.knowledge.references import Interval
from healthcoach.report.charts import ChartError, chart_svg
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


def test_points_stay_inside_the_canvas():
    """Точка за краем поля молча исчезнет при печати."""
    width, height = 400, 150
    svg = chart_svg(_series([18.0, 45.0, 200.0]), width=width, height=height)
    for cx, cy in re.findall(r'<circle cx="([\d.]+)" cy="([\d.]+)"', svg):
        assert 0 <= float(cx) <= width
        assert 0 <= float(cy) <= height


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
