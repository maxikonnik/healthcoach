from healthcoach.knowledge.import_xlsx import (
    is_section_heading,
    slugify,
    split_inline_scale,
)


def test_slugify_transliterates_cyrillic():
    assert slugify("Образ жизни") == "obraz_zizni"
    assert slugify("ЖЕЛУДОК  и П/Ж") == "zeludok_i_p_z"


def test_slugify_is_stable_and_bounded():
    assert slugify("  Питание  ") == slugify("Питание")
    assert not slugify("Питание").startswith("_")
    assert not slugify("Питание").endswith("_")


def test_split_inline_scale_extracts_options():
    text = (
        "Регулярные занятия спортом\n"
        "0 - Два и больше в неделю\n"
        "1 - Один раз в неделю\n"
        "2 - Один или два раза в месяц\n"
        "3 - Никогда"
    )
    question, options = split_inline_scale(text)
    assert question == "Регулярные занятия спортом"
    assert [o["score"] for o in options] == [0, 1, 2, 3]
    assert options[0]["label"] == "Два и больше в неделю"


def test_split_inline_scale_handles_en_dash():
    _, options = split_inline_scale("Вопрос\n0 – Нет\n1 – Да")
    assert [o["label"] for o in options] == ["Нет", "Да"]


def test_split_inline_scale_without_scale_returns_empty():
    question, options = split_inline_scale("Отрыжка вскоре после еды")
    assert question == "Отрыжка вскоре после еды"
    assert options == []


def test_split_inline_scale_joins_multiline_question():
    question, options = split_inline_scale("Первая строка\nвторая строка\n0 - Нет")
    assert question == "Первая строка вторая строка"
    assert len(options) == 1


def test_is_section_heading_recognises_numbered_and_plain():
    assert is_section_heading("1. ПИТАНИЕ") == "ПИТАНИЕ"
    assert is_section_heading("КЛИНИЧЕСКАЯ ЧАСТЬ") == "КЛИНИЧЕСКАЯ ЧАСТЬ"
    assert is_section_heading("14. ЖЕНСКОЕ ЗДОРОВЬЕ") == "ЖЕНСКОЕ ЗДОРОВЬЕ"


def test_is_section_heading_rejects_ordinary_text():
    assert is_section_heading("Изжога или обратный заброс") is None
    assert is_section_heading("Сумма всех баллов в данном блоке") is None
    assert is_section_heading("") is None


def test_split_inline_scale_reads_multi_digit_scores():
    """В опроснике Candida баллы двузначные: 10, 20, 35."""
    question, options = split_inline_scale(
        "Применяли ли вы антибиотики длительно\n0 - Нет\n35 - Да"
    )
    assert question == "Применяли ли вы антибиотики длительно"
    assert [(o["score"], o["label"]) for o in options] == [(0, "Нет"), (35, "Да")]


def test_split_inline_scale_reads_three_option_multi_digit_scale():
    _, options = split_inline_scale(
        "Употребляли противозачаточные препараты\n"
        "0 - не употреблял(а)\n"
        "8 - от 6 до 24 месяцев\n"
        "15 - более 24 месяцев"
    )
    assert [o["score"] for o in options] == [0, 8, 15]


def test_split_inline_scale_does_not_leak_scores_into_question_text():
    """Нераспознанный вариант молча уезжал в текст вопроса — так было до фикса."""
    question, _ = split_inline_scale("Вопрос\n0 - Нет\n35 - Да")
    assert "35" not in question
