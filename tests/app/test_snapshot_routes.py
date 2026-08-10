import json
import sqlite3
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from healthcoach.app.deps import build_context
from healthcoach.app.main import create_app
from healthcoach.intake.questionnaire_html import PAYLOAD_VERSION

KNOWLEDGE = Path(__file__).parents[2] / "knowledge"

WOMAN = {"full_name": "Иванова Мария", "sex": "ж", "birth_date": "1990-05-17"}


@pytest.fixture
def client(tmp_path):
    context = build_context(data_dir=tmp_path, knowledge_dir=KNOWLEDGE)
    with TestClient(create_app(context)) as test_client:
        yield test_client, context


def _snapshot(test_client) -> int:
    test_client.post("/clients", data=WOMAN)
    test_client.post("/clients/CL-0001/snapshots", data={"taken_on": "2026-09-01"})
    return 1


def _measurements(context, snapshot_id):
    with context.session() as repo:
        return repo.snapshots.measurements(snapshot_id)


def _stored_answers(context, snapshot_id):
    with context.session() as repo:
        return repo.snapshots.answers(snapshot_id)


def _answers_file(context, answers, blocks):
    body = {
        "версия": PAYLOAD_VERSION,
        "клиент": "CL-0001",
        "спецификация": context.questionnaire.version,
        "блоки": blocks,
        "ответы": answers,
    }
    return json.dumps(body, ensure_ascii=False).encode("utf-8")


def test_snapshot_page_renders(client):
    test_client, _ = client
    snapshot_id = _snapshot(test_client)
    response = test_client.get(f"/snapshots/{snapshot_id}")
    assert response.status_code == 200
    assert "CL-0001" in response.text


def test_unknown_snapshot_is_404(client):
    test_client, _ = client
    assert test_client.get("/snapshots/999").status_code == 404


def test_measurement_is_recognised_and_stored(client):
    test_client, context = client
    snapshot_id = _snapshot(test_client)
    test_client.post(
        f"/snapshots/{snapshot_id}/measurements",
        data={
            "raw_name": "Ферритин (S-Ferritin)",
            "value": "18",
            "units": "нг/мл",
            "taken_on": "2026-08-20",
        },
    )
    (stored,) = _measurements(context, snapshot_id)
    assert stored.analyte_id == "ферритин"
    assert stored.value == 18.0
    assert stored.confirmed is False


def test_alias_units_are_converted_on_entry(client):
    test_client, context = client
    snapshot_id = _snapshot(test_client)
    test_client.post(
        f"/snapshots/{snapshot_id}/measurements",
        data={
            "raw_name": "Ферритин",
            "value": "18",
            "units": "мкг/л",
            "taken_on": "2026-08-20",
        },
    )
    (stored,) = _measurements(context, snapshot_id)
    assert stored.units == "нг/мл"
    assert stored.value == 18.0


def test_unknown_analyte_is_stored_and_flagged(client):
    test_client, context = client
    snapshot_id = _snapshot(test_client)
    test_client.post(
        f"/snapshots/{snapshot_id}/measurements",
        data={
            "raw_name": "Гомоцистеин",
            "value": "12",
            "units": "мкмоль/л",
            "taken_on": "2026-08-20",
        },
    )
    (stored,) = _measurements(context, snapshot_id)
    assert stored.analyte_id == ""
    assert stored.raw_name == "Гомоцистеин"

    page = test_client.get(f"/snapshots/{snapshot_id}").text
    assert "не распознан" in page


def test_unmatched_units_are_stored_and_flagged(client):
    test_client, context = client
    snapshot_id = _snapshot(test_client)
    test_client.post(
        f"/snapshots/{snapshot_id}/measurements",
        data={
            "raw_name": "Ферритин",
            "value": "18",
            "units": "пмоль/л",
            "taken_on": "2026-08-20",
        },
    )
    (stored,) = _measurements(context, snapshot_id)
    assert stored.units == "пмоль/л"
    page = test_client.get(f"/snapshots/{snapshot_id}").text
    assert "единицы" in page


def test_declared_unit_synonym_is_not_flagged_as_a_mismatch(client):
    """Регресс: `_rows` (routes_snapshots.py) сравнивал единицы прямым
    равенством строк и не знал про объявленные синонимы — измерение,
    хранящееся в объявленном (но не канонизированном) синониме, выглядело
    бы для коуча как несопоставленное, хотя коуч сам объявил его равным."""
    from datetime import date

    test_client, context = client
    snapshot_id = _snapshot(test_client)
    with context.session() as repo:
        repo.snapshots.add_measurement(
            snapshot_id,
            analyte_id="ферритин",
            raw_name="Ферритин",
            value=75.0,
            raw_value="75",
            units="мкг/л",
            taken_on=date(2026, 8, 20),
        )

    page = test_client.get(f"/snapshots/{snapshot_id}").text
    assert "единицы не сопоставлены" not in page


def test_confirming_a_measurement_shows_it_as_confirmed(client):
    test_client, context = client
    snapshot_id = _snapshot(test_client)
    test_client.post(
        f"/snapshots/{snapshot_id}/measurements",
        data={
            "raw_name": "Ферритин",
            "value": "18",
            "units": "нг/мл",
            "taken_on": "2026-08-20",
        },
    )
    (stored,) = _measurements(context, snapshot_id)
    test_client.post(f"/snapshots/{snapshot_id}/measurements/{stored.id}/confirm")
    (again,) = _measurements(context, snapshot_id)
    assert again.confirmed is True


def test_answers_upload_is_stored(client):
    test_client, context = client
    snapshot_id = _snapshot(test_client)
    block = context.questionnaire.block("obraz_zizni")
    answers = {q.id: min(o.score for o in q.options()) for q in block.questions}
    core = [b.id for b in context.questionnaire.blocks if b.core]

    response = test_client.post(
        f"/snapshots/{snapshot_id}/answers",
        files={
            "file": ("ответы.json", _answers_file(context, answers, core), "application/json")
        },
    )
    assert response.status_code == 200
    assert _stored_answers(context, snapshot_id) == answers


def test_upload_reports_skipped_but_not_the_blocks_never_shown(client):
    """Коуч видит, что клиент пропустил, и не видит того, чего ему не слали."""
    test_client, context = client
    snapshot_id = _snapshot(test_client)
    block = context.questionnaire.block("obraz_zizni")
    answers = {block.questions[0].id: 0}
    core = [b.id for b in context.questionnaire.blocks if b.core]

    page = test_client.post(
        f"/snapshots/{snapshot_id}/answers",
        files={
            "file": ("ответы.json", _answers_file(context, answers, core), "application/json")
        },
    ).text

    assert block.questions[1].id in page
    candida = context.questionnaire.block("oprosnik_candida")
    assert candida.questions[0].id not in page


def test_answers_of_another_client_are_refused(client):
    """В папке загрузок у коуча лежат файлы всех клиентов, различаются именем."""
    test_client, context = client
    snapshot_id = _snapshot(test_client)
    test_client.post(
        "/clients",
        data={"full_name": "Петров Пётр", "sex": "м", "birth_date": "1985-03-02"},
    )

    block = context.questionnaire.block("obraz_zizni")
    answers = {q.id: min(o.score for o in q.options()) for q in block.questions}
    core = [b.id for b in context.questionnaire.blocks if b.core]
    body = {
        "версия": PAYLOAD_VERSION,
        "клиент": "CL-0002",
        "спецификация": context.questionnaire.version,
        "блоки": core,
        "ответы": answers,
    }
    payload = json.dumps(body, ensure_ascii=False).encode("utf-8")

    response = test_client.post(
        f"/snapshots/{snapshot_id}/answers",
        files={"file": ("ответы.json", payload, "application/json")},
        follow_redirects=False,
    )
    assert response.status_code == 400
    assert "CL-0002" in response.text
    assert _stored_answers(context, snapshot_id) == {}


def test_confirmation_does_not_reach_another_snapshot(client):
    """Идентификатор среза в адресе обязан что-то значить."""
    test_client, context = client
    first = _snapshot(test_client)
    test_client.post("/clients/CL-0001/snapshots", data={"taken_on": "2026-10-01"})
    second = first + 1

    test_client.post(
        f"/snapshots/{second}/measurements",
        data={
            "raw_name": "Ферритин",
            "value": "18",
            "units": "нг/мл",
            "taken_on": "2026-08-20",
        },
    )
    (stored,) = _measurements(context, second)

    response = test_client.post(
        f"/snapshots/{first}/measurements/{stored.id}/confirm", follow_redirects=False
    )
    assert response.status_code == 404
    (untouched,) = _measurements(context, second)
    assert untouched.confirmed is False


def test_confirming_a_measurement_that_does_not_exist_is_404(client):
    test_client, _ = client
    snapshot_id = _snapshot(test_client)
    response = test_client.post(
        f"/snapshots/{snapshot_id}/measurements/99999/confirm", follow_redirects=False
    )
    assert response.status_code == 404


def test_confirmed_unrecognised_measurement_reaches_the_findings(client):
    """Подтверждённый показатель не может исчезнуть из картины без следа."""
    test_client, context = client
    snapshot_id = _snapshot(test_client)
    test_client.post(
        f"/snapshots/{snapshot_id}/measurements",
        data={
            "raw_name": "Гомоцистеин",
            "value": "12",
            "units": "мкмоль/л",
            "taken_on": "2026-08-20",
        },
    )
    (stored,) = _measurements(context, snapshot_id)
    assert stored.analyte_id == ""

    before = test_client.get(f"/snapshots/{snapshot_id}/findings").text
    assert "Гомоцистеин" not in before

    test_client.post(f"/snapshots/{snapshot_id}/measurements/{stored.id}/confirm")
    after = test_client.get(f"/snapshots/{snapshot_id}/findings").text
    assert "Гомоцистеин" in after
    assert "правило не задано" in after


def test_broken_answers_upload_is_reported(client):
    test_client, _ = client
    snapshot_id = _snapshot(test_client)
    response = test_client.post(
        f"/snapshots/{snapshot_id}/answers",
        files={"file": ("плохо.json", b"{not json", "application/json")},
        follow_redirects=False,
    )
    assert response.status_code == 400


MAN = {"full_name": "Петров Пётр", "sex": "м", "birth_date": "1985-03-02"}


def _client_with_ferritin(test_client, context, card, code, value):
    """Клиент с подтверждённым ферритином. Возвращает идентификатор среза."""
    test_client.post("/clients", data=card)
    test_client.post(f"/clients/{code}/snapshots", data={"taken_on": "2026-09-01"})
    with context.session() as repo:
        snapshot_id = repo.snapshots.for_client(code)[-1].id
    test_client.post(
        f"/snapshots/{snapshot_id}/measurements",
        data={
            "raw_name": "Ферритин",
            "value": value,
            "units": "нг/мл",
            "taken_on": "2026-08-20",
        },
    )
    (stored,) = _measurements(context, snapshot_id)
    test_client.post(f"/snapshots/{snapshot_id}/measurements/{stored.id}/confirm")
    return snapshot_id


def test_findings_take_sex_from_the_client_card(client):
    """Целевой коридор ферритина у мужчин выше — пол нельзя подставлять.

    Ссылка на странице среза не передаёт ни пола, ни возраста: если бы
    маршрут подставлял их по умолчанию, находки считались бы для другого
    человека, и в отчёте это никак не было бы видно.
    """
    test_client, context = client

    female = _client_with_ferritin(test_client, context, WOMAN, "CL-0001", "70")
    male = _client_with_ferritin(test_client, context, MAN, "CL-0002", "70")

    assert "в целевом" in test_client.get(f"/snapshots/{female}/findings").text
    assert "ниже целевого" in test_client.get(f"/snapshots/{male}/findings").text


def test_findings_report_the_subject_they_were_computed_for(client):
    """Иначе подстановку нельзя было бы заметить, даже если она случится."""
    test_client, context = client
    snapshot_id = _client_with_ferritin(test_client, context, MAN, "CL-0001", "35")

    report = test_client.get(f"/snapshots/{snapshot_id}/findings").text
    assert "пол м" in report
    assert "возраст 41" in report
    assert "дефицит" in report


def test_age_is_taken_at_the_snapshot_date_not_today(client):
    """Иначе за год сопровождения возраст уедет и коридор сменится молча."""
    test_client, context = client
    test_client.post(
        "/clients",
        data={
            "full_name": "Петров Пётр",
            "sex": "м",
            "birth_date": "1985-03-02",
        },
    )
    test_client.post("/clients/CL-0001/snapshots", data={"taken_on": "2020-09-01"})
    with context.session() as repo:
        snapshot_id = repo.snapshots.for_client("CL-0001")[-1].id

    report = test_client.get(f"/snapshots/{snapshot_id}/findings").text
    assert "возраст 35" in report


def test_findings_refuse_an_incomplete_client_card(client):
    """Пустая карточка не должна подставлять пол — лучше отказ с объяснением."""
    test_client, context = client
    test_client.post("/clients", data=WOMAN)
    test_client.post("/clients/CL-0001/snapshots", data={"taken_on": "2026-09-01"})
    with context.session() as repo:
        snapshot_id = repo.snapshots.for_client("CL-0001")[-1].id

    # Так выглядит карточка, доставшаяся от схемы версии 1.
    connection = sqlite3.connect(context.database_path)
    connection.execute("UPDATE identities SET sex = '', birth_date = ''")
    connection.commit()
    connection.close()

    response = test_client.get(f"/snapshots/{snapshot_id}/findings")
    assert response.status_code == 400
    assert "не заполнена" in response.text


def test_findings_use_the_recorded_scope_not_just_this_snapshot(client):
    """Текстовая выгрузка находок идёт тем же путём, что и отчёт (план 4, задача 4)."""
    test_client, context = client
    test_client.post("/clients", data=WOMAN)
    test_client.post("/clients/CL-0001/snapshots", data={"taken_on": "2026-03-01"})
    test_client.post("/clients/CL-0001/snapshots", data={"taken_on": "2026-09-01"})
    with context.session() as repo:
        old_id, new_id = [s.id for s in repo.snapshots.for_client("CL-0001")]
    test_client.post(
        f"/snapshots/{old_id}/measurements",
        data={
            "raw_name": "Ферритин", "value": "18", "units": "нг/мл",
            "taken_on": "2026-02-20",
        },
    )
    (stored,) = _measurements(context, old_id)
    test_client.post(f"/snapshots/{old_id}/measurements/{stored.id}/confirm")
    with context.session() as repo:
        repo.scopes.set_members(new_id, [old_id, new_id])

    report = test_client.get(f"/snapshots/{new_id}/findings").text

    assert "Ферритин" in report
    assert "18" in report


def test_findings_dump_blocks_derived_index_across_snapshots(client):
    """Ревью: `to_measurements` — единственная проекция StoredMeasurement →
    Measurement, разделяемая routes_report.py, routes_snapshots.py и
    report/data.py. Если бы этот сайт (или одна из его прежних трёх копий)
    забыл snapshot_id, compute_derived перестал бы видеть, что операнды
    из разных срезов, и посчитал бы производный индекс из мартовского
    кальция и августовского калия — то, что не должен означать (правило
    5). Дамп находок на экране среза обязан отказаться считать его так
    же, как отказывается PDF."""
    test_client, context = client
    test_client.post("/clients", data=WOMAN)
    test_client.post("/clients/CL-0001/snapshots", data={"taken_on": "2026-03-01"})
    test_client.post("/clients/CL-0001/snapshots", data={"taken_on": "2026-09-01"})
    with context.session() as repo:
        old_id, new_id = [s.id for s in repo.snapshots.for_client("CL-0001")]
    test_client.post(
        f"/snapshots/{old_id}/measurements",
        data={
            "raw_name": "Кальций", "value": "10", "units": "мг/дл",
            "taken_on": "2026-03-10",
        },
    )
    test_client.post(
        f"/snapshots/{new_id}/measurements",
        data={
            "raw_name": "Калий", "value": "4", "units": "ммоль/л",
            "taken_on": "2026-08-09",
        },
    )
    (calcium,) = _measurements(context, old_id)
    (potassium,) = _measurements(context, new_id)
    test_client.post(f"/snapshots/{old_id}/measurements/{calcium.id}/confirm")
    test_client.post(f"/snapshots/{new_id}/measurements/{potassium.id}/confirm")
    with context.session() as repo:
        repo.scopes.set_members(new_id, [old_id, new_id])

    report = test_client.get(f"/snapshots/{new_id}/findings").text

    assert "Соотношение кальций/калий" in report
    assert "не удалось вычислить" in report
    assert "2.5" not in report


class FakeProvider:
    """Заглушка модели для теста, доводящего срез до утверждённого черновика —
    без этого использовался бы настоящий ClaudeCodeProvider по умолчанию."""

    def complete(self, prompt: str) -> str:
        return "Текст раздела."


@pytest.fixture
def client_with_llm(tmp_path):
    import dataclasses

    context = dataclasses.replace(
        build_context(data_dir=tmp_path, knowledge_dir=KNOWLEDGE), llm=FakeProvider()
    )
    with TestClient(create_app(context)) as test_client:
        yield test_client, context


def test_steps_bar_shows_partial_indicators_step_linking_to_the_section(client):
    test_client, context = client
    snapshot_id = _snapshot(test_client)
    test_client.post(
        f"/snapshots/{snapshot_id}/measurements",
        data={
            "raw_name": "Ферритин", "value": "18", "units": "нг/мл",
            "taken_on": "2026-08-20",
        },
    )
    test_client.post(
        f"/snapshots/{snapshot_id}/measurements",
        data={
            "raw_name": "Калий", "value": "4.2", "units": "ммоль/л",
            "taken_on": "2026-08-20",
        },
    )
    (first, _second) = _measurements(context, snapshot_id)
    test_client.post(f"/snapshots/{snapshot_id}/measurements/{first.id}/confirm")

    page = test_client.get(f"/snapshots/{snapshot_id}").text
    assert "сверено 1 из 2" in page
    assert 'href="#показатели"' in page
    assert 'id="показатели"' in page


def test_steps_bar_pdf_step_links_to_the_report_after_draft_approval(client_with_llm):
    test_client, context = client_with_llm
    test_client.post("/clients", data=WOMAN)
    test_client.post("/clients/CL-0001/snapshots", data={"taken_on": "2026-09-01"})
    with context.session() as repo:
        snapshot_id = repo.snapshots.for_client("CL-0001")[-1].id
    test_client.post(
        f"/snapshots/{snapshot_id}/measurements",
        data={
            "raw_name": "Ферритин", "value": "18", "units": "нг/мл",
            "taken_on": "2026-08-20",
        },
    )
    (stored,) = _measurements(context, snapshot_id)
    test_client.post(f"/snapshots/{snapshot_id}/measurements/{stored.id}/confirm")

    test_client.post(f"/snapshots/{snapshot_id}/request", data={"raw": "Устал"})
    test_client.post(
        f"/snapshots/{snapshot_id}/request/redact", data={"redacted": "Устал"}
    )
    test_client.post(f"/snapshots/{snapshot_id}/request/approve")
    test_client.post(f"/snapshots/{snapshot_id}/draft")
    test_client.post(f"/snapshots/{snapshot_id}/draft/approve")

    page = test_client.get(f"/snapshots/{snapshot_id}").text
    assert f'href="/snapshots/{snapshot_id}/report.pdf"' in page


def test_steps_bar_shows_all_five_titles_on_an_empty_snapshot(client):
    test_client, _ = client
    snapshot_id = _snapshot(test_client)
    page = test_client.get(f"/snapshots/{snapshot_id}").text
    assert page.count('class="step ') == 5
    for title in ("Анкета", "Показатели", "Запрос", "Черновик", "PDF"):
        assert f"<b>{title}</b>" in page


# План 4, задача 4: якоря возврата — редирект ведёт назад к таблице
# показателей, а не к верху страницы.

_ANCHOR_INDICATORS = "%D0%BF%D0%BE%D0%BA%D0%B0%D0%B7%D0%B0%D1%82%D0%B5%D0%BB%D0%B8"
"""Percent-encoded «показатели»: RedirectResponse кодирует Location через
urllib.parse.quote — заголовок HTTP не может нести кириллицу как есть."""


def test_confirm_redirects_back_to_the_indicators_anchor(client):
    test_client, context = client
    snapshot_id = _snapshot(test_client)
    test_client.post(
        f"/snapshots/{snapshot_id}/measurements",
        data={
            "raw_name": "Ферритин", "value": "18", "units": "нг/мл",
            "taken_on": "2026-08-20",
        },
    )
    (stored,) = _measurements(context, snapshot_id)
    response = test_client.post(
        f"/snapshots/{snapshot_id}/measurements/{stored.id}/confirm",
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert response.headers["location"].endswith(f"#{_ANCHOR_INDICATORS}")


def test_add_measurement_redirects_back_to_the_indicators_anchor(client):
    test_client, _ = client
    snapshot_id = _snapshot(test_client)
    response = test_client.post(
        f"/snapshots/{snapshot_id}/measurements",
        data={
            "raw_name": "Ферритин", "value": "18", "units": "нг/мл",
            "taken_on": "2026-08-20",
        },
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert response.headers["location"].endswith(f"#{_ANCHOR_INDICATORS}")


def test_findings_use_only_confirmed_measurements(client):
    """Ворота сверки: неподтверждённое измерение в находки не идёт."""
    test_client, context = client
    snapshot_id = _snapshot(test_client)
    test_client.post(
        f"/snapshots/{snapshot_id}/measurements",
        data={
            "raw_name": "Ферритин",
            "value": "18",
            "units": "нг/мл",
            "taken_on": "2026-08-20",
        },
    )
    before = test_client.get(f"/snapshots/{snapshot_id}/findings").text
    assert "Ферритин" not in before

    (stored,) = _measurements(context, snapshot_id)
    test_client.post(f"/snapshots/{snapshot_id}/measurements/{stored.id}/confirm")
    after = test_client.get(f"/snapshots/{snapshot_id}/findings").text
    assert "Ферритин" in after
    assert "дефицит" in after
