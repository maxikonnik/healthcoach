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
