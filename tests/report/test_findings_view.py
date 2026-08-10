import pytest

from healthcoach.knowledge.references import Interval
from healthcoach.report import findings_view as fv
from healthcoach.report.findings_view import FindingsView, Group, Row, build_view
from healthcoach.report.pdf import interval_text
from healthcoach.report.scale import Scale
from healthcoach.scoring.findings import KIND_ANALYTE, KIND_QUESTIONNAIRE, Finding
from healthcoach.scoring.references import (
    STATUS_ABOVE,
    STATUS_BELOW,
    STATUS_DEFICIT,
    STATUS_EXCESS,
    STATUS_NOT_COMPUTED,
    STATUS_NO_RULE,
    STATUS_NO_VALUE,
    STATUS_UNIT_MISMATCH,
    STATUS_WITHIN,
)


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


def test_axis_labels_follow_scale_for_bound_selection_not_a_second_copy(monkeypatch):
    """Доказательство, что подписи берутся из `Scale.bound_low/bound_high`,
    а не пересчитывают отбор границ заново: если бы `findings_view` держал
    вторую копию правила, патч `scale_for` на эти подписи бы не повлиял.
    """
    patched = Scale(
        value_pct=50,
        target_from_pct=40,
        target_to_pct=60,
        value_outside=False,
        bound_low=1.0,
        bound_high=999.0,
        axis_low=1.0,
        axis_high=999.0,
    )
    monkeypatch.setattr(fv, "scale_for", lambda value, target, lab_range: patched)
    row = build_view([_finding()]).attention.rows[0]
    assert row.axis_low_text == "1"
    assert row.axis_high_text == "999"


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


# Шкала — утверждение инструмента «я оценил это значение». Рисуется только
# там, где оценка действительно состоялась.


def test_unit_mismatch_draws_no_scale_even_though_a_lab_range_is_attached():
    """Единицы не сошлись: `lab_range` пришёл в единицах референса, а
    `value`/`units` — в единицах бланка. Шкала по ним нарисовала бы маркер
    в чужой системе координат под плашкой «оценить не удалось»."""
    finding = _finding(
        title="Кальций",
        status=STATUS_UNIT_MISMATCH,
        value=2.4,
        units="ммоль/л",
        target=None,
        lab_range=Interval(8.5, 10.5),
        rule_missing=True,
    )
    row = build_view([finding]).unjudged.rows[0]
    assert row.scale is None
    assert row.axis_low_text == ""
    assert row.axis_high_text == ""


def test_no_target_for_this_sex_and_age_draws_no_scale():
    """Показатель распознан, `lab_range` есть, но коридора для этого пола и
    возраста нет — оценки не было, значит и шкалы быть не должно."""
    finding = _finding(
        title="Ферритин",
        status=STATUS_NO_RULE,
        value=30.0,
        target=None,
        lab_range=Interval(10, 120),
        rule_missing=True,
    )
    row = build_view([finding]).unjudged.rows[0]
    assert row.scale is None
    assert row.axis_low_text == ""


@pytest.mark.parametrize(
    "status",
    [STATUS_UNIT_MISMATCH, STATUS_NO_RULE, STATUS_NOT_COMPUTED, STATUS_NO_VALUE],
)
def test_unjudged_status_draws_no_scale_whatever_the_flags_say(status):
    """Право рисовать шкалу даёт статус, а не флаг `rule_missing`.

    Флаг означает «в базе знаний чего-то не хватает» и поднят на четырёх
    разных путях (см. `AnalyteVerdict.title_from_document`) — это не то же
    самое, что «оценки не было». Сверять по нему значило бы поставить
    рисование шкалы в зависимость от чужого признака, который завтра
    поднимут или не поднимут по своей причине.
    """
    finding = _finding(
        status=status,
        value=2.4,
        target=Interval(2, 3),
        lab_range=Interval(1, 5),
        rule_missing=False,
    )
    (row,) = build_view([finding]).unjudged.rows
    assert row.scale is None
    assert row.axis_low_text == ""


@pytest.mark.parametrize(
    "status",
    [STATUS_DEFICIT, STATUS_BELOW, STATUS_WITHIN, STATUS_ABOVE, STATUS_EXCESS],
)
def test_judged_status_still_gets_its_scale(status):
    """Обратная сторона запрета: там, где оценка состоялась, шкала есть."""
    finding = _finding(status=status, value=40.0, rule_missing=True)
    rows = build_view([finding])
    (row,) = rows.attention.rows or rows.normal.rows
    assert row.scale is not None
    assert row.axis_low_text == "10"


# Списки для базы знаний. `rule_missing` поднят на четырёх разных путях и
# в один список их сваливать нельзя: каждый путь просит своей работы, а
# один из них не просит никакой.


def test_unit_mismatch_is_listed_as_units_work_not_as_a_missing_rule():
    """Правило для кальция написано — не сошлись единицы. Отправлять коуча
    писать правило, которое она уже написала, — ровно та ошибка, которой в
    этом списке быть не должно."""
    finding = _finding(
        title="Кальций",
        status=STATUS_UNIT_MISMATCH,
        value=2.4,
        units="ммоль/л",
        target=None,
        lab_range=Interval(8.5, 10.5),
        rule_missing=True,
    )
    view = build_view([finding])
    assert view.unit_mismatches == ("Кальций",)
    assert view.missing_rules == ()


def test_unknown_indicator_is_listed_as_a_missing_rule():
    finding = _finding(
        title="Гомоцистеин",
        status=STATUS_NO_RULE,
        target=None,
        lab_range=None,
        rule_missing=True,
        title_from_document=True,
    )
    view = build_view([finding])
    assert view.missing_rules == ("Гомоцистеин",)
    assert view.unit_mismatches == ()


def test_missing_target_for_this_sex_and_age_is_also_knowledge_base_work():
    """Показатель распознан, но целевого коридора для этого пола и возраста
    в файле нет — правило всё равно дописывать в knowledge/references/."""
    finding = _finding(
        title="Ферритин",
        status=STATUS_NO_RULE,
        value=30.0,
        target=None,
        lab_range=Interval(10, 120),
        rule_missing=True,
    )
    assert build_view([finding]).missing_rules == ("Ферритин",)


def test_blocked_derived_index_asks_for_no_knowledge_base_work_at_all():
    """Производный индекс не посчитан из-за операнда, у которого своя
    беда. Правило индекса на месте; называть его в списке пропущенных
    правил — послать коуча чинить не то."""
    finding = _finding(
        title="Соотношение кальций/калий",
        status=STATUS_NOT_COMPUTED,
        value=None,
        units="",
        target=Interval(2, 3),
        lab_range=None,
        rule_missing=True,
    )
    view = build_view([finding])
    assert view.missing_rules == ()
    assert view.unit_mismatches == ()


def test_unparsed_value_asks_for_no_knowledge_base_work_either():
    finding = _finding(
        title="Что-то с бланка",
        status=STATUS_NO_VALUE,
        value=None,
        target=None,
        lab_range=None,
        rule_missing=True,
    )
    view = build_view([finding])
    assert view.missing_rules == ()
    assert view.unit_mismatches == ()


# Граница групп. Всё, что тяжелее «в норме», должно быть видно сразу, а не
# под свёрнутым `<details>` — иначе экран прячет то, ради чего он сделан.


@pytest.mark.parametrize("status", [STATUS_ABOVE, STATUS_BELOW, "неведомый статус"])
def test_severity_one_stays_in_attention_and_out_of_the_collapsed_fold(status):
    """«Выше целевого» и «ниже целевого» — тяжесть 1; незнакомый статус —
    тоже 1 (`_SEVERITY_UNKNOWN`, чтобы не спрятался среди нормальных).
    Сдвинь границу группировки на единицу — и всё это уедет в «оценить не
    удалось», то есть под сгиб."""
    view = build_view([_finding(status=status, value=95.0)])
    assert [row.finding.status for row in view.attention.rows] == [status]
    assert view.unjudged.rows == ()
    assert view.normal.rows == ()
