from pathlib import Path

from healthcoach.knowledge.questionnaire import (
    Block,
    Question,
    Questionnaire,
    ScaleOption,
    Subscale,
    Threshold,
)
from healthcoach.knowledge.questionnaire import load_questionnaire
from healthcoach.knowledge.references import load_references
from healthcoach.scoring.findings import collect_findings
from healthcoach.scoring.references import Measurement, Subject

REFS = Path(__file__).parents[2] / "knowledge" / "references"
SPEC = Path(__file__).parents[2] / "knowledge" / "questionnaire.yaml"

SCALE = (ScaleOption(0, "нет"), ScaleOption(1, "иногда"), ScaleOption(2, "часто"))


def _questionnaire() -> Questionnaire:
    questions = tuple(
        Question(
            id=f"nadpochechniki.{i}",
            number=i,
            text=f"Симптом {i}",
            scale=None,
            block_scale=SCALE,
        )
        for i in range(1, 4)
    )
    block = Block(
        id="nadpochechniki",
        title="Надпочечники",
        part="клиническая",
        core=True,
        scale=SCALE,
        questions=questions,
        subscales=(
            Subscale(
                id="весь",
                title="Весь блок",
                question_ids=tuple(q.id for q in questions),
                thresholds=(
                    Threshold("низкая", 1, 2, None),
                    Threshold("средняя", 3, 4, None),
                    Threshold("высокая", 5, None, None),
                ),
            ),
        ),
    )
    return Questionnaire(version="1.0", blocks=(block,))


SUBJECT = Subject(sex="ж", age=32, cycle_phase=None)


def test_collects_all_three_kinds():
    findings = collect_findings(
        _questionnaire(),
        load_references(REFS),
        answers={f"nadpochechniki.{i}": 2 for i in range(1, 4)},
        measurements=[
            Measurement("ферритин", 18, "нг/мл"),
            Measurement("кальций", 10.0, "мг/дл"),
            Measurement("калий", 4.0, "ммоль/л"),
        ],
        subject=SUBJECT,
    )
    kinds = {f.kind for f in findings}
    assert kinds == {"показатель", "производный", "опросник"}


def test_questionnaire_finding_carries_degree_as_status():
    findings = collect_findings(
        _questionnaire(),
        load_references(REFS),
        answers={f"nadpochechniki.{i}": 2 for i in range(1, 4)},  # сумма 6
        measurements=[],
        subject=SUBJECT,
    )
    (finding,) = findings
    assert finding.kind == "опросник"
    assert finding.subject_id == "nadpochechniki/весь"
    assert finding.title == "Надпочечники"
    assert finding.status == "высокая"
    assert finding.value == 6


def test_severe_findings_come_first_and_unknown_last():
    findings = collect_findings(
        _questionnaire(),
        load_references(REFS),
        answers={f"nadpochechniki.{i}": 0 for i in range(1, 4)},  # норма
        measurements=[
            Measurement("гомоцистеин", 12, "мкмоль/л"),  # правило не задано
            Measurement("ферритин", 18, "нг/мл"),  # дефицит
            Measurement("кальций", 9.5, "мг/дл"),  # в целевом
            Measurement("калий", 4.2, "ммоль/л"),  # в целевом
        ],
        subject=SUBJECT,
    )
    statuses = [f.status for f in findings]
    assert statuses[0] == "дефицит"
    assert statuses[-1] == "правило не задано"
    assert "в пределах нормы" in statuses  # находка опросника не потерялась


def test_questionnaire_without_degree_still_reported():
    findings = collect_findings(
        _questionnaire(),
        load_references(REFS),
        answers={"nadpochechniki.1": 0, "nadpochechniki.2": 0, "nadpochechniki.3": 0},
        measurements=[],
        subject=SUBJECT,
    )
    (finding,) = findings
    assert finding.status == "в пределах нормы"
    assert finding.value == 0


def _dass_questionnaire() -> Questionnaire:
    """Блок с градациями DASS: мужской род и буква 'е', как на листе ключа."""
    questions = tuple(
        Question(
            id=f"dass.{i}",
            number=i,
            text=f"Утверждение {i}",
            scale=None,
            block_scale=SCALE,
        )
        for i in range(1, 4)
    )
    block = Block(
        id="dass",
        title="DASS — депрессия",
        part="дополнительная",
        core=False,
        scale=SCALE,
        questions=questions,
        subscales=(
            Subscale(
                id="весь",
                title="Весь блок",
                question_ids=tuple(q.id for q in questions),
                thresholds=(
                    Threshold("Нормальный", 0, 1, None),
                    Threshold("Тяжелый", 2, None, None),
                ),
            ),
        ),
    )
    return Questionnaire(version="1.0", blocks=(block,))


def test_dass_masculine_degree_sorts_as_severe():
    """Тяжёлая депрессия по DASS обязана обгонять дефицит показателя.

    Проверка неслучайна: если распознавание мужских форм отвалится, степень
    получит тяжесть «неизвестно» (1), дефицит останется на 0, и порядок
    перевернётся — тест упадёт.
    """
    findings = collect_findings(
        _dass_questionnaire(),
        load_references(REFS),
        answers={f"dass.{i}": 2 for i in range(1, 4)},  # сумма 6 → Тяжелый
        measurements=[Measurement("ферритин", 18, "нг/мл")],  # дефицит
        subject=SUBJECT,
    )
    assert [f.status for f in findings] == ["Тяжелый", "дефицит"]


def test_dass_normal_degree_is_not_treated_as_severe():
    """«Нормальный» обязан уступить показателю ниже целевого коридора.

    При отвалившемся распознавании «Нормальный» получил бы тяжесть
    «неизвестно» (1) вместо нормы (3), сравнялся бы с «ниже целевого»
    и обогнал бы его по вторичному ключу — тест упадёт.
    """
    findings = collect_findings(
        _dass_questionnaire(),
        load_references(REFS),
        answers={f"dass.{i}": 0 for i in range(1, 4)},  # сумма 0 → Нормальный
        measurements=[Measurement("ферритин", 45, "нг/мл")],  # ниже целевого
        subject=SUBJECT,
    )
    assert [f.status for f in findings] == ["ниже целевого", "Нормальный"]


def test_unscored_subscale_is_not_called_normal():
    """548 из 548 не должны выводиться как «в пределах нормы»."""
    block = _block_without_thresholds()
    q = Questionnaire(version="1.0", blocks=(block,))
    findings = collect_findings(
        q,
        load_references(REFS),
        answers={f"bez.{i}": 2 for i in range(1, 4)},
        measurements=[],
        subject=SUBJECT,
    )
    (finding,) = findings
    assert finding.status == "степень не выставлена"
    assert finding.rule_missing is True
    assert finding.note == "пороги не заданы"
    assert finding.value == 6


def test_unscored_sorts_below_real_findings():
    block = _block_without_thresholds()
    q = Questionnaire(version="1.0", blocks=(block,))
    findings = collect_findings(
        q,
        load_references(REFS),
        answers={f"bez.{i}": 2 for i in range(1, 4)},
        measurements=[Measurement("ферритин", 18, "нг/мл")],
        subject=SUBJECT,
    )
    assert findings[0].status == "дефицит"
    assert findings[-1].status == "степень не выставлена"


def test_dass_reaches_the_coach_as_unscored_not_normal():
    """Раньше 42 балла по DASS выводились как «очень тяжелый»."""
    from pathlib import Path

    from healthcoach.knowledge.questionnaire import load_questionnaire

    spec = Path(__file__).parents[2] / "knowledge" / "questionnaire.yaml"
    q = load_questionnaire(spec)
    block = q.block("dass_oprosnik_depressia_trevoznost_stress")
    findings = collect_findings(
        q,
        load_references(REFS),
        answers={question.id: 1 for question in block.questions},
        measurements=[],
        subject=SUBJECT,
    )
    (finding,) = [f for f in findings if f.subject_id.startswith(block.id)]
    assert finding.value == 42
    assert finding.status == "степень не выставлена"
    assert finding.rule_missing is True


def _block_without_thresholds() -> Block:
    questions = tuple(
        Question(
            id=f"bez.{i}", number=i, text=f"Вопрос {i}", scale=None, block_scale=SCALE
        )
        for i in range(1, 4)
    )
    return Block(
        id="bez",
        title="Без порогов",
        part="клиническая",
        core=True,
        scale=SCALE,
        questions=questions,
        subscales=(
            Subscale(
                id="весь",
                title="Весь блок",
                question_ids=tuple(q.id for q in questions),
                thresholds=(),
            ),
        ),
    )


def test_degree_from_partial_answers_carries_the_count():
    """Пропущенный вопрос идёт за ноль баллов, а больше баллов — хуже.

    Значит каждый пропуск смещает клиента в сторону здорового. Степень по
    неполным ответам мягче настоящей, и находка обязана это показывать.
    """
    questionnaire = load_questionnaire(SPEC)
    block = questionnaire.block("obraz_zizni")
    subscale = block.subscales[0]
    ids = list(subscale.question_ids)

    full = {qid: 0 for qid in ids}
    partial = {qid: 0 for qid in ids[:-1]}

    references = load_references(REFS)
    subject = Subject(sex="ж", age=32)

    def finding_for(answers):
        for finding in collect_findings(
            questionnaire, references, answers, [], subject
        ):
            if finding.subject_id == f"{block.id}/{subscale.id}":
                return finding
        raise AssertionError("находка по подгруппе не найдена")

    assert finding_for(full).partial is False
    assert finding_for(full).answered == len(ids)

    incomplete = finding_for(partial)
    assert incomplete.partial is True
    assert incomplete.answered == len(ids) - 1
    assert incomplete.total == len(ids)
