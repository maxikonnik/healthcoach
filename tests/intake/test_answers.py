import json
import re
from pathlib import Path

import pytest

from healthcoach.intake.answers import AnswersError, parse_answers
from healthcoach.intake.questionnaire_html import PAYLOAD_VERSION, render_questionnaire
from healthcoach.knowledge.questionnaire import load_questionnaire

SPEC = Path(__file__).parents[2] / "knowledge" / "questionnaire.yaml"

PAYLOAD_KEYS = ("версия", "клиент", "спецификация", "блоки", "ответы")


@pytest.fixture(scope="module")
def questionnaire():
    return load_questionnaire(SPEC)


def _core_ids(questionnaire):
    return [block.id for block in questionnaire.blocks if block.core]


def _payload(questionnaire, answers, **overrides):
    body = {
        "версия": PAYLOAD_VERSION,
        "клиент": "CL-0417",
        "спецификация": questionnaire.version,
        "блоки": _core_ids(questionnaire),
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


def test_questions_from_blocks_never_shown_are_not_called_skipped(questionnaire):
    """Иначе коуч получает две сотни строк, к которым клиент не имеет отношения."""
    result = parse_answers(questionnaire, _payload(questionnaire, {}))

    candida = questionnaire.block("oprosnik_candida")
    for question in candida.questions:
        assert question.id in result.not_asked
        assert question.id not in result.skipped

    shown = questionnaire.block("obraz_zizni")
    for question in shown.questions:
        assert question.id in result.skipped
        assert question.id not in result.not_asked

    assert "oprosnik_candida" not in result.shown_blocks
    assert "obraz_zizni" in result.shown_blocks


def test_requested_extra_block_moves_its_questions_into_skipped(questionnaire):
    blocks = [*_core_ids(questionnaire), "oprosnik_candida"]
    result = parse_answers(
        questionnaire, _payload(questionnaire, {}, **{"блоки": blocks})
    )
    candida = questionnaire.block("oprosnik_candida")
    assert candida.questions[0].id in result.skipped
    assert candida.questions[0].id not in result.not_asked


def test_answer_to_a_block_never_shown_is_refused(questionnaire):
    """Ответ на вопрос, которого клиент не видел, — расхождение, а не пропуск."""
    candida = questionnaire.block("oprosnik_candida")
    question = candida.questions[0]
    payload = _payload(questionnaire, {question.id: min(
        o.score for o in question.options()
    )})
    with pytest.raises(AnswersError, match="не показывали"):
        parse_answers(questionnaire, payload)


def test_missing_blocks_key_is_refused(questionnaire):
    body = json.loads(_payload(questionnaire, {}))
    del body["блоки"]
    with pytest.raises(AnswersError, match="блоки"):
        parse_answers(questionnaire, json.dumps(body, ensure_ascii=False))


def test_empty_blocks_list_is_refused(questionnaire):
    """Опросник, в котором клиенту не показали ни одного блока, — не анкета."""
    with pytest.raises(AnswersError, match="пуст"):
        parse_answers(questionnaire, _payload(questionnaire, {}, **{"блоки": []}))


def test_repeated_blocks_collapse(questionnaire):
    core = _core_ids(questionnaire)
    result = parse_answers(
        questionnaire, _payload(questionnaire, {}, **{"блоки": [*core, *core]})
    )
    assert result.shown_blocks == tuple(core)


def test_unknown_block_names_the_version_mismatch(questionnaire):
    payload = _payload(questionnaire, {}, **{"блоки": ["выдуманный_блок"]})
    with pytest.raises(AnswersError) as excinfo:
        parse_answers(questionnaire, payload)
    message = str(excinfo.value)
    assert "выдуманный_блок" in message
    assert "версии" in message


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
            json.dumps(
                {"версия": PAYLOAD_VERSION, "клиент": "CL-0001"}, ensure_ascii=False
            ),
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


def test_boolean_score_is_refused(questionnaire):
    """True в Python — это int со значением 1; молча принять его нельзя."""
    block = questionnaire.block("obraz_zizni")
    payload = _payload(questionnaire, {block.questions[0].id: True})
    with pytest.raises(AnswersError, match="целым числом"):
        parse_answers(questionnaire, payload)


def _const(html: str, name: str):
    """Значение JS-константы, объявленной страницей."""
    match = re.search(rf"^const {name} = (.+);$", html, re.MULTILINE)
    assert match is not None, f"страница не объявляет {name}"
    return json.loads(match.group(1))


def test_round_trip_through_the_generated_page(questionnaire):
    """Формат, который объявляет страница, обязан разбираться импортом.

    Значения берутся из самой страницы, а не пишутся здесь заново: иначе
    переименование ключа или расхождение версий прошло бы молча.
    """
    html = render_questionnaire(
        questionnaire, "CL-0417", extra_block_ids=["oprosnik_candida"]
    )
    for key in PAYLOAD_KEYS:
        assert f'"{key}"' in html, f"страница не объявляет ключ {key!r}"

    block = questionnaire.block("obraz_zizni")
    answers = {q.id: min(o.score for o in q.options()) for q in block.questions}
    payload = json.dumps(
        {
            "версия": _const(html, "PAYLOAD_VERSION"),
            "клиент": _const(html, "CLIENT_CODE"),
            "спецификация": _const(html, "SPEC_VERSION"),
            "блоки": _const(html, "SHOWN_BLOCKS"),
            "ответы": answers,
        },
        ensure_ascii=False,
    )

    result = parse_answers(questionnaire, payload)
    assert result.answers == answers
    assert result.client_code == "CL-0417"
    assert "oprosnik_candida" in result.shown_blocks
    candida = questionnaire.block("oprosnik_candida")
    assert candida.questions[0].id not in result.not_asked
