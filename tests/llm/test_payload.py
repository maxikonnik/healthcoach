from datetime import date

import pytest

from healthcoach.knowledge.specialists import load_specialists
from healthcoach.llm.payload import build_payload, finding_id
from healthcoach.privacy.leak import LeakError
from healthcoach.scoring.findings import Finding
from healthcoach.scoring.references import Subject
from healthcoach.storage.clients import Client
from pathlib import Path

SPECIALISTS = Path(__file__).parents[2] / "knowledge" / "specialists.yaml"

CLIENT = Client(
    code="CL-0001",
    full_name="Королькова Евгения Валерьевна",
    sex="ж",
    birth_date=date(1987, 4, 18),
    contacts="@korolkova",
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
    assert "18.04.1987" not in payload


def test_payload_refuses_a_request_that_still_names_the_client():
    """Сборка — единственный путь наружу, и она зовёт сторожа сама."""
    with pytest.raises(LeakError, match="Королько"):
        build_payload(
            [FINDING],
            Subject(sex="ж", age=39),
            "Королькова жалуется на усталость",
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
        title="KOROLKOVA E.V. Ферритин",
        value=18.0,
        units="нг/мл",
        status="правило не задано",
        target=None,
        lab_range=None,
        note=None,
        rule_missing=True,
    )
    payload = build_payload([unresolved], Subject(sex="ж", age=39), "", _specialties(), CLIENT)
    assert "KOROLKOVA E.V. Ферритин" not in payload
    assert "показатель из бланка, не распознан" in payload
    assert "18" in payload
    assert "правило не задано" in payload


def test_payload_does_not_send_the_verbatim_title_of_a_finding_with_no_rule_even_when_resolved():
    """Раньше маркером считался пустой subject_id — ложно: `_unresolved()`
    вызывается и когда analyte_id распознан, но значения нет (например,
    в бланке ‘<0.60’), и title всё равно берётся из текста бланка
    (`measurement.label`), а не из базы знаний. Настоящий маркер — kind
    показателя/производного вместе с rule_missing."""
    resolved_but_missing = Finding(
        kind="показатель",
        subject_id="ferritin",
        title="KOROLKOVA E.V. Ферритин",
        value=None,
        units="нг/мл",
        status="значение не распознано",
        target=None,
        lab_range=None,
        note=None,
        rule_missing=True,
    )
    payload = build_payload(
        [resolved_but_missing], Subject(sex="ж", age=39), "", _specialties(), CLIENT
    )
    assert "KOROLKOVA E.V. Ферритин" not in payload
    assert "показатель из бланка, не распознан" in payload
    assert "нг/мл" in payload
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


def test_payload_carries_cycle_phase_when_set():
    payload = build_payload(
        [FINDING], Subject(sex="ж", age=39, cycle_phase="фолликулярная"), "", _specialties(), CLIENT
    )
    assert "фолликулярная" in payload


def test_payload_omits_cycle_phase_when_not_set():
    payload = build_payload([FINDING], Subject(sex="ж", age=39), "", _specialties(), CLIENT)
    assert "фаза цикла" not in payload
