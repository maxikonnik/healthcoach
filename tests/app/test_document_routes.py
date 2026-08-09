from datetime import date
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from healthcoach.app.deps import build_context
from healthcoach.app.main import create_app

KNOWLEDGE = Path(__file__).parents[2] / "knowledge"
FIXTURES = Path(__file__).parents[1] / "intake" / "fixtures"

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


def test_unsupported_format_is_refused(client):
    test_client, _ = client
    snapshot_id = _snapshot(test_client)
    response = test_client.post(
        f"/snapshots/{snapshot_id}/documents",
        files={"file": ("бланк.docx", b"nope", "application/octet-stream")},
        follow_redirects=False,
    )
    assert response.status_code == 400


def test_unknown_snapshot_is_404(client):
    test_client, _ = client
    response = test_client.post(
        "/snapshots/999/documents",
        files={"file": ("бланк.pdf", b"%PDF-1.4", "application/pdf")},
        follow_redirects=False,
    )
    assert response.status_code == 404


def test_value_can_be_filled_in_by_hand(client):
    """У «<0.60» числа нет: коуч решает, что вписать."""
    test_client, context = client
    snapshot_id = _snapshot(test_client)
    with context.session() as repo:
        stored = repo.snapshots.add_measurement(
            snapshot_id,
            analyte_id="ферритин",
            raw_name="Ферритин",
            value=None,
            raw_value="<0.60",
            units="нг/мл",
            taken_on=date(2026, 8, 20),
        )

    test_client.post(
        f"/snapshots/{snapshot_id}/measurements/{stored.id}/value",
        data={"value": "0,3"},
    )

    (read_back,) = _measurements(context, snapshot_id)
    assert read_back.value == 0.3
    assert read_back.raw_value == "<0.60"


def test_value_of_another_snapshot_is_404(client):
    test_client, context = client
    first = _snapshot(test_client)
    test_client.post("/clients/CL-0001/snapshots", data={"taken_on": "2026-10-01"})
    with context.session() as repo:
        second = repo.snapshots.for_client("CL-0001")[-1].id
        stored = repo.snapshots.add_measurement(
            second,
            analyte_id="ферритин",
            raw_name="Ферритин",
            value=None,
            raw_value="<0.60",
            units="нг/мл",
            taken_on=date(2026, 8, 20),
        )

    response = test_client.post(
        f"/snapshots/{first}/measurements/{stored.id}/value",
        data={"value": "0.3"},
        follow_redirects=False,
    )
    assert response.status_code == 404


_HEADER = "Показатель Результат Ед. изм. Референсные значения"


def test_unparsed_line_reaches_the_coach_but_not_the_measurements(client, monkeypatch):
    """Строка, которую разбор не понял, обязана дойти до коуча текстом —
    и не имеет права осесть в базе под видом измерения."""
    test_client, context = client
    snapshot_id = _snapshot(test_client)
    lines = [
        _HEADER,
        "Ферритин 50 нг/мл 20 - 250",
        "Загадочная строка 12,3",
    ]
    monkeypatch.setattr(
        "healthcoach.intake.documents.read_pdf_lines", lambda _path: lines
    )

    response = test_client.post(
        f"/snapshots/{snapshot_id}/documents",
        files={"file": ("бланк.pdf", b"%PDF-1.4", "application/pdf")},
    )

    assert response.status_code == 200
    assert "Загадочная строка 12,3" in response.text

    stored = _measurements(context, snapshot_id)
    assert len(stored) == 1
    assert all("Загадочная" not in m.raw_name for m in stored)


def test_shown_import_count_matches_what_was_stored(client, monkeypatch):
    test_client, context = client
    snapshot_id = _snapshot(test_client)
    lines = [
        _HEADER,
        "Ферритин 50 нг/мл 20 - 250",
        "Витамин Д 30 нг/мл 30 - 100",
    ]
    monkeypatch.setattr(
        "healthcoach.intake.documents.read_pdf_lines", lambda _path: lines
    )

    response = test_client.post(
        f"/snapshots/{snapshot_id}/documents",
        files={"file": ("бланк.pdf", b"%PDF-1.4", "application/pdf")},
    )

    stored = _measurements(context, snapshot_id)
    assert len(stored) == 2
    assert f"импортировано показателей: {len(stored)}" in response.text


def test_fully_parsed_document_shows_no_unparsed_section(client, monkeypatch):
    """Пустая секция «не понято», которая рисуется всегда, — тот же шум,
    что и её отсутствие, когда она нужна."""
    test_client, context = client
    snapshot_id = _snapshot(test_client)
    lines = [
        _HEADER,
        "Ферритин 50 нг/мл 20 - 250",
    ]
    monkeypatch.setattr(
        "healthcoach.intake.documents.read_pdf_lines", lambda _path: lines
    )

    response = test_client.post(
        f"/snapshots/{snapshot_id}/documents",
        files={"file": ("бланк.pdf", b"%PDF-1.4", "application/pdf")},
    )

    assert response.status_code == 200
    assert "Не понято" not in response.text


def test_non_numeric_value_is_refused(client):
    test_client, context = client
    snapshot_id = _snapshot(test_client)
    with context.session() as repo:
        stored = repo.snapshots.add_measurement(
            snapshot_id,
            analyte_id="ферритин",
            raw_name="Ферритин",
            value=None,
            raw_value="<0.60",
            units="нг/мл",
            taken_on=date(2026, 8, 20),
        )

    response = test_client.post(
        f"/snapshots/{snapshot_id}/measurements/{stored.id}/value",
        data={"value": "мало"},
        follow_redirects=False,
    )
    assert response.status_code == 400


# Раунд правок 2: пять находок ревью.


def test_unparsed_lines_survive_a_page_reload(client, monkeypatch):
    """До правки строки, которые разбор не понял, показывались один раз —
    в ответе на сам POST — и терялись на первом же обновлении страницы."""
    test_client, context = client
    snapshot_id = _snapshot(test_client)
    lines = [
        _HEADER,
        "Ферритин 50 нг/мл 20 - 250",
        "Загадочная строка 12,3",
    ]
    monkeypatch.setattr(
        "healthcoach.intake.documents.read_pdf_lines", lambda _path: lines
    )
    test_client.post(
        f"/snapshots/{snapshot_id}/documents",
        files={"file": ("бланк.pdf", b"%PDF-1.4", "application/pdf")},
    )

    reloaded = test_client.get(f"/snapshots/{snapshot_id}")

    assert reloaded.status_code == 200
    assert "Загадочная строка 12,3" in reloaded.text


def test_attached_documents_are_listed_with_original_filenames(client, monkeypatch):
    test_client, context = client
    snapshot_id = _snapshot(test_client)
    lines = [_HEADER, "Ферритин 50 нг/мл 20 - 250"]
    monkeypatch.setattr(
        "healthcoach.intake.documents.read_pdf_lines", lambda _path: lines
    )
    test_client.post(
        f"/snapshots/{snapshot_id}/documents",
        files={"file": ("Биохимия 22.08.pdf", b"%PDF-1.4", "application/pdf")},
    )

    reloaded = test_client.get(f"/snapshots/{snapshot_id}")

    assert "Биохимия 22.08.pdf" in reloaded.text


def test_uploading_the_same_file_twice_is_not_refused(client, monkeypatch):
    """Повторная загрузка — решение коуча, не наше: маршрут не имеет права
    отказать в ней сам."""
    test_client, context = client
    snapshot_id = _snapshot(test_client)
    lines = [_HEADER, "Ферритин 50 нг/мл 20 - 250"]
    monkeypatch.setattr(
        "healthcoach.intake.documents.read_pdf_lines", lambda _path: lines
    )

    first = test_client.post(
        f"/snapshots/{snapshot_id}/documents",
        files={"file": ("бланк.pdf", b"%PDF-1.4", "application/pdf")},
    )
    second = test_client.post(
        f"/snapshots/{snapshot_id}/documents",
        files={"file": ("бланк.pdf", b"%PDF-1.4", "application/pdf")},
    )

    assert first.status_code == 200
    assert second.status_code == 200
    with context.session() as repo:
        assert len(repo.documents.for_snapshot(snapshot_id)) == 2
    assert len(_measurements(context, snapshot_id)) == 2


def test_failed_upload_leaves_no_row_and_no_file(client):
    test_client, context = client
    snapshot_id = _snapshot(test_client)

    response = test_client.post(
        f"/snapshots/{snapshot_id}/documents",
        files={"file": ("бланк.docx", b"nope", "application/octet-stream")},
    )

    assert response.status_code == 400
    with context.session() as repo:
        assert repo.documents.for_snapshot(snapshot_id) == []
    folder = context.documents_dir / str(snapshot_id)
    assert not folder.exists()


def test_failed_upload_of_an_unreadable_pdf_leaves_no_row_and_no_file(client):
    """Тот же отказ, но с другой стороны read_document: файл с именем .pdf,
    который PdfError отвергает по содержимому, а не по расширению."""
    test_client, context = client
    snapshot_id = _snapshot(test_client)

    response = test_client.post(
        f"/snapshots/{snapshot_id}/documents",
        files={"file": ("бланк.pdf", b"\xff\xd8\xff", "application/pdf")},
    )

    assert response.status_code == 400
    with context.session() as repo:
        assert repo.documents.for_snapshot(snapshot_id) == []
    folder = context.documents_dir / str(snapshot_id)
    assert not folder.exists()


def test_unexpected_error_from_read_document_still_cleans_up(client, monkeypatch):
    """read_document документирует единый тип ошибки, но не гарантирует
    его: сорвись что-то незаявленное, временный файл не должен остаться
    висеть без строки в базе, которая дала бы коучу его увидеть или
    удалить."""
    test_client, context = client
    snapshot_id = _snapshot(test_client)

    def _boom(_path, _engine=None):
        raise RuntimeError("что-то пошло не так")

    monkeypatch.setattr("healthcoach.app.routes_documents.read_document", _boom)

    with pytest.raises(RuntimeError):
        test_client.post(
            f"/snapshots/{snapshot_id}/documents",
            files={"file": ("бланк.pdf", b"%PDF-1.4", "application/pdf")},
        )

    with context.session() as repo:
        assert repo.documents.for_snapshot(snapshot_id) == []
    folder = context.documents_dir / str(snapshot_id)
    assert not folder.exists()


def test_error_message_names_the_coachs_filename_once(client):
    """Раньше в сообщении дважды повторялось служебное имя файла на диске
    («1.pdf: 1.pdf: файл не прочитан...») — коуч загружал «бланк.pdf» и не
    видел этого имени вовсе."""
    test_client, _ = client
    snapshot_id = _snapshot(test_client)

    response = test_client.post(
        f"/snapshots/{snapshot_id}/documents",
        files={"file": ("бланк.pdf", b"\xff\xd8\xff", "application/pdf")},
    )

    assert response.status_code == 400
    detail = response.json()["detail"]
    assert detail.count("бланк.pdf") == 1


def test_stored_path_is_recorded(client, monkeypatch):
    """Document.stored_path раньше всегда оставался пустой строкой."""
    test_client, context = client
    snapshot_id = _snapshot(test_client)
    lines = [_HEADER, "Ферритин 50 нг/мл 20 - 250"]
    monkeypatch.setattr(
        "healthcoach.intake.documents.read_pdf_lines", lambda _path: lines
    )

    test_client.post(
        f"/snapshots/{snapshot_id}/documents",
        files={"file": ("бланк.pdf", b"%PDF-1.4", "application/pdf")},
    )

    with context.session() as repo:
        (document,) = repo.documents.for_snapshot(snapshot_id)
    assert document.stored_path
    assert Path(document.stored_path).read_bytes() == b"%PDF-1.4"


def test_value_for_a_measurement_that_does_not_exist_is_404(client):
    test_client, _ = client
    snapshot_id = _snapshot(test_client)

    response = test_client.post(
        f"/snapshots/{snapshot_id}/measurements/99999/value",
        data={"value": "0.3"},
        follow_redirects=False,
    )

    assert response.status_code == 404


def test_value_already_filled_is_refused_but_not_reported_as_missing(client):
    """Повторная отправка формы (или отклик по старой вкладке) находит
    строку на месте — 404 сказал бы коучу, что число потерялось."""
    test_client, context = client
    snapshot_id = _snapshot(test_client)
    with context.session() as repo:
        stored = repo.snapshots.add_measurement(
            snapshot_id,
            analyte_id="ферритин",
            raw_name="Ферритин",
            value=18.0,
            raw_value="18.0",
            units="нг/мл",
            taken_on=date(2026, 8, 20),
        )

    response = test_client.post(
        f"/snapshots/{snapshot_id}/measurements/{stored.id}/value",
        data={"value": "99"},
        follow_redirects=False,
    )

    assert response.status_code != 404
    assert response.status_code < 500
    (read_back,) = _measurements(context, snapshot_id)
    assert read_back.value == 18.0


def test_document_import_leaves_measurements_unconfirmed(client, monkeypatch):
    test_client, context = client
    snapshot_id = _snapshot(test_client)
    lines = [_HEADER, "Ферритин 50 нг/мл 20 - 250"]
    monkeypatch.setattr(
        "healthcoach.intake.documents.read_pdf_lines", lambda _path: lines
    )

    test_client.post(
        f"/snapshots/{snapshot_id}/documents",
        files={"file": ("бланк.pdf", b"%PDF-1.4", "application/pdf")},
    )

    stored = _measurements(context, snapshot_id)
    assert stored
    assert all(not m.confirmed for m in stored)


def test_document_import_records_the_source(client, monkeypatch):
    test_client, context = client
    snapshot_id = _snapshot(test_client)
    lines = [_HEADER, "Ферритин 50 нг/мл 20 - 250"]
    monkeypatch.setattr(
        "healthcoach.intake.documents.read_pdf_lines", lambda _path: lines
    )

    test_client.post(
        f"/snapshots/{snapshot_id}/documents",
        files={"file": ("бланк.pdf", b"%PDF-1.4", "application/pdf")},
    )

    stored = _measurements(context, snapshot_id)
    assert stored
    assert all(m.source == "pdf" for m in stored)
