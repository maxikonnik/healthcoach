import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from healthcoach.app.deps import build_context
from healthcoach.app.main import create_app
from healthcoach.intake.questionnaire_html import PAYLOAD_VERSION

KNOWLEDGE = Path(__file__).parents[2] / "knowledge"


@pytest.fixture
def client(tmp_path):
    context = build_context(data_dir=tmp_path, knowledge_dir=KNOWLEDGE)
    with TestClient(create_app(context)) as test_client:
        yield test_client, context


def _snapshot(test_client) -> int:
    test_client.post("/clients", data={"full_name": "Иванова Мария"})
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
    test_client.post("/clients", data={"full_name": "Петров Пётр"})

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


def test_findings_respect_the_sex_parameter(client):
    """Пол влияет на выбор целевого коридора: у мужчин ферритин выше."""
    test_client, context = client
    snapshot_id = _snapshot(test_client)
    test_client.post(
        f"/snapshots/{snapshot_id}/measurements",
        data={
            "raw_name": "Ферритин",
            "value": "70",
            "units": "нг/мл",
            "taken_on": "2026-08-20",
        },
    )
    (stored,) = _measurements(context, snapshot_id)
    test_client.post(f"/snapshots/{snapshot_id}/measurements/{stored.id}/confirm")

    female = test_client.get(
        f"/snapshots/{snapshot_id}/findings", params={"sex": "ж", "age": 32}
    ).text
    male = test_client.get(
        f"/snapshots/{snapshot_id}/findings", params={"sex": "м", "age": 32}
    ).text
    assert "в целевом" in female
    assert "ниже целевого" in male


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
