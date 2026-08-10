from datetime import date

import pytest

from healthcoach.knowledge.questionnaire import Questionnaire
from healthcoach.knowledge.references import load_references
from healthcoach.knowledge.specialists import load_specialists
from healthcoach.llm.payload import build_payload, finding_id
from healthcoach.privacy.leak import LeakError
from healthcoach.scoring.findings import Finding, collect_findings
from healthcoach.scoring.references import Measurement, Subject
from healthcoach.storage.clients import Client
from pathlib import Path

SPECIALISTS = Path(__file__).parents[2] / "knowledge" / "specialists.yaml"
REFS = Path(__file__).parents[2] / "knowledge" / "references"

CLIENT = Client(
    code="CL-0001",
    full_name="Соловьёва Ирина Анатольевна",
    sex="ж",
    birth_date=date(1985, 3, 24),
    contacts="@solovyova",
    note=None,
)

FINDING = Finding(
    kind="показатель",
    subject_id="ферритин",
    title="Ферритин",
    value=18.0,
    units="нг/мл",
    status="дефицит",
    target=None,
    lab_range=None,
    note=None,
    rule_missing=False,
)


def _specialties():
    return load_specialists(SPECIALISTS).public_view()


def test_payload_carries_the_findings():
    payload = build_payload([FINDING], Subject(sex="ж", age=39), "", _specialties(), CLIENT)
    assert "Ферритин" in payload
    assert "18" in payload
    assert "дефицит" in payload


def test_payload_carries_sex_and_age_but_not_the_birth_date():
    payload = build_payload([FINDING], Subject(sex="ж", age=39), "", _specialties(), CLIENT)
    assert "39" in payload
    assert "24.03.1985" not in payload


def test_payload_refuses_a_request_that_still_names_the_client():
    """Сборка — единственный путь наружу, и она зовёт сторожа сама."""
    with pytest.raises(LeakError, match="Соловьё"):
        build_payload(
            [FINDING],
            Subject(sex="ж", age=39),
            "Соловьёва жалуется на усталость",
            _specialties(),
            CLIENT,
        )


def test_payload_never_carries_doctor_contacts():
    """Врачи видны только коучу — в справочнике для модели их нет."""
    payload = build_payload([FINDING], Subject(sex="ж", age=39), "", _specialties(), CLIENT)
    specialists = load_specialists(SPECIALISTS)
    for specialty in specialists.specialties:
        for doctor in specialty.doctors:
            assert doctor.name not in payload
            assert doctor.contacts not in payload


def test_finding_id_is_stable_and_distinguishes_findings():
    other = Finding(
        kind="опросник",
        subject_id="obraz_zizni/весь",
        title="ОБРАЗ ЖИЗНИ",
        value=8,
        units="баллов",
        status="высокая",
        target=None,
        lab_range=None,
        note=None,
        rule_missing=False,
    )
    assert finding_id(FINDING) == finding_id(FINDING)
    assert finding_id(FINDING) != finding_id(other)


def test_payload_lists_the_finding_ids_so_sections_can_point_at_them():
    payload = build_payload([FINDING], Subject(sex="ж", age=39), "", _specialties(), CLIENT)
    assert finding_id(FINDING) in payload


def test_payload_does_not_send_the_verbatim_title_of_an_unresolved_finding():
    """Заголовок нераспознанной находки — текст с бланка, вплоть до OCR
    транслитерации имени клиента. Модель всё равно не может истолковать
    показатель, которого нет в базе знаний, поэтому наружу идёт общая
    формулировка, а не то, что там было написано."""
    unresolved = Finding(
        kind="показатель",
        subject_id="",
        title="SOLOVYOVA E.V. Ферритин",
        value=18.0,
        units="нг/мл",
        status="правило не задано",
        target=None,
        lab_range=None,
        note=None,
        rule_missing=True,
        row_id=7,
        title_from_document=True,
    )
    payload = build_payload([unresolved], Subject(sex="ж", age=39), "", _specialties(), CLIENT)
    assert "SOLOVYOVA E.V. Ферритин" not in payload
    assert "показатель из бланка, не распознан" in payload
    assert "18" in payload
    assert "правило не задано" in payload


def test_payload_does_not_send_the_verbatim_title_of_a_finding_with_no_rule_even_when_resolved():
    """Раньше маркером считался пустой subject_id — ложно: `_unresolved()`
    вызывается и когда analyte_id распознан, но значения нет (например,
    в бланке ‘<0.60’), и title всё равно берётся из текста бланка
    (`measurement.label`), а не из базы знаний. Настоящий маркер — kind
    показателя/производного вместе с rule_missing. С тех пор маркер стал
    точнее: `title_from_document`, который поднимает сам этот путь и
    только он."""
    resolved_but_missing = Finding(
        kind="показатель",
        subject_id="ferritin",
        title="SOLOVYOVA E.V. Ферритин",
        value=None,
        units="нг/мл",
        status="значение не распознано",
        target=None,
        lab_range=None,
        note=None,
        rule_missing=True,
        row_id=3,
        title_from_document=True,
        units_from_document=True,
    )
    payload = build_payload(
        [resolved_but_missing], Subject(sex="ж", age=39), "", _specialties(), CLIENT
    )
    assert "SOLOVYOVA E.V. Ферритин" not in payload
    assert "показатель из бланка, не распознан" in payload
    assert "значение не распознано" in payload


def test_payload_keeps_the_real_title_of_a_questionnaire_finding_with_no_degree():
    """Заголовок опросника — название блока/подшкалы из базы знаний коуча,
    не текст документа, даже когда степень не выставлена (rule_missing=True).
    Маскировать его незачем и нельзя — его нет смысла путать с заголовком
    показателя."""
    unscored = Finding(
        kind="опросник",
        subject_id="obraz_zizni/весь",
        title="ОБРАЗ ЖИЗНИ",
        value=8,
        units="баллов",
        status="степень не выставлена",
        target=None,
        lab_range=None,
        note="нет правила для этой суммы",
        rule_missing=True,
    )
    payload = build_payload([unscored], Subject(sex="ж", age=39), "", _specialties(), CLIENT)
    assert "ОБРАЗ ЖИЗНИ" in payload
    assert "показатель из бланка, не распознан" not in payload


def _findings_for(measurements):
    """Находки по настоящему пути: измерение → сверка → находка.

    Опросник пустой: здесь проверяются показатели, а вручную собранная
    находка не доказала бы, что флаги «из документа» кто-то выставляет.
    """
    return collect_findings(
        Questionnaire(version="1.0", blocks=()),
        load_references(REFS),
        answers={},
        measurements=measurements,
        subject=Subject(sex="ж", age=39),
    )


UNRESOLVED_ROWS = [
    Measurement("", 12.0, "мкмоль/л", label="Гомоцистеин по Инвитро", row_id=41),
    Measurement("", 32.0, "нг/мл", label="Витамин D 25-OH", row_id=42),
]


def test_two_unresolved_findings_do_not_share_one_identifier():
    """В базе знаний коуча единицы показателей, в бланке — два десятка.
    Пустой subject_id у всех нераспознанных один, и без различителя вся
    выгрузка получала бы идентификатор «показатель/»: коуч не может ни
    отличить их, ни сослаться на одну."""
    findings = _findings_for(UNRESOLVED_ROWS)
    assert len(findings) == 2

    ids = [finding_id(f) for f in findings]
    assert len(set(ids)) == 2, ids


def test_the_identifier_of_an_unresolved_finding_is_the_same_on_a_second_run():
    """Раздел черновика хранит идентификаторы находок. Если при следующей
    сборке страницы они окажутся другими, раздел укажет не туда."""
    first = [finding_id(f) for f in _findings_for(UNRESOLVED_ROWS)]
    second = [finding_id(f) for f in _findings_for(UNRESOLVED_ROWS)]
    assert first == second


def test_the_identifier_of_an_unresolved_finding_does_not_carry_the_form_text():
    """Различитель — номер строки среза, а не подпись из бланка: подпись
    уходит модели вместе с идентификатором."""
    ids = [finding_id(f) for f in _findings_for(UNRESOLVED_ROWS)]
    for text in ("Гомоцистеин по Инвитро", "Витамин D 25-OH"):
        assert all(text not in one for one in ids)


def test_unresolved_findings_reach_the_model_as_distinguishable_lines():
    payload = build_payload(
        _findings_for(UNRESOLVED_ROWS), Subject(sex="ж", age=39), "",
        _specialties(), CLIENT,
    )
    lines = [line for line in payload.splitlines() if line.startswith("[показатель/")]
    assert len(lines) == 2
    assert lines[0] != lines[1]


def test_payload_names_a_recognised_analyte_whose_units_did_not_match():
    """Единицы не сопоставились — но показатель распознан, и заголовок у
    него из базы знаний коуча, а не из бланка. Раздел «показатели» обязан
    такие находки назвать; под маской называть было бы нечем."""
    findings = _findings_for(
        [Measurement("ферритин", 18.0, "мг/дл", label="SOLOVYOVA E.V. Ферритин", row_id=5)]
    )
    payload = build_payload(
        findings, Subject(sex="ж", age=39), "", _specialties(), CLIENT
    )
    assert "Ферритин" in payload
    assert "показатель из бланка, не распознан" not in payload
    assert "показатель/ферритин" in payload
    assert "SOLOVYOVA E.V." not in payload


def test_payload_does_not_carry_the_units_written_on_the_form():
    """Ручной ввод сохраняет подпись единиц дословно. Маска на заголовке
    не закрывает ни units, ни отголосок исходного написания в note — а
    они стоят в той же строке."""
    findings = _findings_for(
        [Measurement("ферритин", 18.0, "мкг/л SOLOVYOVA E.V.", row_id=5)]
    )
    payload = build_payload(
        findings, Subject(sex="ж", age=39), "", _specialties(), CLIENT
    )
    assert "SOLOVYOVA E.V." not in payload
    assert "единицы из бланка" in payload
    # Статус остаётся: модель знает, что показатель не истолковать.
    assert "единицы не сопоставлены" in payload


def test_payload_carries_cycle_phase_when_set():
    payload = build_payload(
        [FINDING], Subject(sex="ж", age=39, cycle_phase="фолликулярная"), "", _specialties(), CLIENT
    )
    assert "фолликулярная" in payload


def test_payload_omits_cycle_phase_when_not_set():
    payload = build_payload([FINDING], Subject(sex="ж", age=39), "", _specialties(), CLIENT)
    assert "фаза цикла" not in payload
