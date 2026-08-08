"""Эталонные проверки реальной спецификации опросника коуча."""

from pathlib import Path

from healthcoach.knowledge.questionnaire import load_questionnaire
from healthcoach.knowledge.validation import validate_questionnaire
from healthcoach.scoring.questionnaire import score_questionnaire

SPEC = Path(__file__).parents[2] / "knowledge" / "questionnaire.yaml"


def _questionnaire():
    return load_questionnaire(SPEC)


def test_real_questionnaire_loads():
    q = _questionnaire()
    assert len(q.blocks) == 24
    assert sum(len(b.questions) for b in q.blocks) == 544


def test_all_three_parts_present():
    q = _questionnaire()
    assert {b.part for b in q.blocks} == {
        "организационная",
        "клиническая",
        "дополнительная",
    }


def test_extra_questionnaires_are_not_core():
    """Дополнительные опросники коуч включает вручную под конкретного клиента."""
    q = _questionnaire()
    extra = [b for b in q.blocks if b.part == "дополнительная"]
    assert len(extra) == 5
    assert all(not b.core for b in extra)
    assert all(b.core for b in q.blocks if b.part != "дополнительная")


def test_part_banners_are_not_blocks():
    """Баннеры частей набраны капсом так же, как заголовки блоков."""
    q = _questionnaire()
    titles = {b.title.casefold() for b in q.blocks}
    for banner in ("организационная часть", "клиническая часть", "дополнительные опросники"):
        assert banner not in titles


def test_every_question_belongs_to_a_subscale():
    q = _questionnaire()
    for block in q.blocks:
        covered = {qid for sub in block.subscales for qid in sub.question_ids}
        missing = {question.id for question in block.questions} - covered
        assert not missing, f"блок {block.id}: вопросы вне подгрупп: {sorted(missing)}"


def test_every_question_has_a_usable_scale():
    q = _questionnaire()
    for block in q.blocks:
        for question in block.questions:
            options = question.options()
            assert options, f"{question.id}: пустая шкала"
            assert len({o.score for o in options}) == len(options)


def test_no_threshold_problems_remain():
    """Расхождения с исходным xlsx согласованы с коучем и внесены генератором."""
    problems = validate_questionnaire(_questionnaire())
    assert problems == [], "\n".join(f"{p.where}: {p.message}" for p in problems)


def test_gastro_block_reference_case():
    """Эталон по листу ключа: Желудок и П/Ж, сумма 12 — средняя степень."""
    q = _questionnaire()
    block = q.block("zeludok_i_p_z")
    answers: dict[str, int] = {}
    remaining = 12
    for question in block.questions:
        top = max(o.score for o in question.options())
        take = min(top, remaining)
        answers[question.id] = take
        remaining -= take
    assert remaining == 0

    scored = {s.subscale_id: s for s in score_questionnaire(q, answers, sex="ж")}
    assert scored["весь"].score == 12
    assert scored["весь"].degree == "средняя"


def test_candida_degree_comes_from_the_total():
    """Пороги Candida относятся к сумме по всему опроснику, а не к секциям."""
    q = _questionnaire()
    block = q.block("oprosnik_candida")
    by_id = {s.id: s for s in block.subscales}

    assert set(by_id) == {"а", "б", "в", "всего"}
    assert len(by_id["всего"].question_ids) == 70
    assert by_id["всего"].thresholds
    for section in ("а", "б", "в"):
        assert by_id[section].thresholds == ()


def test_candida_sections_still_report_their_sums():
    """Секции остаются в результате — коуч видит разбивку без степени."""
    q = _questionnaire()
    block = q.block("oprosnik_candida")
    answers = {
        question.id: max(o.score for o in question.options())
        for question in block.questions
    }
    scored = {
        s.subscale_id: s
        for s in score_questionnaire(q, answers, sex="м")
        if s.block_id == "oprosnik_candida"
    }

    assert scored["а"].score == 236 and scored["а"].degree is None
    assert scored["б"].score == 216 and scored["б"].degree is None
    assert scored["в"].score == 96 and scored["в"].degree is None
    assert scored["всего"].score == 548 and scored["всего"].degree == "высокая"


def test_candida_other_symptoms_alone_cannot_reach_the_threshold():
    """Причина, по которой пороги считаются от суммы: секция В даёт максимум 96."""
    q = _questionnaire()
    block = q.block("oprosnik_candida")
    by_id = {s.id: s for s in block.subscales}
    other = _subscale_questions(block, by_id["в"])
    ceiling = sum(max(o.score for o in question.options()) for question in other)

    threshold = min(
        t.min for t in by_id["всего"].thresholds if t.degree == "высокая"
    )
    assert ceiling < threshold


def test_candida_top_degree_is_open_ended():
    """Верхняя степень Candida исправлена с '<140' на «выше 140»."""
    q = _questionnaire()
    by_id = {s.id: s for s in q.block("oprosnik_candida").subscales}
    top = [t for t in by_id["всего"].thresholds if t.degree == "высокая"]
    assert {t.sex for t in top} == {"м", "ж"}
    for threshold in top:
        assert threshold.max is None
        assert threshold.min == (141 if threshold.sex == "м" else 181)


def _subscale_questions(block, subscale):
    ids = set(subscale.question_ids)
    return [q for q in block.questions if q.id in ids]


def test_candida_sections_keep_their_own_scales():
    """У каждой секции Candida своя шкала, выписанная в колонке H."""
    q = _questionnaire()
    block = q.block("oprosnik_candida")
    by_id = {s.id: s for s in block.subscales}

    main = _subscale_questions(block, by_id["б"])
    assert all(
        [(o.score, o.label) for o in question.options()]
        == [(3, "слабые"), (6, "средние"), (9, "сильные")]
        for question in main
    )

    other = _subscale_questions(block, by_id["в"])
    assert all(
        [(o.score, o.label) for o in question.options()]
        == [(1, "слабые"), (2, "средние"), (3, "сильные")]
        for question in other
    )


def test_candida_history_scores_are_multi_digit():
    """Баллы секции А доходят до 35; однозначный разбор их терял."""
    q = _questionnaire()
    block = q.block("oprosnik_candida")
    history = _subscale_questions(block, block.subscales[0])
    tops = {max(o.score for o in question.options()) for question in history}
    assert 35 in tops and 25 in tops and 20 in tops


def test_nutrition_parts_have_opposite_scales():
    """Часть 1 считает вредное, часть 2 — полезное; шкалы зеркальны."""
    q = _questionnaire()
    block = q.block("pitanie")
    by_id = {s.id: s for s in block.subscales}

    harmful = _subscale_questions(block, by_id["а"])[0]
    healthy = _subscale_questions(block, by_id["б"])[0]

    assert harmful.options()[0].label == "не употребляю"
    assert healthy.options()[0].label == "употребляю ежедневно"


def test_qeesi_masking_index_has_its_own_scale():
    """Индекс маскировки считается по 0/1, остальные секции — по 0/5/10."""
    q = _questionnaire()
    block = q.block("bolsoy_oprosnik_po_ocenke_intoksikacii_qeesi")
    by_id = {s.id: s for s in block.subscales}

    masking = _subscale_questions(block, by_id["г"])[0]
    symptoms = _subscale_questions(block, by_id["в"])[0]

    assert [o.score for o in masking.options()] == [0, 1]
    assert [o.score for o in symptoms.options()] == [0, 5, 10]


def test_sex_specific_thresholds_exist_where_the_key_defines_them():
    q = _questionnaire()
    by_id = {s.id: s for s in q.block("oprosnik_candida").subscales}
    assert {t.sex for t in by_id["всего"].thresholds} == {"м", "ж"}


def test_dass_has_no_thresholds_until_the_subscales_are_split():
    """Пороги DASS относятся к подшкалам из 14 утверждений, а не к сумме по 42."""
    q = _questionnaire()
    block = q.block("dass_oprosnik_depressia_trevoznost_stress")
    assert len(block.questions) == 42
    for subscale in block.subscales:
        assert subscale.thresholds == ()


def test_dass_sum_is_reported_without_a_degree():
    """Сумма видна коучу, но степень не выставляется — иначе она была бы неверной."""
    q = _questionnaire()
    block = q.block("dass_oprosnik_depressia_trevoznost_stress")
    answers = {question.id: 1 for question in block.questions}
    (scored,) = [
        s
        for s in score_questionnaire(q, answers, sex="ж")
        if s.block_id == block.id
    ]
    assert scored.score == 42
    assert scored.degree is None
    assert scored.degree_missing == "пороги не заданы"
