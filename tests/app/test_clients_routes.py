from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from healthcoach.app.deps import build_context
from healthcoach.app.main import create_app

KNOWLEDGE = Path(__file__).parents[2] / "knowledge"

WOMAN = {"full_name": "Иванова Мария", "sex": "ж", "birth_date": "1990-05-17"}


@pytest.fixture
def client(tmp_path):
    context = build_context(data_dir=tmp_path, knowledge_dir=KNOWLEDGE)
    with TestClient(create_app(context)) as test_client:
        yield test_client


def test_empty_client_list_renders(client):
    response = client.get("/")
    assert response.status_code == 200
    assert "Клиенты" in response.text


def test_adding_a_client_shows_it_in_the_list(client):
    client.post("/clients", data=WOMAN | {"contacts": "@masha"})
    response = client.get("/")
    assert "Иванова Мария" in response.text
    assert "CL-0001" in response.text


def test_client_card_shows_code_and_name(client):
    client.post("/clients", data=WOMAN)
    response = client.get("/clients/CL-0001")
    assert response.status_code == 200
    assert "CL-0001" in response.text
    assert "Иванова Мария" in response.text


def test_unknown_client_is_404(client):
    assert client.get("/clients/CL-9999").status_code == 404


def test_creating_a_snapshot_lists_it_on_the_card(client):
    client.post("/clients", data=WOMAN)
    client.post("/clients/CL-0001/snapshots", data={"taken_on": "2026-09-01"})
    response = client.get("/clients/CL-0001")
    assert "2026-09-01" in response.text


def test_empty_name_is_rejected(client):
    response = client.post("/clients", data=WOMAN | {"full_name": "   "})
    assert response.status_code == 400


def test_questionnaire_download_is_html(client):
    client.post("/clients", data=WOMAN)
    response = client.get("/clients/CL-0001/questionnaire")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert "CL-0001" in response.text
    assert "attachment" in response.headers.get("content-disposition", "")


def test_requests_from_different_threads_all_reach_the_database(client):
    """Обработчики выполняются в пуле потоков, соединение нельзя делить.

    sqlite3.Connection принадлежит потоку, в котором создан. Если соединение
    станет общим на всё приложение, эти запросы упадут с ProgrammingError.
    """
    client.post("/clients", data=WOMAN)

    with ThreadPoolExecutor(max_workers=8) as pool:
        responses = list(
            pool.map(lambda _: client.get("/clients/CL-0001"), range(24))
        )

    assert [r.status_code for r in responses] == [200] * 24
    assert all("Иванова Мария" in r.text for r in responses)


def test_questionnaire_can_include_extra_blocks(client):
    client.post("/clients", data=WOMAN)
    response = client.get(
        "/clients/CL-0001/questionnaire", params={"extra": "oprosnik_candida"}
    )
    assert "ОПРОСНИК CANDIDA" in response.text


def test_incomplete_card_can_be_filled_in_from_the_page(client):
    """Карточки от прежней версии схемы остаются пустыми — их надо чем-то чинить."""
    client.post("/clients", data=WOMAN)
    response = client.post(
        "/clients/CL-0001",
        data={"sex": "м", "birth_date": "1985-03-02", "contacts": "@petr"},
        follow_redirects=True,
    )
    assert response.status_code == 200
    assert "1985-03-02" in response.text
    assert "@petr" in response.text


def test_updating_an_unknown_client_is_404(client):
    response = client.post(
        "/clients/CL-9999",
        data={"sex": "м", "birth_date": "1985-03-02"},
        follow_redirects=False,
    )
    assert response.status_code == 404


def test_birth_date_in_the_future_is_refused(client):
    response = client.post("/clients", data=WOMAN | {"birth_date": "2099-01-01"})
    assert response.status_code == 400


KUZNETSOVA = {"full_name": "Кузнецова Ольга", "sex": "ж", "birth_date": "1988-02-02"}


def test_unconfirmed_measurement_badge_shows_on_dashboard(client):
    client.post("/clients", data=WOMAN)
    client.post("/clients/CL-0001/snapshots", data={"taken_on": "2026-09-01"})
    client.post(
        "/snapshots/1/measurements",
        data={
            "raw_name": "Ферритин",
            "value": "18",
            "units": "нг/мл",
            "taken_on": "2026-08-20",
        },
    )
    response = client.get("/")
    assert "не сверено: 1" in response.text


def test_client_with_later_snapshot_is_listed_first(client):
    client.post("/clients", data=WOMAN)
    client.post("/clients/CL-0001/snapshots", data={"taken_on": "2026-08-01"})
    client.post("/clients", data=KUZNETSOVA)
    client.post("/clients/CL-0002/snapshots", data={"taken_on": "2026-09-01"})
    response = client.get("/")
    text = response.text
    assert text.index(KUZNETSOVA["full_name"]) < text.index(WOMAN["full_name"])


def test_client_without_snapshots_is_listed_last(client):
    client.post("/clients", data=WOMAN)
    client.post("/clients/CL-0001/snapshots", data={"taken_on": "2026-08-01"})
    client.post("/clients", data=KUZNETSOVA)
    response = client.get("/")
    text = response.text
    assert text.index(WOMAN["full_name"]) < text.index(KUZNETSOVA["full_name"])
    assert "нет срезов" in text


def test_incomplete_card_with_fresh_snapshot_sorts_above_complete_stale_one(tmp_path):
    """Незаполненная карточка не должна прятать свежий срез внизу списка."""
    import sqlite3

    context = build_context(data_dir=tmp_path, knowledge_dir=KNOWLEDGE)
    with TestClient(create_app(context)) as test_client:
        test_client.post("/clients", data=WOMAN)
        test_client.post("/clients/CL-0001/snapshots", data={"taken_on": "2026-08-01"})
        test_client.post("/clients", data=KUZNETSOVA)
        test_client.post("/clients/CL-0002/snapshots", data={"taken_on": "2026-09-01"})
        connection = sqlite3.connect(context.database_path)
        connection.execute(
            "UPDATE identities SET sex = '', birth_date = '' WHERE code = 'CL-0002'"
        )
        connection.commit()
        connection.close()

        response = test_client.get("/")

    text = response.text
    assert text.index(KUZNETSOVA["full_name"]) < text.index(WOMAN["full_name"])
    assert "2026-09-01" in text


def test_add_client_form_is_collapsed_in_details(client):
    response = client.get("/")
    text = response.text
    details_start = text.index("<details>")
    details_end = text.index("</details>")
    form_start = text.index('action="/clients"')
    assert details_start < form_start < details_end


# План 4, задача 4: карточка ставит работу (срезы) выше паспорта.


def test_snapshots_block_comes_before_the_passport_form(client):
    client.post("/clients", data=WOMAN)
    client.post("/clients/CL-0001/snapshots", data={"taken_on": "2026-09-01"})
    text = client.get("/clients/CL-0001").text
    snapshots_heading = text.index("<h2>Срезы</h2>")
    passport_form = text.index('action="/clients/CL-0001"')
    assert snapshots_heading < passport_form


def test_passport_form_is_open_when_the_card_is_incomplete(tmp_path):
    """От схемы версии 1 карточки достаются пустыми — коуч обязан сразу
    увидеть форму, а не искать её под свёрнутым <summary>."""
    import sqlite3

    context = build_context(data_dir=tmp_path, knowledge_dir=KNOWLEDGE)
    with TestClient(create_app(context)) as test_client:
        test_client.post("/clients", data=WOMAN)
        # Так выглядит карточка, доставшаяся от схемы версии 1.
        connection = sqlite3.connect(context.database_path)
        connection.execute("UPDATE identities SET sex = '', birth_date = ''")
        connection.commit()
        connection.close()

        page = test_client.get("/clients/CL-0001").text

    summary_start = page.index("<summary>Паспортные данные")
    details_start = page.rindex("<details", 0, summary_start)
    details_tag = page[details_start:summary_start]
    assert "open" in details_tag


def test_passport_form_is_collapsed_when_the_card_is_complete(client):
    client.post("/clients", data=WOMAN | {"contacts": "@masha"})
    page = client.get("/clients/CL-0001").text
    summary_start = page.index("<summary>Паспортные данные")
    details_start = page.rindex("<details", 0, summary_start)
    details_tag = page[details_start:summary_start]
    assert "open" not in details_tag


# План 4/2026-08-10, задача 5: кнопка и выбор срезов на карточке клиента.


class FakeProvider:
    def __init__(self):
        self.prompts = []

    def complete(self, prompt: str) -> str:
        self.prompts.append(prompt)
        return "Текст раздела."


@pytest.fixture
def client_and_context(tmp_path):
    import dataclasses

    context = dataclasses.replace(
        build_context(data_dir=tmp_path, knowledge_dir=KNOWLEDGE), llm=FakeProvider()
    )
    with TestClient(create_app(context)) as test_client:
        yield test_client, context


def _approve_draft(test_client, context, snapshot_id: int) -> None:
    """Провести срез через измерение, находку, запрос и утверждение
    черновика — тот же путь, что и в tests/app/test_report_routes.py."""
    test_client.post(
        f"/snapshots/{snapshot_id}/measurements",
        data={
            "raw_name": "Ферритин", "value": "18", "units": "нг/мл",
            "taken_on": "2026-06-20",
        },
    )
    with context.session() as repo:
        (stored,) = repo.snapshots.measurements(snapshot_id)
    test_client.post(f"/snapshots/{snapshot_id}/measurements/{stored.id}/confirm")
    test_client.post(f"/snapshots/{snapshot_id}/request", data={"raw": "Устал"})
    test_client.post(
        f"/snapshots/{snapshot_id}/request/redact", data={"redacted": "Устал"}
    )
    test_client.post(f"/snapshots/{snapshot_id}/request/approve")
    test_client.post(f"/snapshots/{snapshot_id}/draft")
    test_client.post(f"/snapshots/{snapshot_id}/draft/approve")


def _snapshot_ids(test_client, context, code="CL-0001") -> list[int]:
    with context.session() as repo:
        return [s.id for s in repo.snapshots.for_client(code)]


def test_report_redirects_to_the_freshest_snapshot_draft(client_and_context):
    test_client, context = client_and_context
    test_client.post("/clients", data=WOMAN)
    test_client.post("/clients/CL-0001/snapshots", data={"taken_on": "2026-01-10"})
    test_client.post("/clients/CL-0001/snapshots", data={"taken_on": "2026-06-20"})
    old_id, new_id = _snapshot_ids(test_client, context)

    response = test_client.post(
        "/clients/CL-0001/reports",
        data={"snapshot_ids": [old_id, new_id]},
        follow_redirects=False,
    )

    assert response.status_code == 303
    assert response.headers["location"] == f"/snapshots/{new_id}/draft"


def test_same_date_primary_is_the_larger_id_not_form_order(client_and_context):
    """Ревью: две сдачи в один день — первичный срез должен решаться по
    (taken_on, id) самого среза, а не по порядку появления в форме."""
    test_client, context = client_and_context
    test_client.post("/clients", data=WOMAN)
    test_client.post("/clients/CL-0001/snapshots", data={"taken_on": "2026-06-20"})
    test_client.post("/clients/CL-0001/snapshots", data={"taken_on": "2026-06-20"})
    smaller_id, larger_id = _snapshot_ids(test_client, context)
    assert larger_id > smaller_id

    response = test_client.post(
        "/clients/CL-0001/reports",
        # Меньший id указан первым в форме — если сортировка держится на
        # (taken_on, id), это не должно повлиять на выбор первичного среза.
        data={"snapshot_ids": [smaller_id, larger_id]},
        follow_redirects=False,
    )

    assert response.headers["location"] == f"/snapshots/{larger_id}/draft"
    with context.session() as repo:
        assert repo.scopes.members(larger_id) == sorted([smaller_id, larger_id])


def test_report_saves_the_chosen_scope(client_and_context):
    test_client, context = client_and_context
    test_client.post("/clients", data=WOMAN)
    test_client.post("/clients/CL-0001/snapshots", data={"taken_on": "2026-01-10"})
    test_client.post("/clients/CL-0001/snapshots", data={"taken_on": "2026-06-20"})
    old_id, new_id = _snapshot_ids(test_client, context)

    test_client.post(
        "/clients/CL-0001/reports", data={"snapshot_ids": [old_id, new_id]}
    )

    with context.session() as repo:
        assert repo.scopes.members(new_id) == sorted([old_id, new_id])


def test_empty_selection_is_refused(client_and_context):
    test_client, context = client_and_context
    test_client.post("/clients", data=WOMAN)
    test_client.post("/clients/CL-0001/snapshots", data={"taken_on": "2026-01-10"})

    response = test_client.post("/clients/CL-0001/reports", data={})

    assert response.status_code == 400


def test_unknown_client_reports_is_404(client_and_context):
    test_client, _ = client_and_context
    response = test_client.post("/clients/CL-9999/reports", data={"snapshot_ids": [1]})
    assert response.status_code == 404


def test_foreign_snapshot_is_refused_and_scope_is_untouched(client_and_context):
    test_client, context = client_and_context
    test_client.post("/clients", data=WOMAN)
    test_client.post("/clients/CL-0001/snapshots", data={"taken_on": "2026-01-10"})
    test_client.post("/clients/CL-0001/snapshots", data={"taken_on": "2026-06-20"})
    a_old, a_new = _snapshot_ids(test_client, context)

    test_client.post(
        "/clients", data={"full_name": "Петров Пётр", "sex": "м", "birth_date": "1988-01-01"}
    )
    test_client.post("/clients/CL-0002/snapshots", data={"taken_on": "2026-07-01"})
    with context.session() as repo:
        (b_snap,) = repo.snapshots.for_client("CL-0002")

    # Легитимный набор сначала — чтобы было что не менять.
    test_client.post(
        "/clients/CL-0001/reports", data={"snapshot_ids": [a_old, a_new]}
    )

    response = test_client.post(
        "/clients/CL-0001/reports",
        data={"snapshot_ids": [a_old, b_snap.id]},
    )

    assert response.status_code == 400
    with context.session() as repo:
        assert repo.scopes.members(a_new) == sorted([a_old, a_new])


def test_approved_draft_refuses_rebuild_and_scope_is_untouched(client_and_context):
    test_client, context = client_and_context
    test_client.post("/clients", data=WOMAN)
    test_client.post("/clients/CL-0001/snapshots", data={"taken_on": "2026-01-10"})
    test_client.post("/clients/CL-0001/snapshots", data={"taken_on": "2026-06-20"})
    old_id, new_id = _snapshot_ids(test_client, context)

    test_client.post(
        "/clients/CL-0001/reports", data={"snapshot_ids": [old_id, new_id]}
    )
    _approve_draft(test_client, context, new_id)

    response = test_client.post(
        "/clients/CL-0001/reports", data={"snapshot_ids": [new_id]}
    )

    assert response.status_code == 409
    assert response.json()["detail"] == "черновик утверждён и не пересобирается"
    with context.session() as repo:
        assert repo.scopes.members(new_id) == sorted([old_id, new_id])


def test_resubmitting_a_scope_replaces_the_previous_one(client_and_context):
    test_client, context = client_and_context
    test_client.post("/clients", data=WOMAN)
    test_client.post("/clients/CL-0001/snapshots", data={"taken_on": "2026-01-10"})
    test_client.post("/clients/CL-0001/snapshots", data={"taken_on": "2026-06-20"})
    old_id, new_id = _snapshot_ids(test_client, context)

    test_client.post(
        "/clients/CL-0001/reports", data={"snapshot_ids": [old_id, new_id]}
    )
    test_client.post("/clients/CL-0001/reports", data={"snapshot_ids": [new_id]})

    with context.session() as repo:
        assert repo.scopes.members(new_id) == [new_id]


def test_freshest_snapshot_checkbox_is_checked_by_default(client_and_context):
    test_client, context = client_and_context
    test_client.post("/clients", data=WOMAN)
    test_client.post("/clients/CL-0001/snapshots", data={"taken_on": "2026-01-10"})
    test_client.post("/clients/CL-0001/snapshots", data={"taken_on": "2026-06-20"})
    old_id, new_id = _snapshot_ids(test_client, context)

    page = test_client.get("/clients/CL-0001").text

    old_row = page.index(f'value="{old_id}"')
    new_row = page.index(f'value="{new_id}"')
    old_checkbox = page[old_row - 20 : old_row + 60]
    new_checkbox = page[new_row - 20 : new_row + 60]
    assert "checked" not in old_checkbox
    assert "checked" in new_checkbox


def test_approval_racing_the_scope_write_is_409_not_500(
    client_and_context, monkeypatch
):
    """Утверждение прошло между проверкой маршрута и записью набора.

    Ровно та же гонка, что у разделов черновика: хранилище отказывает,
    маршрут переводит отказ в 409, а не роняет 500. Подмена `set_members`
    воспроизводит именно этот зазор — иначе его в тесте не поймать.
    """
    from healthcoach.storage.scopes import ReportScopeRepository

    test_client, context = client_and_context
    test_client.post("/clients", data=WOMAN)
    test_client.post("/clients/CL-0001/snapshots", data={"taken_on": "2026-01-10"})
    test_client.post("/clients/CL-0001/snapshots", data={"taken_on": "2026-06-20"})
    old_id, new_id = _snapshot_ids(test_client, context)

    def refuse(self, snapshot_id, member_ids):
        raise ValueError(
            f"черновик среза {snapshot_id} утверждён — набор срезов не меняется"
        )

    monkeypatch.setattr(ReportScopeRepository, "set_members", refuse)

    response = test_client.post(
        "/clients/CL-0001/reports", data={"snapshot_ids": [old_id, new_id]}
    )

    assert response.status_code == 409
    assert "утверждён" in response.json()["detail"]
