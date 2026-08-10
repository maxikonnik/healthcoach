from healthcoach.knowledge.references import Interval
from healthcoach.report.scale import Scale, scale_for


def test_value_inside_corridor_sits_between_target_edges():
    scale = scale_for(75.0, Interval(60, 90), Interval(40, 100))
    assert scale is not None
    assert scale.target_from_pct <= scale.value_pct <= scale.target_to_pct
    assert not scale.value_outside


def test_value_below_corridor_sits_left_of_target_from():
    scale = scale_for(50.0, Interval(60, 90), Interval(40, 100))
    assert scale is not None
    assert scale.value_pct < scale.target_from_pct
    assert not scale.value_outside


def test_value_far_above_lab_range_is_pinned_to_the_right_edge():
    """Выброс не должен тянуть ось за собой — коридор иначе схлопнется."""
    scale = scale_for(500.0, Interval(12, 18), Interval(10, 20))
    assert scale is not None
    assert scale.value_outside
    assert scale.value_pct == 100


def test_value_far_below_axis_is_pinned_to_the_left_edge():
    scale = scale_for(-50.0, Interval(12, 18), Interval(10, 20))
    assert scale is not None
    assert scale.value_outside
    assert scale.value_pct == 0


def test_target_open_above_reaches_the_right_axis_edge():
    """«от 60» — полоса до конца оси, а не до какой-то произвольной точки."""
    scale = scale_for(70.0, Interval(60, None), Interval(40, 100))
    assert scale is not None
    assert scale.target_to_pct == 100


def test_target_open_below_reaches_the_left_axis_edge():
    scale = scale_for(70.0, Interval(None, 90), Interval(40, 100))
    assert scale is not None
    assert scale.target_from_pct == 0


def test_lab_range_without_target_still_builds_an_axis_but_draws_no_band():
    """Решение: лабораторный интервал — это норма бланка, а не коридор коуча.

    Рисовать его как зелёную целевую полосу значило бы выдать чужую (не
    коучем заданную) норму за решение из базы знаний — а инструмент не
    угадывает. Поэтому шкала строится (ось есть, маркер на своём месте),
    но полоса коридора нулевой ширины: рисовать её нечем.
    """
    scale = scale_for(75.0, None, Interval(60, 90))
    assert scale is not None
    assert scale.target_from_pct == scale.target_to_pct == 0


def test_single_open_bound_without_lab_range_gives_no_scale():
    """Одной границы недостаточно, чтобы честно построить ось."""
    assert scale_for(70.0, Interval(60, None), None) is None


def test_value_none_gives_no_scale():
    assert scale_for(None, Interval(60, 90), None) is None


def test_degenerate_axis_from_a_single_point_gives_no_scale():
    """target и lab_range сходятся в одной точке — оси попросту нет."""
    assert scale_for(70.0, Interval(70, 70), Interval(70, 70)) is None


def test_all_percentages_are_integers_even_for_non_round_numbers():
    scale = scale_for(41.7, Interval(33, 67), Interval(10, 90))
    assert scale is not None
    assert isinstance(scale.value_pct, int)
    assert isinstance(scale.target_from_pct, int)
    assert isinstance(scale.target_to_pct, int)
    for pct in (scale.value_pct, scale.target_from_pct, scale.target_to_pct):
        assert 0 <= pct <= 100


def test_axis_labels_carry_an_eight_percent_margin():
    scale = scale_for(75.0, Interval(60, 90), None)
    assert scale is not None
    assert scale.axis_low == 57.6
    assert scale.axis_high == 92.4


def test_bound_low_high_are_the_honest_endpoints_without_the_margin():
    """`bound_low`/`bound_high` — то, что попадёт на подпись оси; они не
    должны быть раздвинуты, в отличие от `axis_low`/`axis_high`."""
    scale = scale_for(75.0, Interval(60, 90), None)
    assert scale is not None
    assert scale.bound_low == 60
    assert scale.bound_high == 90


def test_scale_is_a_frozen_dataclass():
    scale = scale_for(75.0, Interval(60, 90), None)
    assert isinstance(scale, Scale)
