import json
from pathlib import Path

import pytest

from healthcoach.intake.answers import AnswersError, parse_answers
from healthcoach.knowledge.questionnaire import load_questionnaire

SPEC = Path(__file__).parents[2] / "knowledge" / "questionnaire.yaml"


@pytest.fixture(scope="module")
def questionnaire():
    return load_questionnaire(SPEC)


def _payload(questionnaire, answers, **overrides):
    body = {
        "версия": "1.0",
        "клиент": "CL-0417",
        "спецификация": questionnaire.version,
        "ответы": answers,
    }
    body.update(overrides)
    return json.dumps(body, ensure_ascii=False)


def test_parses_valid_payload(questionnaire):
    block = questionnaire.block("obraz_zizni")
    answers = {q.id: min(o.score for o in q.options()) for q in block.questions}
    result = parse_answers(questionnaire, _payload(questionnaire, answers))
    assert result.client_code == "CL-0417"
    assert result.answers == answers


def test_accepts_bytes(questionnaire):
    block = questionnaire.block("obraz_zizni")
    answers = {block.questions[0].id: 0}
    payload = _payload(questionnaire, answers).encode("utf-8")
    assert parse_answers(questionnaire, payload).answers == answers


def test_unanswered_questions_are_listed_not_invented(questionnaire):
    block = questionnaire.block("obraz_zizni")
    answered = {block.questions[0].id: 0}
    result = parse_answers(questionnaire, _payload(questionnaire, answered))
    assert block.questions[1].id in result.skipped
    assert block.questions[0].id not in result.skipped


def test_score_outside_the_scale_is_refused(questionnaire):
    block = questionnaire.block("obraz_zizni")
    question = block.questions[0]
    top = max(o.score for o in question.options())
    with pytest.raises(AnswersError, match=question.id):
        parse_answers(questionnaire, _payload(questionnaire, {question.id: top + 1}))


def test_unknown_question_names_the_version_mismatch(questionnaire):
    with pytest.raises(AnswersError) as excinfo:
        parse_answers(questionnaire, _payload(questionnaire, {"выдуманный.1": 0}))
    message = str(excinfo.value)
    assert "выдуманный.1" in message
    assert "версии" in message


def test_broken_json_is_refused(questionnaire):
    with pytest.raises(AnswersError, match="не разобран"):
        parse_answers(questionnaire, "{не json")


def test_missing_answers_key_is_refused(questionnaire):
    with pytest.raises(AnswersError, match="ответы"):
        parse_answers(
            questionnaire,
            json.dumps({"версия": "1.0", "клиент": "CL-0001"}, ensure_ascii=False),
        )


def test_unknown_payload_version_is_refused(questionnaire):
    with pytest.raises(AnswersError, match="версия файла"):
        parse_answers(questionnaire, _payload(questionnaire, {}, **{"версия": "9.9"}))


def test_specification_version_mismatch_is_refused(questionnaire):
    with pytest.raises(AnswersError, match="спецификаци"):
        parse_answers(
            questionnaire, _payload(questionnaire, {}, **{"спецификация": "0.1"})
        )


def test_non_integer_score_is_refused(questionnaire):
    block = questionnaire.block("obraz_zizni")
    payload = _payload(questionnaire, {block.questions[0].id: "два"})
    with pytest.raises(AnswersError, match="целым числом"):
        parse_answers(questionnaire, payload)


def test_round_trip_through_the_generated_page(questionnaire):
    """Формат, который объявляет страница, обязан разбираться импортом."""
    from healthcoach.intake.questionnaire_html import render_questionnaire

    html = render_questionnaire(questionnaire, "CL-0417")
    assert '"версия"' in html and '"спецификация"' in html

    block = questionnaire.block("obraz_zizni")
    answers = {q.id: min(o.score for o in q.options()) for q in block.questions}
    payload = json.dumps(
        {
            "версия": "1.0",
            "клиент": "CL-0417",
            "спецификация": questionnaire.version,
            "ответы": answers,
        },
        ensure_ascii=False,
    )
    assert parse_answers(questionnaire, payload).answers == answers
