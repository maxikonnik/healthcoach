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
