from datetime import date, datetime
from pathlib import Path

import pytest
from fastapi.templating import Jinja2Templates

from healthcoach.knowledge.coach import Coach
from healthcoach.knowledge.questionnaire import load_questionnaire
from healthcoach.knowledge.references import Interval, load_references
from healthcoach.knowledge.specialists import load_specialists
from healthcoach.llm.payload import build_payload
from healthcoach.privacy.findings import DOCUMENT_UNITS, UNRESOLVED_TITLE
from healthcoach.report.data import ReportError, collect_report
from healthcoach.report.pdf import render_report_html
from healthcoach.scoring.findings import collect_findings
from healthcoach.scoring.references import (
    STATUS_NO_RULE,
    STATUS_UNIT_MISMATCH,
    Measurement,
    Subject,
)
from healthcoach.storage.clients import ClientRepository
from healthcoach.storage.db import open_database
from healthcoach.storage.drafts import DraftRepository
from healthcoach.storage.scopes import ReportScopeRepository
from healthcoach.storage.snapshots import SnapshotRepository

REFS = Path(__file__).parents[2] / "knowledge" / "references"
SPEC = Path(__file__).parents[2] / "knowledge" / "questionnaire.yaml"
SPECIALISTS = Path(__file__).parents[2] / "knowledge" / "specialists.yaml"
TEMPLATES_DIR = Path(__file__).parents[2] / "src" / "healthcoach" / "app" / "templates"
COACH = Coach(name="Иконникова Екатерина", title="нутрициолог", signature="")


@pytest.fixture(scope="module")
def knowledge():
    return load_questionnaire(SPEC), load_references(REFS)


def _collect(repo, knowledge, snapshot_id):
    questionnaire, references = knowledge
    return collect_report(repo, questionnaire, references, COACH, snapshot_id)


class Repos:
    """Хранилища на одном соединении — как их выдаёт Context.session()."""

    def __init__(self, connection):
        self.clients = ClientRepository(connection)
        self.snapshots = SnapshotRepository(connection)
        self.drafts = DraftRepository(connection)
        self.scopes = ReportScopeRepository(connection)


@pytest.fixture
def repo(tmp_path):
    connection = open_database(tmp_path / "db.sqlite")
    yield Repos(connection)
    connection.close()


def _client_with_snapshot(repo, taken_on=date(2026, 9, 1)):
    client = repo.clients.add("Соловьёва Ирина", "ж", date(1985, 3, 24))
    snapshot = repo.snapshots.create(client.code, taken_on)
    return client, snapshot


def _approved_draft(repo, snapshot_id):
    repo.drafts.save_section(snapshot_id, "запрос", "Текст запроса.", ())
    repo.drafts.save_section(snapshot_id, "показатели", "Текст показателей.", ())
    repo.drafts.approve(snapshot_id, datetime(2026, 9, 2, 10, 0))


def test_report_carries_the_client_and_the_coach(repo, knowledge):
    _, snapshot = _client_with_snapshot(repo)
    _approved_draft(repo, snapshot.id)

    data = _collect(repo, knowledge, snapshot.id)

    assert data.client_name == "Соловьёва Ирина"
    assert data.client_code == "CL-0001"
    assert data.taken_on == date(2026, 9, 1)
    assert data.coach.name == "Иконникова Екатерина"
    assert data.approved_at == datetime(2026, 9, 2, 10, 0)


def test_sections_come_in_the_order_of_the_report(repo, knowledge):
    _, snapshot = _client_with_snapshot(repo)
    _approved_draft(repo, snapshot.id)

    data = _collect(repo, knowledge, snapshot.id)

    assert [s.section_id for s in data.sections] == ["запрос", "показатели"]


def test_section_takes_the_coach_edit_over_the_model_text(repo, knowledge):
    """В отчёт идёт то, что оставил коуч, а не то, что написала модель."""
    _, snapshot = _client_with_snapshot(repo)
    saved = repo.drafts.save_section(snapshot.id, "запрос", "Текст модели.", ())
    repo.drafts.edit_section(saved.id, snapshot.id, "Правка коуча.")
    repo.drafts.approve(snapshot.id, datetime(2026, 9, 2))

    data = _collect(repo, knowledge, snapshot.id)

    assert data.sections[0].text == "Правка коуча."


def test_unapproved_draft_is_refused(repo, knowledge):
    """Неутверждённый черновик клиенту не отдаётся ни при каких условиях."""
    _, snapshot = _client_with_snapshot(repo)
    repo.drafts.save_section(snapshot.id, "запрос", "Текст.", ())

    with pytest.raises(ReportError, match="не утверждён"):
        _collect(repo, knowledge, snapshot.id)


def test_missing_draft_is_refused(repo, knowledge):
    _, snapshot = _client_with_snapshot(repo)
    with pytest.raises(ReportError, match="не утверждён"):
        _collect(repo, knowledge, snapshot.id)


def test_unknown_snapshot_is_refused(repo, knowledge):
    with pytest.raises(ReportError, match="нет среза"):
        _collect(repo, knowledge, 99999)


def test_only_confirmed_measurements_reach_the_report(repo, knowledge):
    """Ворота сверки держатся и здесь: клиент видит только сверенное."""
    client, snapshot = _client_with_snapshot(repo)
    confirmed = repo.snapshots.add_measurement(
        snapshot.id, "ферритин", "Ферритин", 18.0, "18", "нг/мл", date(2026, 8, 20)
    )
    repo.snapshots.add_measurement(
        snapshot.id, "ферритин", "Ферритин", 999.0, "999", "нг/мл", date(2026, 8, 21)
    )
    repo.snapshots.confirm_measurement(confirmed.id, snapshot.id)
    _approved_draft(repo, snapshot.id)

    data = _collect(repo, knowledge, snapshot.id)

    values = [f.value for f in data.findings]
    assert 18.0 in values
    assert 999.0 not in values


def test_a_single_measurement_is_not_dynamics(repo, knowledge):
    """Одна точка — первое измерение, а не динамика: линии здесь нет."""
    client, snapshot = _client_with_snapshot(repo)
    stored = repo.snapshots.add_measurement(
        snapshot.id, "ферритин", "Ферритин", 18.0, "18", "нг/мл", date(2026, 8, 20)
    )
    repo.snapshots.confirm_measurement(stored.id, snapshot.id)
    _approved_draft(repo, snapshot.id)

    data = _collect(repo, knowledge, snapshot.id)

    (series,) = data.series
    assert len(series.points) == 1
    assert series.has_dynamics is False


def test_two_snapshots_give_dynamics_sorted_by_sampling_date(repo, knowledge):
    client, first = _client_with_snapshot(repo, date(2026, 6, 1))
    second = repo.snapshots.create(client.code, date(2026, 9, 1))

    later = repo.snapshots.add_measurement(
        second.id, "ферритин", "Ферритин", 45.0, "45", "нг/мл", date(2026, 8, 25)
    )
    earlier = repo.snapshots.add_measurement(
        first.id, "ферритин", "Ферритин", 18.0, "18", "нг/мл", date(2026, 5, 20)
    )
    repo.snapshots.confirm_measurement(later.id, second.id)
    repo.snapshots.confirm_measurement(earlier.id, first.id)
    _approved_draft(repo, second.id)

    data = _collect(repo, knowledge, second.id)

    (series,) = data.series
    assert series.has_dynamics is True
    assert [p.value for p in series.points] == [18.0, 45.0]
    assert [p.taken_on for p in series.points] == [date(2026, 5, 20), date(2026, 8, 25)]


def test_unconfirmed_history_does_not_reach_the_chart(repo, knowledge):
    """График строится по сверенному, иначе клиент увидит непроверенную точку."""
    client, first = _client_with_snapshot(repo, date(2026, 6, 1))
    second = repo.snapshots.create(client.code, date(2026, 9, 1))
    repo.snapshots.add_measurement(
        first.id, "ферритин", "Ферритин", 5.0, "5", "нг/мл", date(2026, 5, 20)
    )
    stored = repo.snapshots.add_measurement(
        second.id, "ферритин", "Ферритин", 45.0, "45", "нг/мл", date(2026, 8, 25)
    )
    repo.snapshots.confirm_measurement(stored.id, second.id)
    _approved_draft(repo, second.id)

    data = _collect(repo, knowledge, second.id)

    (series,) = data.series
    assert [p.value for p in series.points] == [45.0]
    assert series.has_dynamics is False


def test_unrecognised_measurement_has_no_series(repo, knowledge):
    """У показателя без идентификатора нечего откладывать по оси."""
    client, snapshot = _client_with_snapshot(repo)
    stored = repo.snapshots.add_measurement(
        snapshot.id, "", "Гомоцистеин", 12.0, "12", "мкмоль/л", date(2026, 8, 20)
    )
    repo.snapshots.confirm_measurement(stored.id, snapshot.id)
    _approved_draft(repo, snapshot.id)

    data = _collect(repo, knowledge, snapshot.id)

    assert data.series == ()


def test_document_text_does_not_reach_the_report(repo, knowledge):
    """Название с бланка может нести что угодно, вплоть до клиники и телефона."""
    client, snapshot = _client_with_snapshot(repo)
    stored = repo.snapshots.add_measurement(
        snapshot.id,
        "",
        "SOLOVYOVA I.A. Ферритин",
        18.0,
        "18",
        "нг/мл",
        date(2026, 8, 20),
    )
    repo.snapshots.confirm_measurement(stored.id, snapshot.id)
    _approved_draft(repo, snapshot.id)

    data = _collect(repo, knowledge, snapshot.id)

    (finding,) = [f for f in data.findings if f.row_id == stored.id]
    assert finding.title == UNRESOLVED_TITLE
    assert finding.value == 18.0
    assert finding.status == STATUS_NO_RULE
    assert "SOLOVYOVA" not in repr(data)


def _approved_draft_with_dynamics(repo, snapshot_id):
    """Черновик, в котором есть раздел «динамика»: только под ним печатается график."""
    repo.drafts.save_section(snapshot_id, "показатели", "Текст показателей.", ())
    repo.drafts.save_section(snapshot_id, "динамика", "Это точка отсчёта.", ())
    repo.drafts.approve(snapshot_id, datetime(2026, 9, 2, 10, 0))


def _rendered(data):
    return render_report_html(data, Jinja2Templates(directory=str(TEMPLATES_DIR)))


def test_series_carries_the_units_and_the_corridor_from_the_knowledge_base(
    repo, knowledge
):
    """Подпись оси и коридор — из базы знаний коуча, а не откуда придётся.

    Ни одно утверждение об этом не стояло: `target` можно было занулить, и
    коридор молча исчез бы со всех графиков продукта, а `units` подменить
    названием показателя, и подпись «Ферритин, Ферритин» никого бы не
    остановила. Единицы здесь ещё и синоним референсных («мкг/л»), то
    есть арифметики между ними нет: точка остаётся, подпись — каноническая.
    """
    _, snapshot = _client_with_snapshot(repo)
    stored = repo.snapshots.add_measurement(
        snapshot.id, "ферритин", "Ферритин", 18.0, "18", "мкг/л", date(2026, 8, 20)
    )
    repo.snapshots.confirm_measurement(stored.id, snapshot.id)
    _approved_draft(repo, snapshot.id)

    data = _collect(repo, knowledge, snapshot.id)

    (series,) = data.series
    assert series.title == "Ферритин"
    assert series.units == "нг/мл"
    assert series.target == Interval(60, 90)
    assert [p.value for p in series.points] == [18.0]


def test_a_measurement_whose_units_did_not_match_does_not_enter_the_series(
    repo, knowledge
):
    """Чего вердикт отказался судить, того график не рисует.

    Калий 2.4 мг/дл — это около 0.61 ммоль/л. Сохранён он как есть: показатель
    распознан, а пересчёта из мг/дл коуч не объявлял, поэтому `analyte_id`
    выставлен, а единицы остались с бланка. Пока ряд отбирался по одному
    `analyte_id`, эта точка попадала на график, откладывалась по оси,
    подписанной «ммоль/л», и клиент видел падение с 4.2 под нижнюю границу
    коридора. Падения не было.
    """
    client, march = _client_with_snapshot(repo, date(2026, 3, 1))
    september = repo.snapshots.create(client.code, date(2026, 9, 1))
    matched = repo.snapshots.add_measurement(
        march.id, "калий", "Калий", 4.2, "4.2", "ммоль/л", date(2026, 3, 1)
    )
    mismatched = repo.snapshots.add_measurement(
        september.id, "калий", "Калий", 2.4, "2.4", "мг/дл", date(2026, 9, 1)
    )
    repo.snapshots.confirm_measurement(matched.id, march.id)
    repo.snapshots.confirm_measurement(mismatched.id, september.id)
    _approved_draft(repo, september.id)

    data = _collect(repo, knowledge, september.id)

    (verdict,) = [f for f in data.findings if f.subject_id == "калий"]
    assert verdict.status == STATUS_UNIT_MISMATCH
    assert verdict.target is None

    (series,) = data.series
    assert series.units == "ммоль/л"
    assert [p.value for p in series.points] == [4.2]
    assert series.has_dynamics is False


def test_an_older_snapshot_shows_no_measurement_taken_after_it(repo, knowledge):
    """Отчёт по мартовскому срезу не знает про сентябрьский забор.

    Коуч печатает отчёт заново когда угодно, в том числе через полгода.
    Без верхней границы по дате мартовский PDF получал график, дотянутый до
    сентябрьского значения, — и спорил сам с собой: находки собраны по
    одному срезу, модель написала «это точка отсчёта», а рядом линия.
    """
    client, march = _client_with_snapshot(repo, date(2026, 3, 1))
    september = repo.snapshots.create(client.code, date(2026, 9, 1))
    early = repo.snapshots.add_measurement(
        march.id, "ферритин", "Ферритин", 18.0, "18", "нг/мл", date(2026, 2, 20)
    )
    late = repo.snapshots.add_measurement(
        september.id, "ферритин", "Ферритин", 45.0, "45", "нг/мл", date(2026, 8, 25)
    )
    repo.snapshots.confirm_measurement(early.id, march.id)
    repo.snapshots.confirm_measurement(late.id, september.id)
    _approved_draft_with_dynamics(repo, march.id)
    _approved_draft_with_dynamics(repo, september.id)

    march_data = _collect(repo, knowledge, march.id)
    (series,) = march_data.series
    assert [p.value for p in series.points] == [18.0]
    assert series.has_dynamics is False
    assert "<svg" not in _rendered(march_data)

    september_data = _collect(repo, knowledge, september.id)
    (series,) = september_data.series
    assert [p.value for p in series.points] == [18.0, 45.0]
    assert series.has_dynamics is True
    assert _rendered(september_data).count("<svg") == 1


HOSTILE_LABEL = "MEDLAB 4471 Ферритин"
HOSTILE_UNITS = "ед/MEDLAB +7 916 555-11-22"


def test_document_text_is_masked_the_same_way_for_the_model_and_for_the_report(
    repo, knowledge
):
    """Маска на текст бланка одна, и проверена она на обоих путях сразу.

    Копий было две, и они разошлись: вход модели закрывал заголовок,
    единицы и заметку, а сборка отчёта — только заголовок, так что
    единицы с бланка и заметка, цитирующая их дословно, доходили до
    `ReportData` нетронутыми. Пока их никто не печатал, это было незаметно;
    таблица ключевых показателей их печатает. Оба пути проверяются здесь
    вместе, чтобы разойтись им было негде.
    """
    questionnaire, references = knowledge
    client, snapshot = _client_with_snapshot(repo)
    unresolved = repo.snapshots.add_measurement(
        snapshot.id, "", HOSTILE_LABEL, 18.0, "18", HOSTILE_UNITS, date(2026, 8, 20)
    )
    mismatched = repo.snapshots.add_measurement(
        snapshot.id, "ферритин", "Ферритин", 18.0, "18", HOSTILE_UNITS, date(2026, 8, 20)
    )
    for stored in (unresolved, mismatched):
        repo.snapshots.confirm_measurement(stored.id, snapshot.id)
    _approved_draft(repo, snapshot.id)

    subject = Subject(sex="ж", age=41)
    findings = collect_findings(
        questionnaire,
        references,
        {},
        [
            Measurement(m.analyte_id, m.value, m.units, label=m.raw_name, row_id=m.id)
            for m in repo.snapshots.measurements(snapshot.id)
        ],
        subject,
    )
    payload = build_payload(
        findings,
        subject,
        "",
        load_specialists(SPECIALISTS).public_view(),
        repo.clients.get(client.code),
    )
    data = _collect(repo, knowledge, snapshot.id)
    report = repr(data.findings)
    printed = _rendered(data)

    for secret in (HOSTILE_LABEL, HOSTILE_UNITS, "MEDLAB", "555-11-22"):
        assert secret not in payload
        assert secret not in report
        assert secret not in printed
    for safe in (UNRESOLVED_TITLE, DOCUMENT_UNITS):
        assert safe in payload
        assert safe in report
        assert safe in printed


def test_the_coachs_own_note_reaches_the_model_but_not_the_client(repo, knowledge):
    """Заметка коуча — клиническая рамка для модели и не текст для клиента.

    «Растёт при воспалении — смотреть вместе с СРБ» — это то, без чего
    трактовка беднее, и другого канала у неё нет: `трактовать_с` в базе
    знаний есть, а модели не уходит вовсе. Поэтому модель заметку
    получает.

    Клиент — нет: писалась она не ему, и однажды в ней может оказаться
    «направить к врачу: Петров И.Л., +7 916 555-11-22». Со стороны клиента
    заметка снимается устройством, а не просьбой в инструкции.
    """
    questionnaire, references = knowledge
    client, snapshot = _client_with_snapshot(repo)
    stored = repo.snapshots.add_measurement(
        snapshot.id, "ферритин", "Ферритин", 18.0, "18", "нг/мл", date(2026, 8, 20)
    )
    repo.snapshots.confirm_measurement(stored.id, snapshot.id)
    _approved_draft(repo, snapshot.id)

    note = references.analyte("ферритин").note
    assert note, "у ферритина в базе знаний есть заметка — иначе тест ничего не держит"

    subject = Subject(sex="ж", age=41)
    findings = collect_findings(
        questionnaire,
        references,
        {},
        [Measurement("ферритин", 18.0, "нг/мл", label="Ферритин", row_id=stored.id)],
        subject,
    )
    payload = build_payload(
        findings,
        subject,
        "",
        load_specialists(SPECIALISTS).public_view(),
        repo.clients.get(client.code),
    )
    data = _collect(repo, knowledge, snapshot.id)

    assert note in payload
    assert note not in repr(data.findings)
    assert note not in _rendered(data)
    # Само число на месте на обоих путях: снята заметка, а не находка.
    assert "18" in payload
    assert "18 нг/мл" in _rendered(data)


def test_a_note_copied_from_the_clients_own_document_reaches_neither(repo, knowledge):
    """Заметка про несопоставленные единицы цитирует бланк дословно.

    Она не из базы знаний коуча, а из документа клиента, и разрешение,
    выданное заметке коуча, её не касается: закрыта обеим сторонам.
    """
    questionnaire, references = knowledge
    client, snapshot = _client_with_snapshot(repo)
    stored = repo.snapshots.add_measurement(
        snapshot.id, "ферритин", "Ферритин", 18.0, "18", HOSTILE_UNITS, date(2026, 8, 20)
    )
    repo.snapshots.confirm_measurement(stored.id, snapshot.id)
    _approved_draft(repo, snapshot.id)

    subject = Subject(sex="ж", age=41)
    findings = collect_findings(
        questionnaire,
        references,
        {},
        [Measurement("ферритин", 18.0, HOSTILE_UNITS, label="Ферритин", row_id=stored.id)],
        subject,
    )
    (finding,) = [f for f in findings if f.subject_id == "ферритин"]
    assert HOSTILE_UNITS in finding.note, "заметка обязана цитировать бланк — иначе тест пуст"

    payload = build_payload(
        findings,
        subject,
        "",
        load_specialists(SPECIALISTS).public_view(),
        repo.clients.get(client.code),
    )
    data = _collect(repo, knowledge, snapshot.id)

    for text in (finding.note, HOSTILE_UNITS):
        assert text not in payload
        assert text not in repr(data.findings)
        assert text not in _rendered(data)


def test_incomplete_client_card_is_refused(repo, knowledge):
    """Карточка без пола и даты рождения — брак карточек до версии схемы 2."""
    repo.clients._connection.execute(
        "INSERT INTO identities (code, full_name, sex, birth_date, contacts, note) "
        "VALUES (?, ?, '', '', NULL, NULL)",
        ("CL-0001", "Иванова Мария"),
    )
    snapshot = repo.snapshots.create("CL-0001", date(2026, 9, 1))
    _approved_draft(repo, snapshot.id)

    with pytest.raises(ReportError, match="CL-0001"):
        _collect(repo, knowledge, snapshot.id)


# План 4, задача 4: свод по набору срезов доходит до отчёта.


def test_report_includes_an_indicator_submitted_only_in_an_older_member(
    repo, knowledge
):
    """Показатель, сданный лишь в старом срезе набора, доходит до отчёта."""
    client, march = _client_with_snapshot(repo, date(2026, 3, 1))
    september = repo.snapshots.create(client.code, date(2026, 9, 1))
    old_only = repo.snapshots.add_measurement(
        march.id, "кальций", "Кальций", 9.5, "9.5", "мг/дл", date(2026, 3, 1)
    )
    repo.snapshots.confirm_measurement(old_only.id, march.id)
    repo.scopes.set_members(september.id, [march.id, september.id])
    _approved_draft(repo, september.id)

    data = _collect(repo, knowledge, september.id)

    (finding,) = [f for f in data.findings if f.subject_id == "кальций"]
    assert finding.value == 9.5
    # Дата находки — дата самого измерения, а не дата отчёта.
    assert finding.taken_on == date(2026, 3, 1)


def test_series_appears_for_an_indicator_absent_from_the_primary_snapshot(
    repo, knowledge
):
    """Список показателей графика берётся из свода, а не из первичного среза."""
    client, march = _client_with_snapshot(repo, date(2026, 3, 1))
    september = repo.snapshots.create(client.code, date(2026, 9, 1))
    old_only = repo.snapshots.add_measurement(
        march.id, "кальций", "Кальций", 9.5, "9.5", "мг/дл", date(2026, 3, 1)
    )
    repo.snapshots.confirm_measurement(old_only.id, march.id)
    repo.scopes.set_members(september.id, [march.id, september.id])
    _approved_draft(repo, september.id)

    data = _collect(repo, knowledge, september.id)

    (series,) = data.series
    assert series.analyte_id == "кальций"
    assert [p.value for p in series.points] == [9.5]


def test_a_single_member_scope_matches_todays_behaviour(repo, knowledge):
    """Правило 7: срез без сохранённого набора отчёт собирает как раньше."""
    client, snapshot = _client_with_snapshot(repo)
    stored = repo.snapshots.add_measurement(
        snapshot.id, "ферритин", "Ферритин", 18.0, "18", "нг/мл", date(2026, 8, 20)
    )
    repo.snapshots.confirm_measurement(stored.id, snapshot.id)
    _approved_draft(repo, snapshot.id)

    data = _collect(repo, knowledge, snapshot.id)

    (finding,) = [f for f in data.findings if f.subject_id == "ферритин"]
    assert finding.value == 18.0
    (series,) = data.series
    assert series.analyte_id == "ферритин"
