import pytest

from healthcoach.knowledge.questionnaire import (
    Block,
    Question,
    Questionnaire,
    ScaleOption,
    Subscale,
    Threshold,
)
from healthcoach.knowledge.validation import (
    RangeParseError,
    parse_threshold_range,
    validate_questionnaire,
)


@pytest.mark.parametrize(
    "text, expected",
    [
        ("4-8", (4, 8)),
        ("0-19", (0, 19)),
        (">14", (15, None)),
        ("> 14", (15, None)),
        ("<40", (None, 39)),
        ("40-100", (40, 100)),
    ],
)
def test_parse_threshold_range(text, expected):
    assert parse_threshold_range(text) == expected


def test_parse_threshold_range_rejects_garbage():
    with pytest.raises(RangeParseError, match="не удалось разобрать"):
        parse_threshold_range("много")


def _questionnaire(thresholds: list[Threshold]) -> Questionnaire:
    scale = (ScaleOption(0, "нет"), ScaleOption(1, "да"))
    question = Question(
        id="b.1", number=1, text="Вопрос", scale=None, block_scale=scale
    )
    block = Block(
        id="b",
        title="Блок",
        part="клиническая",
        core=True,
        scale=scale,
        questions=(question,),
        subscales=(
            Subscale(
                id="весь",
                title="Весь блок",
                question_ids=("b.1",),
                thresholds=tuple(thresholds),
            ),
        ),
    )
    return Questionnaire(version="1.0", blocks=(block,))


def test_valid_thresholds_produce_no_problems():
    q = _questionnaire(
        [
            Threshold("низкая", 4, 8, None),
            Threshold("средняя", 9, 13, None),
            Threshold("высокая", 14, None, None),
        ]
    )
    assert validate_questionnaire(q) == []


def test_overlapping_thresholds_reported():
    q = _questionnaire(
        [
            Threshold("низкая", 4, 8, None),
            Threshold("средняя", 7, 13, None),
        ]
    )
    problems = validate_questionnaire(q)
    assert any("пересекаются" in p.message for p in problems)


def test_gap_between_thresholds_reported():
    q = _questionnaire(
        [
            Threshold("низкая", 4, 8, None),
            Threshold("средняя", 12, 20, None),
        ]
    )
    problems = validate_questionnaire(q)
    assert any("разрыв" in p.message for p in problems)


def test_candida_style_bounded_top_degree_reported():
    """Высшая степень с верхней границей — та самая опечатка в исходном xlsx."""
    q = _questionnaire(
        [
            Threshold("низкая", None, 40, None),
            Threshold("средняя", 41, 140, None),
            Threshold("высокая", None, 140, None),
        ]
    )
    problems = validate_questionnaire(q)
    assert any("верхняя граница" in p.message for p in problems)


def test_degrees_checked_per_sex_independently():
    q = _questionnaire(
        [
            Threshold("низкая", 0, 40, "м"),
            Threshold("высокая", 41, None, "м"),
            Threshold("низкая", 0, 60, "ж"),
            Threshold("высокая", 61, None, "ж"),
        ]
    )
    assert validate_questionnaire(q) == []


def test_unknown_degree_name_is_reported():
    q = _questionnaire(
        [
            Threshold("странная", 1, 5, None),
            Threshold("высокая", 6, None, None),
        ]
    )
    problems = validate_questionnaire(q)
    assert any("не входит в известный порядок" in p.message for p in problems)


def test_dass_masculine_degree_names_are_recognised():
    q = _questionnaire(
        [
            Threshold("Нормальный", 0, 9, None),
            Threshold("Средний", 10, 13, None),
            Threshold("Умеренный", 14, 20, None),
            Threshold("Тяжелый", 21, 27, None),
            Threshold("Очень тяжелый", 28, None, None),
        ]
    )
    assert validate_questionnaire(q) == []


def test_degree_matching_ignores_case_and_yo():
    q = _questionnaire(
        [
            Threshold("НИЗКАЯ", 1, 5, None),
            Threshold("Тяжёлая", 6, None, None),
        ]
    )
    assert validate_questionnaire(q) == []
