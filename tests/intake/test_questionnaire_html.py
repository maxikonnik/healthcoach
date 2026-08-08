import json
import re
from pathlib import Path

import pytest

from healthcoach.intake.questionnaire_html import (
    QuestionnaireHtmlError,
    render_questionnaire,
)
from healthcoach.knowledge.questionnaire import load_questionnaire

SPEC = Path(__file__).parents[2] / "knowledge" / "questionnaire.yaml"


@pytest.fixture(scope="module")
def questionnaire():
    return load_questionnaire(SPEC)


def test_core_blocks_are_always_included(questionnaire):
    html = render_questionnaire(questionnaire, "CL-0001")
    for block in questionnaire.blocks:
        if block.core:
            assert block.title in html


def test_extra_blocks_are_excluded_by_default(questionnaire):
    html = render_questionnaire(questionnaire, "CL-0001")
    candida = questionnaire.block("oprosnik_candida")
    assert candida.title not in html


def test_requested_extra_block_is_included(questionnaire):
    html = render_questionnaire(
        questionnaire, "CL-0001", extra_block_ids=["oprosnik_candida"]
    )
    assert questionnaire.block("oprosnik_candida").title in html


def test_unknown_extra_block_is_refused(questionnaire):
    with pytest.raises(QuestionnaireHtmlError, match="нет блока"):
        render_questionnaire(questionnaire, "CL-0001", extra_block_ids=["выдуманный"])


def test_requesting_a_core_block_as_extra_is_refused(questionnaire):
    with pytest.raises(QuestionnaireHtmlError, match="входит в ядро"):
        render_questionnaire(questionnaire, "CL-0001", extra_block_ids=["pitanie"])


def test_file_is_self_contained(questionnaire):
    """Клиент открывает файл из мессенджера — внешних загрузок быть не должно."""
    html = render_questionnaire(questionnaire, "CL-0001")
    assert "<script src=" not in html
    assert "<link " not in html
    assert "http://" not in html
    assert "https://" not in html


def test_client_code_is_embedded_for_the_storage_key(questionnaire):
    html = render_questionnaire(questionnaire, "CL-0417")
    assert "CL-0417" in html
    assert "localStorage" in html


def test_every_option_of_every_included_question_is_rendered(questionnaire):
    html = render_questionnaire(questionnaire, "CL-0001")
    block = questionnaire.block("obraz_zizni")
    for question in block.questions:
        for option in question.options():
            expected = f'value="{option.score}"'
            assert expected in html
            assert option.label in html


def test_question_ids_are_present_as_input_names(questionnaire):
    html = render_questionnaire(questionnaire, "CL-0001")
    block = questionnaire.block("obraz_zizni")
    for question in block.questions:
        assert f'name="{question.id}"' in html


def test_answers_payload_shape_is_documented_in_the_page(questionnaire):
    """Файл сам объявляет формат, который потом разбирает импорт."""
    html = render_questionnaire(questionnaire, "CL-0417")
    assert '"версия"' in html
    assert '"клиент"' in html
    assert '"ответы"' in html


def test_html_escapes_question_text(questionnaire):
    """В тексте вопросов встречаются кавычки и угловые скобки."""
    html = render_questionnaire(questionnaire, "CL-0001")
    assert "<script>alert" not in html
    assert re.search(r"<body|<main", html)
