import json
import re
from pathlib import Path

import pytest

from healthcoach.intake.questionnaire_html import (
    QuestionnaireHtmlError,
    render_questionnaire,
)
from healthcoach.knowledge.questionnaire import (
    Block,
    Question,
    Questionnaire,
    ScaleOption,
    Subscale,
    load_questionnaire,
)

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


def _shown_blocks(html: str) -> list[str]:
    match = re.search(r"^const SHOWN_BLOCKS = (.+);$", html, re.MULTILINE)
    assert match is not None, "страница не объявляет SHOWN_BLOCKS"
    return json.loads(match.group(1))


def test_page_declares_exactly_the_blocks_it_rendered(questionnaire):
    """Файл ответов отличает пропуск от «не показывали» только по этому списку.

    Если страница объявит блоки, которых не показывала, все их вопросы
    вернутся в «пропущенные» — ровно тот шум, ради устранения которого
    список и появился.
    """
    core = [b.id for b in questionnaire.blocks if b.core]

    assert _shown_blocks(render_questionnaire(questionnaire, "CL-0001")) == core
    assert "oprosnik_candida" not in core

    with_extra = render_questionnaire(
        questionnaire, "CL-0001", extra_block_ids=["oprosnik_candida"]
    )
    assert _shown_blocks(with_extra) == [*core, "oprosnik_candida"]


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


def test_every_question_is_rendered_exactly_once(questionnaire):
    """Подгруппы перекрываются: у Candida «всего» перечисляет весь блок.

    Без учёта уже показанных клиент проходил бы эти семьдесят вопросов
    дважды подряд.
    """
    html = render_questionnaire(
        questionnaire, "CL-0001", extra_block_ids=["oprosnik_candida"]
    )
    for question in questionnaire.block("oprosnik_candida").questions:
        assert html.count(f'data-q="{question.id}"') == 1


def test_summary_subscale_does_not_swallow_the_parts(questionnaire):
    """У Candida подгруппа «всего» перечисляет весь блок.

    Порядок подгрупп в спецификации — дело коуча. Если сводная окажется
    первой, она не должна забрать себе все вопросы: заголовки настоящих
    частей нужны клиенту, чтобы понимать, о чём его спрашивают.
    """
    html = render_questionnaire(
        questionnaire, "CL-0001", extra_block_ids=["oprosnik_candida"]
    )
    block = questionnaire.block("oprosnik_candida")
    summary = next(
        sub for sub in block.subscales if len(sub.question_ids) == len(block.questions)
    )
    for subscale in block.subscales:
        if subscale is summary:
            continue
        assert subscale.title in html


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


def _question(number: int, text: str, scale):
    return Question(
        id=f"blok.a.{number}", number=number, text=text, scale=None, block_scale=scale
    )


def _hostile_questionnaire() -> Questionnaire:
    """Спецификация, каждое текстовое поле которой пытается вырваться в разметку."""
    scale = (ScaleOption(score=0, label='<img src=x onerror="alert(1)">'),)
    questions = (
        _question(1, '<script>alert("взлом")</script>', scale),
        _question(2, "кавычка \" и амперсанд &", scale),
    )
    block = Block(
        id="blok",
        title="<i>название блока</i>",
        part="1",
        core=True,
        scale=scale,
        questions=questions,
        subscales=(
            Subscale(
                id="a", title="<b>первая</b>", question_ids=("blok.a.1",), thresholds=()
            ),
            Subscale(
                id="b", title="<b>вторая</b>", question_ids=("blok.a.2",), thresholds=()
            ),
        ),
    )
    return Questionnaire(version="test", blocks=(block,))


def test_hostile_text_in_the_specification_cannot_escape_into_markup():
    """Текст берётся из базы знаний коуча, но экранируется как недоверенный."""
    html = render_questionnaire(_hostile_questionnaire(), "CL-0001")

    assert "<script>alert" not in html
    assert "&lt;script&gt;alert" in html
    assert 'onerror="alert(1)"' not in html
    assert "<i>название блока</i>" not in html
    assert "<b>первая</b>" not in html
    assert "<b>вторая</b>" not in html

    assert re.search(r"<body|<main", html)
