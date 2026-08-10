from healthcoach.knowledge.references import Interval
from healthcoach.report import findings_view as fv
from healthcoach.report.findings_view import FindingsView, Group, Row, build_view
from healthcoach.report.pdf import interval_text
from healthcoach.scoring.findings import KIND_ANALYTE, KIND_QUESTIONNAIRE, Finding
from healthcoach.scoring.references import STATUS_DEFICIT, STATUS_NO_RULE, STATUS_WITHIN


def _finding(**overrides):
    defaults = dict(
        kind=KIND_ANALYTE,
        subject_id="vitd",
        title="Витамин D",
        value=18.0,
        units="нг/мл",
        status=STATUS_DEFICIT,
        target=Interval(30, 50),
        lab_range=Interval(10, 100),
        note=None,
        rule_missing=False,
    )
    defaults.update(overrides)
    return Finding(**defaults)


def test_deficit_finding_goes_to_attention_with_bad_tone():
    view = build_view([_finding(status=STATUS_DEFICIT)])
    assert len(view.attention.rows) == 1
    assert view.attention.rows[0].tone == "bad"
    assert view.normal.rows == ()
    assert view.unjudged.rows == ()


def test_within_target_finding_goes_to_normal_with_ok_tone():
    view = build_view([_finding(status=STATUS_WITHIN, value=40.0)])
    assert view.attention.rows == ()
    assert len(view.normal.rows) == 1
    assert view.normal.rows[0].tone == "ok"


def test_no_rule_finding_goes_to_unjudged_and_lists_missing_rule():
    finding = _finding(
        status=STATUS_NO_RULE,
        title="Неизвестный показатель",
        target=None,
        lab_range=None,
        rule_missing=True,
    )
    view = build_view([finding])
    assert len(view.unjudged.rows) == 1
    assert view.unjudged.rows[0].tone == "muted"
    assert view.missing_rules == ("Неизвестный показатель",)


def test_questionnaire_finding_stays_out_of_attention_even_with_severe_degree():
    finding = _finding(
        kind=KIND_QUESTIONNAIRE,
        subject_id="dass/тревога",
        title="DASS — тревога",
        value=30.0,
        units="баллов",
        status="тяжелая",
        target=None,
        lab_range=None,
    )
    view = build_view([finding])
    assert view.attention.rows == ()
    assert view.unjudged.rows == ()
    assert view.normal.rows == ()
    assert len(view.questionnaire.rows) == 1
    assert view.questionnaire.rows[0].tone == "bad"


def test_questionnaire_low_degree_gets_warn_tone():
    finding = _finding(
        kind=KIND_QUESTIONNAIRE,
        subject_id="dass/тревога",
        title="DASS — тревога",
        value=5.0,
        units="баллов",
        status="низкая",
        target=None,
        lab_range=None,
    )
    view = build_view([finding])
    assert view.questionnaire.rows[0].tone == "warn"


def test_order_within_group_matches_input_order():
    first = _finding(status=STATUS_DEFICIT, title="А")
    second = _finding(status=STATUS_DEFICIT, title="Б")
    view = build_view([first, second])
    assert [row.finding.title for row in view.attention.rows] == ["А", "Б"]


def test_empty_groups_are_present_but_empty():
    view = build_view([])
    assert isinstance(view, FindingsView)
    assert view.attention == Group("Требуют внимания", ())
    assert view.normal == Group("В норме", ())
    assert view.unjudged == Group("Оценить не удалось", ())
    assert view.questionnaire == Group("Шкалы опросника", ())
    assert view.missing_rules == ()


def test_target_and_lab_text_reuse_the_pdf_interval_formatter():
    finding = _finding(target=Interval(30, None), lab_range=Interval(None, 100))
    row = build_view([finding]).attention.rows[0]
    assert row.target_text == interval_text(finding.target)
    assert row.lab_text == interval_text(finding.lab_range)
    assert row.target_text == "от 30"
    assert row.lab_text == "до 100"


def test_value_text_includes_units_and_dash_when_value_is_missing():
    present = build_view([_finding(value=18.0, units="нг/мл")]).attention.rows[0]
    assert present.value_text == "18 нг/мл"
    missing = build_view([_finding(value=None, units="нг/мл")]).attention.rows[0]
    assert missing.value_text == "— нг/мл"


def test_axis_end_labels_are_the_honest_unpadded_bounds():
    finding = _finding(
        status=STATUS_WITHIN,
        value=75.0,
        target=Interval(60, 90),
        lab_range=Interval(10, 120),
    )
    row = build_view([finding]).normal.rows[0]
    assert row.scale is not None
    # Отступ у самой шкалы честно раздвинут — подписи концов оси не должны
    # быть им заражены, иначе на странице появятся числа вроде «1.2».
    assert row.scale.axis_low != 10
    assert row.scale.axis_high != 120
    assert row.axis_low_text == "10"
    assert row.axis_high_text == "120"


def test_axis_labels_are_empty_when_there_is_no_scale():
    finding = _finding(value=70.0, target=Interval(60, None), lab_range=None)
    row = build_view([finding]).attention.rows[0]
    assert row.scale is None
    assert row.axis_low_text == ""
    assert row.axis_high_text == ""


def test_severity_lookup_delegates_to_the_public_scoring_function(monkeypatch):
    """Группировка должна брать тяжесть из scoring.findings, а не считать её заново."""
    monkeypatch.setattr(fv, "severity", lambda status: 0)
    finding = _finding(status=STATUS_WITHIN, value=40.0)  # обычно ушла бы в normal
    view = build_view([finding])
    assert len(view.attention.rows) == 1
    assert view.normal.rows == ()


def test_interval_formatting_delegates_to_the_public_pdf_function(monkeypatch):
    """target_text/lab_text не должны быть второй копией форматирования PDF."""
    monkeypatch.setattr(fv, "interval_text", lambda interval: "PATCHED")
    row = build_view([_finding()]).attention.rows[0]
    assert row.target_text == "PATCHED"
    assert row.lab_text == "PATCHED"
