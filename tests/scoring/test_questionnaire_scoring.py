import pytest

from healthcoach.knowledge.questionnaire import (
    Block,
    Question,
    Questionnaire,
    ScaleOption,
    Subscale,
    Threshold,
)
from healthcoach.scoring.questionnaire import ScoringError, score_questionnaire

SCALE = (
    ScaleOption(0, "не актуально"),
    ScaleOption(1, "иногда"),
    ScaleOption(2, "средне"),
    ScaleOption(3, "сильно"),
)


def _block(thresholds: tuple[Threshold, ...], count: int = 6) -> Block:
    questions = tuple(
        Question(
            id=f"zheludok.{i}",
            number=i,
            text=f"Симптом {i}",
            scale=None,
            block_scale=SCALE,
        )
        for i in range(1, count + 1)
    )
    return Block(
        id="zheludok",
        title="Желудок и П/Ж",
        part="клиническая",
        core=True,
        scale=SCALE,
        questions=questions,
        subscales=(
            Subscale(
                id="весь",
                title="Весь блок",
                question_ids=tuple(q.id for q in questions),
                thresholds=thresholds,
            ),
        ),
    )


THRESHOLDS = (
    Threshold("низкая", 6, 10, None),
    Threshold("средняя", 11, 15, None),
    Threshold("высокая", 16, None, None),
)


def _questionnaire(**kwargs) -> Questionnaire:
    return Questionnaire(version="1.0", blocks=(_block(THRESHOLDS, **kwargs),))


def test_sums_answers_and_resolves_degree():
    q = _questionnaire()
    answers = {f"zheludok.{i}": 2 for i in range(1, 7)}  # сумма 12
    (result,) = score_questionnaire(q, answers, sex="ж")
    assert result.score == 12
    assert result.degree == "средняя"
    assert result.answered == 6
    assert result.total == 6
    assert result.block_title == "Желудок и П/Ж"


def test_score_below_lowest_threshold_has_no_degree():
    q = _questionnaire()
    answers = {f"zheludok.{i}": 0 for i in range(1, 7)}
    answers["zheludok.1"] = 3  # сумма 3, ниже низкой степени
    (result,) = score_questionnaire(q, answers, sex="ж")
    assert result.score == 3
    assert result.degree is None


def test_open_top_threshold_matches():
    q = _questionnaire()
    answers = {f"zheludok.{i}": 3 for i in range(1, 7)}  # сумма 18
    (result,) = score_questionnaire(q, answers, sex="ж")
    assert result.degree == "высокая"


def test_sex_specific_thresholds_selected():
    block = _block(
        (
            Threshold("низкая", 0, 5, "м"),
            Threshold("высокая", 6, None, "м"),
            Threshold("низкая", 0, 12, "ж"),
            Threshold("высокая", 13, None, "ж"),
        )
    )
    q = Questionnaire(version="1.0", blocks=(block,))
    answers = {f"zheludok.{i}": 2 for i in range(1, 7)}  # сумма 12

    (male,) = score_questionnaire(q, answers, sex="м")
    (female,) = score_questionnaire(q, answers, sex="ж")
    assert male.degree == "высокая"
    assert female.degree == "низкая"


def test_sparse_subscale_keeps_score_but_drops_degree():
    q = _questionnaire()
    answers = {"zheludok.1": 3, "zheludok.2": 3}  # отвечено 2 из 6
    (result,) = score_questionnaire(q, answers, sex="ж")
    assert result.score == 6
    assert result.answered == 2
    assert result.degree is None


def test_unanswered_subscale_omitted():
    q = _questionnaire()
    assert score_questionnaire(q, {}, sex="ж") == []


def test_answer_outside_scale_raises():
    q = _questionnaire()
    answers = {f"zheludok.{i}": 0 for i in range(1, 7)}
    answers["zheludok.3"] = 7
    with pytest.raises(ScoringError, match="zheludok.3"):
        score_questionnaire(q, answers, sex="ж")


def test_answer_for_unknown_question_raises():
    q = _questionnaire()
    with pytest.raises(ScoringError, match="нет в спецификации"):
        score_questionnaire(q, {"выдуманный.1": 1}, sex="ж")
