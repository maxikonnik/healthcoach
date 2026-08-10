"""Задача 6 плана: дата измерения проходит `safe_finding` явно, а не по
случайности `dataclasses.replace`. Остальная маска (заголовок, единицы,
заметка) уже проверена там, где живёт основной путь наружу
(`tests/llm/test_payload.py`, `tests/report/test_data.py`) — здесь только
то, что задача 6 добавляет: путь даты."""

from dataclasses import replace
from datetime import date

from healthcoach.privacy.findings import FOR_CLIENT, FOR_MODEL, safe_finding
from healthcoach.scoring.findings import Finding

DATED = Finding(
    kind="показатель",
    subject_id="ферритин",
    title="Ферритин",
    value=18.0,
    units="нг/мл",
    status="дефицит",
    target=None,
    lab_range=None,
    note="Растёт при воспалении — смотреть вместе с СРБ",
    rule_missing=False,
    note_private=True,
    taken_on=date(2026, 3, 10),
)


def test_measurement_date_reaches_the_model():
    safe = safe_finding(DATED, audience=FOR_MODEL)
    assert safe.taken_on == date(2026, 3, 10)


def test_measurement_date_reaches_the_client():
    safe = safe_finding(DATED, audience=FOR_CLIENT)
    assert safe.taken_on == date(2026, 3, 10)


def test_measurement_date_survives_masking_from_a_document_title():
    """Заголовок с бланка маскируется целиком (обеим сторонам) — дата не
    входит в то, что заменяет маска, и остаётся при находке."""
    from_document = replace(
        DATED, title_from_document=True, title="SOLOVYOVA E.V. Ферритин"
    )
    for audience in (FOR_MODEL, FOR_CLIENT):
        safe = safe_finding(from_document, audience=audience)
        assert safe.taken_on == date(2026, 3, 10)


def test_finding_with_no_date_stays_undated_for_both_audiences():
    undated = replace(DATED, taken_on=None)
    assert safe_finding(undated, audience=FOR_MODEL).taken_on is None
    assert safe_finding(undated, audience=FOR_CLIENT).taken_on is None
