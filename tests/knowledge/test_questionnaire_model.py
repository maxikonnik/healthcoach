from pathlib import Path

import pytest

from healthcoach.knowledge.questionnaire import (
    QuestionnaireError,
    load_questionnaire,
)

FIXTURE = Path(__file__).parent / "fixtures" / "questionnaire_minimal.yaml"


def test_loads_blocks_and_questions():
    q = load_questionnaire(FIXTURE)
    assert q.version == "1.0"
    block = q.block("obraz_zhizni")
    assert block.title == "Образ жизни"
    assert block.part == "организационная"
    assert block.core is True
    assert len(block.questions) == 2


def test_question_falls_back_to_block_scale():
    q = load_questionnaire(FIXTURE)
    block = q.block("obraz_zhizni")
    zaryadka = next(x for x in block.questions if x.id == "obraz_zhizni.1")
    assert [o.score for o in zaryadka.options()] == [0, 1]

    sport = next(x for x in block.questions if x.id == "obraz_zhizni.2")
    assert [o.score for o in sport.options()] == [0, 1, 2, 3]


def test_subscale_thresholds_parsed():
    q = load_questionnaire(FIXTURE)
    sub = q.block("obraz_zhizni").subscales[0]
    assert sub.id == "весь"
    assert sub.question_ids == ("obraz_zhizni.1", "obraz_zhizni.2")
    high = sub.thresholds[0]
    assert (high.degree, high.min, high.max, high.sex) == ("высокая", 5, None, None)


def test_unknown_block_raises():
    q = load_questionnaire(FIXTURE)
    with pytest.raises(QuestionnaireError, match="нет блока"):
        q.block("нет_такого")


def test_subscale_referencing_unknown_question_raises(tmp_path):
    bad = tmp_path / "bad.yaml"
    bad.write_text(
        "version: '1.0'\n"
        "blocks:\n"
        "  - id: b\n"
        "    title: Б\n"
        "    part: организационная\n"
        "    core: true\n"
        "    scale: [{score: 0, label: нет}]\n"
        "    questions: [{id: b.1, number: 1, text: Вопрос}]\n"
        "    subscales:\n"
        "      - id: весь\n"
        "        title: Весь блок\n"
        "        question_ids: [b.99]\n"
        "        thresholds: []\n",
        encoding="utf-8",
    )
    with pytest.raises(QuestionnaireError, match="b.99"):
        load_questionnaire(bad)
