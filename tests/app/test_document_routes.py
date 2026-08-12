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


# План 4, задача 4: якоря возврата.

_ANCHOR_INDICATORS = "%D0%BF%D0%BE%D0%BA%D0%B0%D0%B7%D0%B0%D1%82%D0%B5%D0%BB%D0%B8"
"""Percent-encoded «показатели»: RedirectResponse кодирует Location через
urllib.parse.quote — заголовок HTTP не может нести кириллицу как есть."""


def test_set_value_redirects_back_to_the_indicators_anchor(client):
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
        data={"value": "0,3"},
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert response.headers["location"].endswith(f"#{_ANCHOR_INDICATORS}")


def test_document_upload_form_points_at_the_documents_anchor(client):
    """Загрузка документа рендерит страницу напрямую (не редирект — иначе
    сводка «импортировано показателей» не пережила бы переход), так что
    якорь возврата несёт не Location, а адрес формы: браузер применяет
    фрагмент из того же URL, на который отправлена форма."""
    test_client, _ = client
    snapshot_id = _snapshot(test_client)
    page = test_client.get(f"/snapshots/{snapshot_id}").text
    assert (
        f'action="/snapshots/{snapshot_id}/documents#документы"' in page
    )


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


def test_not_a_table_document_shows_the_refusal_on_the_snapshot_screen(
    client, monkeypatch
):
    """УЗИ, протокол, рекомендации — связный текст без шапки таблицы.

    Раньше отказ уходил голой JSON-страницей (`{"detail": "..."}`) — коуч
    видела её вместо экрана среза, из которого только что грузила файл.
    Теперь при этом классе отказа страница рендерится как обычно, с
    сообщением прямо на ней.
    """
    test_client, context = client
    snapshot_id = _snapshot(test_client)
    lines = ["Заключение: без патологии", "Печень не увеличена, контуры ровные"]
    monkeypatch.setattr(
        "healthcoach.intake.documents.read_pdf_lines", lambda _path: lines
    )

    response = test_client.post(
        f"/snapshots/{snapshot_id}/documents",
        files={"file": ("узи.pdf", b"%PDF-1.4", "application/pdf")},
    )

    assert response.status_code == 400
    assert "не похоже на таблицу" in response.text
    # Это правда экран среза, а не голый JSON: воронка шагов всё ещё видна.
    assert "Показатели" in response.text
    with context.session() as repo:
        assert repo.documents.for_snapshot(snapshot_id) == []
    folder = context.documents_dir / str(snapshot_id)
    assert not folder.exists()


def test_empty_document_shows_the_refusal_on_the_snapshot_screen(client, monkeypatch):
    """Пустой PDF (нет текстового слоя) — другое сообщение, тоже на экране
    среза, а не в JSON."""
    test_client, context = client
    snapshot_id = _snapshot(test_client)
    monkeypatch.setattr(
        "healthcoach.intake.documents.read_pdf_lines", lambda _path: []
    )

    response = test_client.post(
        f"/snapshots/{snapshot_id}/documents",
        files={"file": ("бланк.pdf", b"%PDF-1.4", "application/pdf")},
    )

    assert response.status_code == 400
    assert "не нашлось текста" in response.text
    assert "Показатели" in response.text
    with context.session() as repo:
        assert repo.documents.for_snapshot(snapshot_id) == []


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


# Task 6: неточно опознанная шапка — под подтверждение коуча.

_HEADER_TYPO = "Показатель Результат Ел. изм. Референсные пределы"
"""«Ел. изм.» вместо «Ед. изм.» — опечатка распознавания в самой шапке.
Колонка опознаётся по расстоянию редактирования, то есть догадкой."""


def _upload(test_client, snapshot_id, lines, monkeypatch, filename="бланк.pdf"):
    monkeypatch.setattr(
        "healthcoach.intake.documents.read_pdf_lines", lambda _path: lines
    )
    return test_client.post(
        f"/snapshots/{snapshot_id}/documents",
        files={"file": (filename, b"%PDF-1.4", "application/pdf")},
    )


def _staging_files(context, snapshot_id):
    folder = context.documents_dir / str(snapshot_id)
    return sorted(p.name for p in folder.iterdir()) if folder.exists() else []


def test_inexact_header_creates_no_measurements_until_confirmed(client, monkeypatch):
    """Догадка не имеет права молча стать данными.

    Шапка опознана неточно — значит колонка может стоять не на своём месте,
    и референс окажется в единицах. Загрузка показывает догадку и ждёт;
    измерений до подтверждения нет ни одного.
    """
    test_client, context = client
    snapshot_id = _snapshot(test_client)
    lines = [_HEADER_TYPO, "Ферритин 45 нг/мл 10 - 120"]

    response = _upload(test_client, snapshot_id, lines, monkeypatch)

    assert response.status_code == 200
    assert _measurements(context, snapshot_id) == []
    with context.session() as repo:
        assert repo.documents.for_snapshot(snapshot_id) == []
    # Файл ждёт решения коуча во временном имени — том же механизме, что
    # убирает за неудачной загрузкой.
    assert [name.startswith(".upload-") for name in _staging_files(context, snapshot_id)] == [True]


def test_confirmation_screen_shows_the_header_the_columns_and_first_rows(
    client, monkeypatch
):
    """Подтверждать вслепую нечего: коуч видит строку шапки как её прочитало
    распознавание, роли колонок и первые разобранные строки."""
    test_client, context = client
    snapshot_id = _snapshot(test_client)
    lines = [_HEADER_TYPO, "Ферритин 45 нг/мл 10 - 120"]

    page = _upload(test_client, snapshot_id, lines, monkeypatch).text

    assert "Ел. изм." in page
    assert "единицы" in page
    assert "Ферритин" in page
    assert "45" in page
    assert "Да, колонки верные" in page


def test_confirmed_inexact_header_imports_the_measurements(client, monkeypatch):
    test_client, context = client
    snapshot_id = _snapshot(test_client)
    lines = [_HEADER_TYPO, "Ферритин 45 нг/мл 10 - 120"]
    _upload(test_client, snapshot_id, lines, monkeypatch, filename="Биохимия.pdf")
    (staging,) = _staging_files(context, snapshot_id)

    response = test_client.post(
        f"/snapshots/{snapshot_id}/documents/confirm",
        data={"staging": staging, "filename": "Биохимия.pdf"},
    )

    assert response.status_code == 200
    stored = _measurements(context, snapshot_id)
    assert len(stored) == 1
    assert stored[0].units == "нг/мл"
    with context.session() as repo:
        (document,) = repo.documents.for_snapshot(snapshot_id)
    assert document.filename == "Биохимия.pdf"
    assert Path(document.stored_path).is_file()
    assert not any(name.startswith(".upload-") for name in _staging_files(context, snapshot_id))


def test_cancelled_inexact_header_leaves_no_row_and_no_file(client, monkeypatch):
    test_client, context = client
    snapshot_id = _snapshot(test_client)
    lines = [_HEADER_TYPO, "Ферритин 45 нг/мл 10 - 120"]
    _upload(test_client, snapshot_id, lines, monkeypatch)
    (staging,) = _staging_files(context, snapshot_id)

    response = test_client.post(
        f"/snapshots/{snapshot_id}/documents/cancel", data={"staging": staging}
    )

    assert response.status_code == 200
    assert _measurements(context, snapshot_id) == []
    with context.session() as repo:
        assert repo.documents.for_snapshot(snapshot_id) == []
    assert not (context.documents_dir / str(snapshot_id)).exists()


def test_exact_header_is_imported_without_a_confirmation_screen(client, monkeypatch):
    """Обычный случай не имеет права стать длиннее на один экран и клик."""
    test_client, context = client
    snapshot_id = _snapshot(test_client)
    lines = [_HEADER, "Ферритин 45 нг/мл 10 - 120"]

    page = _upload(test_client, snapshot_id, lines, monkeypatch).text

    assert "Да, колонки верные" not in page
    assert len(_measurements(context, snapshot_id)) == 1


def test_confirming_a_staging_name_outside_the_folder_is_refused(client, monkeypatch):
    """Имя временного файла приходит из формы, то есть от кого угодно.

    Форма подтверждения — единственное место, где имя файла на диске
    приходит запросом; принять его как есть значило бы позволить прочитать
    и импортировать любой файл машины.
    """
    test_client, context = client
    snapshot_id = _snapshot(test_client)
    lines = [_HEADER_TYPO, "Ферритин 45 нг/мл 10 - 120"]
    _upload(test_client, snapshot_id, lines, monkeypatch)

    response = test_client.post(
        f"/snapshots/{snapshot_id}/documents/confirm",
        data={"staging": "../../../etc/passwd", "filename": "чужое.pdf"},
        follow_redirects=False,
    )

    assert response.status_code == 400
    assert _measurements(context, snapshot_id) == []


def test_confirming_a_vanished_upload_is_404(client):
    test_client, context = client
    snapshot_id = _snapshot(test_client)

    response = test_client.post(
        f"/snapshots/{snapshot_id}/documents/confirm",
        data={"staging": f".upload-{'0' * 32}.pdf", "filename": "бланк.pdf"},
        follow_redirects=False,
    )

    assert response.status_code == 404
    assert _measurements(context, snapshot_id) == []


def _upload_text_document(test_client, snapshot_id, lines):
    """Загрузить документ с заранее известным текстом.

    Чтение подменяется: проверяется предупреждение о чужом клиенте, а не
    разбор PDF, который проверен своими тестами.
    """
    import healthcoach.app.routes_documents as routes
    from healthcoach.intake.documents import ReadDocument
    from healthcoach.intake.lab_table import parse_lab_lines
    from healthcoach.storage.snapshots import SOURCE_PDF

    original = routes.read_document

    def fake(path, engine=None):
        return ReadDocument(
            source=SOURCE_PDF, lines=tuple(lines), table=parse_lab_lines(lines)
        )

    routes.read_document = fake
    try:
        return test_client.post(
            f"/snapshots/{snapshot_id}/documents",
            files={"file": ("бланк.pdf", b"%PDF-1.4", "application/pdf")},
        ).text
    finally:
        routes.read_document = original


def test_document_of_another_client_is_flagged_not_refused(client):
    """Распознавание коверкает буквы: ложный отказ хуже предупреждения."""
    test_client, context = client
    snapshot_id = _snapshot(test_client)

    lines = [
        "Ф.И.О. пациента: Петров Пётр Петрович",
        "Показатель Результат Ед. изм. Референсные пределы",
        "Ферритин 45 нг/мл 10 - 120",
    ]
    page = _upload_text_document(test_client, snapshot_id, lines)

    assert "Петров" in page
    assert "не найдена" in page
    with context.session() as repo:
        assert repo.snapshots.measurements(snapshot_id)


def test_document_of_this_client_is_not_flagged(client):
    test_client, context = client
    snapshot_id = _snapshot(test_client)

    lines = [
        "Ф.И.О. пациента: Иванова Мария Сергеевна",
        "Показатель Результат Ед. изм. Референсные пределы",
        "Ферритин 45 нг/мл 10 - 120",
    ]
    page = _upload_text_document(test_client, snapshot_id, lines)

    assert "не найдена" not in page


# Раунд ревью 1: фамилия короче четырёх букв выпадает из name_stems, и
# stems[0] оказывается именем, а не фамилией.

SHORT_SURNAME = {"full_name": "Ким Мария Сергеевна", "sex": "ж", "birth_date": "1990-05-17"}
"""«Ким» короче MIN_PART: name_stems даёт ['Мария', 'Сергеев'] — без
фамилии вовсе. Первый элемент — не фамилия, а имя."""


def _snapshot_short_surname(test_client) -> int:
    test_client.post("/clients", data=SHORT_SURNAME)
    test_client.post("/clients/CL-0001/snapshots", data={"taken_on": "2026-09-01"})
    return 1


def test_stranger_document_warns_for_client_with_short_surname(client):
    """До правки проверялся только stems[0] = 'Мария' — совпадение по
    распространённому имени давало чужому документу пройти незамеченным,
    хотя фамилия («Петрова») никак не связана с клиентом («Ким»)."""
    test_client, context = client
    snapshot_id = _snapshot_short_surname(test_client)

    lines = [
        "Ф.И.О. пациента: Петрова Анна Викторовна",
        "Показатель Результат Ед. изм. Референсные пределы",
        "Ферритин 45 нг/мл 10 - 120",
    ]
    page = _upload_text_document(test_client, snapshot_id, lines)

    assert "не найдена" in page


def test_own_document_of_short_surname_client_is_not_flagged(client):
    """До правки та же ошибка била и в обратную сторону: имя усечено
    распознаванием до инициала («М.»), и stems[0] = 'Мария' не находился —
    ложная тревога на собственном документе клиента, хотя отчество
    («Сергеевна») в тексте читается полностью."""
    test_client, context = client
    snapshot_id = _snapshot_short_surname(test_client)

    lines = [
        "Ф.И.О. пациента: Ким М. Сергеевна",
        "Показатель Результат Ед. изм. Референсные пределы",
        "Ферритин 45 нг/мл 10 - 120",
    ]
    page = _upload_text_document(test_client, snapshot_id, lines)

    assert "не найдена" not in page
