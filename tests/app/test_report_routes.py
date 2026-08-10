from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from healthcoach.app.deps import build_context
from healthcoach.app.main import create_app

KNOWLEDGE = Path(__file__).parents[2] / "knowledge"
WOMAN = {"full_name": "Соловьёва Ирина", "sex": "ж", "birth_date": "1985-03-24"}


class FakeProvider:
    def __init__(self, fail=False):
        self.fail = fail
        self.prompts = []

    def complete(self, prompt: str) -> str:
        from healthcoach.llm.provider import LLMError

        self.prompts.append(prompt)
        if self.fail:
            raise LLMError("модель недоступна")
        return "Текст раздела."


@pytest.fixture
def client(tmp_path):
    import dataclasses

    provider = FakeProvider()
    context = dataclasses.replace(
        build_context(data_dir=tmp_path, knowledge_dir=KNOWLEDGE), llm=provider
    )
    with TestClient(create_app(context)) as test_client:
        yield test_client, context, provider


def _approve_request(test_client, snapshot_id: int) -> None:
    """Провести запрос через ввод, вычитку и утверждение."""
    test_client.post(f"/snapshots/{snapshot_id}/request", data={"raw": "Устал"})
    test_client.post(
        f"/snapshots/{snapshot_id}/request/redact", data={"redacted": "Устал"}
    )
    test_client.post(f"/snapshots/{snapshot_id}/request/approve")


def _snapshot_with_a_finding(test_client, context) -> int:
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
    with context.session() as repo:
        (stored,) = repo.snapshots.measurements(snapshot_id)
    test_client.post(f"/snapshots/{snapshot_id}/measurements/{stored.id}/confirm")
    return snapshot_id


def test_request_is_saved_and_redaction_is_offered(client):
    test_client, context, _ = client
    snapshot_id = _snapshot_with_a_finding(test_client, context)

    test_client.post(
        f"/snapshots/{snapshot_id}/request",
        data={"raw": "Соловьёва Ирина хочет разобраться с усталостью"},
    )
    page = test_client.get(f"/snapshots/{snapshot_id}/draft").text

    # Исходный текст показан как есть — коуч должен видеть, с чем пришёл клиент.
    assert "Соловьёва Ирина хочет разобраться с усталостью" in page

    # Предложенная вычитка — содержимое поля «Уйдёт модели»: имя клиента из
    # неё убрано, а остальной текст запроса цел. Ниже на той же странице
    # есть форма «Переписать запрос», которая намеренно показывает исходный
    # текст ещё раз — окно среза нужно сузить до самого поля вычитки, чтобы
    # не зацепить её.
    start = page.index("Уйдёт модели") + len("Уйдёт модели")
    end = page.index("Сохранить вычитку", start)
    suggestion = page[start:end]
    assert "усталостью" in suggestion
    assert "Соловьёва" not in suggestion
    assert "Ирина" not in suggestion


def test_draft_is_refused_until_the_request_is_approved(client):
    """Решение партнёра: коуч вычитывает текст перед отправкой."""
    test_client, context, provider = client
    snapshot_id = _snapshot_with_a_finding(test_client, context)
    test_client.post(f"/snapshots/{snapshot_id}/request", data={"raw": "Устал"})

    response = test_client.post(
        f"/snapshots/{snapshot_id}/draft", follow_redirects=False
    )

    assert response.status_code == 400
    assert provider.prompts == []


def test_draft_is_generated_after_approval(client):
    test_client, context, provider = client
    snapshot_id = _snapshot_with_a_finding(test_client, context)
    test_client.post(f"/snapshots/{snapshot_id}/request", data={"raw": "Устал"})
    test_client.post(
        f"/snapshots/{snapshot_id}/request/redact", data={"redacted": "Устал"}
    )
    test_client.post(f"/snapshots/{snapshot_id}/request/approve")

    test_client.post(f"/snapshots/{snapshot_id}/draft")

    with context.session() as repo:
        sections = repo.drafts.sections(snapshot_id)
    assert len(sections) == 8
    assert provider.prompts


def test_section_can_be_edited_and_the_original_is_kept(client):
    test_client, context, _ = client
    snapshot_id = _snapshot_with_a_finding(test_client, context)
    test_client.post(f"/snapshots/{snapshot_id}/request", data={"raw": "Устал"})
    test_client.post(
        f"/snapshots/{snapshot_id}/request/redact", data={"redacted": "Устал"}
    )
    test_client.post(f"/snapshots/{snapshot_id}/request/approve")
    test_client.post(f"/snapshots/{snapshot_id}/draft")

    with context.session() as repo:
        section = repo.drafts.sections(snapshot_id)[0]
    test_client.post(
        f"/snapshots/{snapshot_id}/draft/{section.id}/edit",
        data={"text": "Правка коуча"},
    )

    with context.session() as repo:
        (again, *_) = repo.drafts.sections(snapshot_id)
    assert again.generated == "Текст раздела."
    assert again.edited == "Правка коуча"


# План 4, задача 4: якоря возврата — правка раздела ведёт назад к этому
# разделу, а не к верху черновика.


def test_edit_section_redirects_back_to_the_section_anchor(client):
    test_client, context, _ = client
    snapshot_id = _snapshot_with_a_finding(test_client, context)
    test_client.post(f"/snapshots/{snapshot_id}/request", data={"raw": "Устал"})
    test_client.post(
        f"/snapshots/{snapshot_id}/request/redact", data={"redacted": "Устал"}
    )
    test_client.post(f"/snapshots/{snapshot_id}/request/approve")
    test_client.post(f"/snapshots/{snapshot_id}/draft")

    with context.session() as repo:
        section = repo.drafts.sections(snapshot_id)[0]
    response = test_client.post(
        f"/snapshots/{snapshot_id}/draft/{section.id}/edit",
        data={"text": "Правка коуча"},
        follow_redirects=False,
    )

    assert response.status_code == 303
    assert response.headers["location"] == (
        f"/snapshots/{snapshot_id}/draft#s{section.id}"
    )


def test_section_block_has_an_anchor_id(client):
    test_client, context, _ = client
    snapshot_id = _snapshot_with_a_finding(test_client, context)
    _approve_request(test_client, snapshot_id)
    test_client.post(f"/snapshots/{snapshot_id}/draft")

    with context.session() as repo:
        section = repo.drafts.sections(snapshot_id)[0]
    page = test_client.get(f"/snapshots/{snapshot_id}/draft").text
    assert f'id="s{section.id}"' in page


def test_editing_after_approval_is_refused(client):
    test_client, context, _ = client
    snapshot_id = _snapshot_with_a_finding(test_client, context)
    test_client.post(f"/snapshots/{snapshot_id}/request", data={"raw": "Устал"})
    test_client.post(
        f"/snapshots/{snapshot_id}/request/redact", data={"redacted": "Устал"}
    )
    test_client.post(f"/snapshots/{snapshot_id}/request/approve")
    test_client.post(f"/snapshots/{snapshot_id}/draft")
    test_client.post(f"/snapshots/{snapshot_id}/draft/approve")

    with context.session() as repo:
        section = repo.drafts.sections(snapshot_id)[0]
    response = test_client.post(
        f"/snapshots/{snapshot_id}/draft/{section.id}/edit",
        data={"text": "Поздняя правка"},
        follow_redirects=False,
    )

    assert response.status_code == 409


def test_model_failure_is_reported_not_swallowed(client):
    test_client, context, provider = client
    snapshot_id = _snapshot_with_a_finding(test_client, context)
    test_client.post(f"/snapshots/{snapshot_id}/request", data={"raw": "Устал"})
    test_client.post(
        f"/snapshots/{snapshot_id}/request/redact", data={"redacted": "Устал"}
    )
    test_client.post(f"/snapshots/{snapshot_id}/request/approve")
    provider.fail = True

    response = test_client.post(
        f"/snapshots/{snapshot_id}/draft", follow_redirects=False
    )

    assert response.status_code == 502
    assert "недоступна" in response.text
    with context.session() as repo:
        assert repo.drafts.sections(snapshot_id) == []


def test_draft_without_findings_is_refused(client):
    test_client, context, _ = client
    test_client.post("/clients", data=WOMAN)
    test_client.post("/clients/CL-0001/snapshots", data={"taken_on": "2026-09-01"})
    with context.session() as repo:
        snapshot_id = repo.snapshots.for_client("CL-0001")[-1].id
    test_client.post(f"/snapshots/{snapshot_id}/request", data={"raw": "Устал"})
    test_client.post(
        f"/snapshots/{snapshot_id}/request/redact", data={"redacted": "Устал"}
    )
    test_client.post(f"/snapshots/{snapshot_id}/request/approve")

    response = test_client.post(
        f"/snapshots/{snapshot_id}/draft", follow_redirects=False
    )

    assert response.status_code == 400


def test_unknown_snapshot_is_404(client):
    test_client, _, _ = client
    assert test_client.get("/snapshots/999/draft").status_code == 404


def test_approving_a_request_without_proofreading_is_refused(client):
    """Утвердить нечего, пока правая часть (вычитка) не заполнена."""
    test_client, context, _ = client
    snapshot_id = _snapshot_with_a_finding(test_client, context)
    test_client.post(f"/snapshots/{snapshot_id}/request", data={"raw": "Устал"})

    response = test_client.post(
        f"/snapshots/{snapshot_id}/request/approve", follow_redirects=False
    )

    assert response.status_code == 400
    with context.session() as repo:
        stored = repo.requests.get(snapshot_id)
    assert not stored.approved


def test_leak_in_the_approved_request_is_refused_not_sent(client):
    """Сторож проверяет payload целиком, включая текст запроса, а не только
    находки — коуч мог вписать в правую часть то, что не стоило."""
    test_client, context, provider = client
    snapshot_id = _snapshot_with_a_finding(test_client, context)
    test_client.post(f"/snapshots/{snapshot_id}/request", data={"raw": "Устал"})
    test_client.post(
        f"/snapshots/{snapshot_id}/request/redact",
        data={"redacted": "Соловьёва Ирина устала"},
    )
    test_client.post(f"/snapshots/{snapshot_id}/request/approve")

    response = test_client.post(
        f"/snapshots/{snapshot_id}/draft", follow_redirects=False
    )

    assert response.status_code == 400
    assert provider.prompts == []
    with context.session() as repo:
        assert repo.drafts.sections(snapshot_id) == []


def test_editing_an_unknown_section_is_404_not_409(client):
    """404 — раздела нет в этом срезе; 409 — черновик заморожен утверждением.
    Это два разных отказа, и код обязан их различать."""
    test_client, context, _ = client
    snapshot_id = _snapshot_with_a_finding(test_client, context)
    test_client.post(f"/snapshots/{snapshot_id}/request", data={"raw": "Устал"})
    test_client.post(
        f"/snapshots/{snapshot_id}/request/redact", data={"redacted": "Устал"}
    )
    test_client.post(f"/snapshots/{snapshot_id}/request/approve")
    test_client.post(f"/snapshots/{snapshot_id}/draft")

    response = test_client.post(
        f"/snapshots/{snapshot_id}/draft/999999/edit",
        data={"text": "Правка"},
        follow_redirects=False,
    )

    assert response.status_code == 404


def test_rebuilding_an_approved_draft_is_refused_before_calling_the_model(client):
    """Отказ после утверждения не должен стоить ни одного обращения к
    модели — находка не должна быть собрана заново, потом отвергнута."""
    test_client, context, provider = client
    snapshot_id = _snapshot_with_a_finding(test_client, context)
    test_client.post(f"/snapshots/{snapshot_id}/request", data={"raw": "Устал"})
    test_client.post(
        f"/snapshots/{snapshot_id}/request/redact", data={"redacted": "Устал"}
    )
    test_client.post(f"/snapshots/{snapshot_id}/request/approve")
    test_client.post(f"/snapshots/{snapshot_id}/draft")
    test_client.post(f"/snapshots/{snapshot_id}/draft/approve")
    provider.prompts.clear()

    response = test_client.post(
        f"/snapshots/{snapshot_id}/draft", follow_redirects=False
    )

    assert response.status_code == 409
    assert provider.prompts == []


def test_request_is_frozen_once_the_draft_is_approved(client):
    """После утверждения черновика запрос клиента не переписывается: иначе
    рядом с замороженными разделами оказался бы посторонний запрос, а текст,
    реально утверждённый и отправленный модели, был бы стёрт."""
    test_client, context, _ = client
    snapshot_id = _snapshot_with_a_finding(test_client, context)
    test_client.post(f"/snapshots/{snapshot_id}/request", data={"raw": "Устал"})
    test_client.post(
        f"/snapshots/{snapshot_id}/request/redact", data={"redacted": "Устал"}
    )
    test_client.post(f"/snapshots/{snapshot_id}/request/approve")
    test_client.post(f"/snapshots/{snapshot_id}/draft")
    test_client.post(f"/snapshots/{snapshot_id}/draft/approve")

    response = test_client.post(
        f"/snapshots/{snapshot_id}/request",
        data={"raw": "Подменённый текст"},
        follow_redirects=False,
    )

    assert response.status_code == 409
    with context.session() as repo:
        stored = repo.requests.get(snapshot_id)
    assert stored.raw == "Устал"
    assert stored.redacted == "Устал"
    assert stored.approved


def test_request_redaction_is_frozen_once_the_draft_is_approved(client):
    test_client, context, _ = client
    snapshot_id = _snapshot_with_a_finding(test_client, context)
    test_client.post(f"/snapshots/{snapshot_id}/request", data={"raw": "Устал"})
    test_client.post(
        f"/snapshots/{snapshot_id}/request/redact", data={"redacted": "Устал"}
    )
    test_client.post(f"/snapshots/{snapshot_id}/request/approve")
    test_client.post(f"/snapshots/{snapshot_id}/draft")
    test_client.post(f"/snapshots/{snapshot_id}/draft/approve")

    response = test_client.post(
        f"/snapshots/{snapshot_id}/request/redact",
        data={"redacted": "Подменённая вычитка"},
        follow_redirects=False,
    )

    assert response.status_code == 409
    with context.session() as repo:
        stored = repo.requests.get(snapshot_id)
    assert stored.redacted == "Устал"


def test_reapproving_a_frozen_draft_is_refused(client):
    """`DraftRepository.approve` делает upsert: без этой проверки повторное
    утверждение молча сдвинуло бы отметку времени утверждения — это данные
    аудита, а не то, что можно переписать задним числом."""
    test_client, context, _ = client
    snapshot_id = _snapshot_with_a_finding(test_client, context)
    test_client.post(f"/snapshots/{snapshot_id}/request", data={"raw": "Устал"})
    test_client.post(
        f"/snapshots/{snapshot_id}/request/redact", data={"redacted": "Устал"}
    )
    test_client.post(f"/snapshots/{snapshot_id}/request/approve")
    test_client.post(f"/snapshots/{snapshot_id}/draft")
    test_client.post(f"/snapshots/{snapshot_id}/draft/approve")

    with context.session() as repo:
        first_approval = repo.drafts.approved_at(snapshot_id)

    response = test_client.post(
        f"/snapshots/{snapshot_id}/draft/approve", follow_redirects=False
    )

    assert response.status_code == 409
    with context.session() as repo:
        assert repo.drafts.approved_at(snapshot_id) == first_approval


def test_the_rewrite_request_button_is_gone_once_the_draft_is_approved(client):
    """Маршрут отвечает на переписывание запроса 409-м, как только черновик
    утверждён. Кнопка, которая всегда отказывает, — обещание, которого
    экран не держит: форма правки раздела закрыта тем же условием."""
    test_client, context, _ = client
    snapshot_id = _snapshot_with_a_finding(test_client, context)
    test_client.post(f"/snapshots/{snapshot_id}/request", data={"raw": "Устал"})
    test_client.post(
        f"/snapshots/{snapshot_id}/request/redact", data={"redacted": "Устал"}
    )
    test_client.post(f"/snapshots/{snapshot_id}/request/approve")
    test_client.post(f"/snapshots/{snapshot_id}/draft")

    before = test_client.get(f"/snapshots/{snapshot_id}/draft").text
    assert "Переписать запрос" in before

    test_client.post(f"/snapshots/{snapshot_id}/draft/approve")

    after = test_client.get(f"/snapshots/{snapshot_id}/draft").text
    assert "Переписать запрос" not in after
    # И правка раздела тоже — на неё маршрут отвечает тем же 409-м.
    assert "Сохранить правку" not in after


def test_progress_reports_how_many_sections_are_ready(client):
    """Сборка идёт минуты: без этого экран висит без признаков жизни."""
    test_client, context, _ = client
    snapshot_id = _snapshot_with_a_finding(test_client, context)

    empty = test_client.get(f"/snapshots/{snapshot_id}/draft/progress").json()
    assert empty["собрано"] == 0
    assert empty["всего"] == 8

    _approve_request(test_client, snapshot_id)
    test_client.post(f"/snapshots/{snapshot_id}/draft")

    full = test_client.get(f"/snapshots/{snapshot_id}/draft/progress").json()
    assert full["собрано"] == full["всего"]


def test_progress_of_an_unknown_snapshot_is_404(client):
    test_client, _, _ = client
    assert test_client.get("/snapshots/999/draft/progress").status_code == 404


def test_draft_button_locks_itself_on_submit(client):
    """Второе нажатие запустило бы вторую сборку — восемь лишних вызовов."""
    test_client, context, _ = client
    snapshot_id = _snapshot_with_a_finding(test_client, context)
    _approve_request(test_client, snapshot_id)

    page = test_client.get(f"/snapshots/{snapshot_id}/draft").text
    assert "button.disabled = true" in page
    assert "draft/progress" in page
    assert "<progress" in page
    assert 'id="draft-status"' in page


def test_report_is_refused_until_the_draft_is_approved(client):
    """До утверждения отдавать клиенту нечего."""
    test_client, context, _ = client
    snapshot_id = _snapshot_with_a_finding(test_client, context)
    _approve_request(test_client, snapshot_id)
    test_client.post(f"/snapshots/{snapshot_id}/draft")

    response = test_client.get(f"/snapshots/{snapshot_id}/report.pdf")

    assert response.status_code == 409


def test_report_is_a_pdf_attachment_after_approval(client):
    test_client, context, _ = client
    snapshot_id = _snapshot_with_a_finding(test_client, context)
    _approve_request(test_client, snapshot_id)
    test_client.post(f"/snapshots/{snapshot_id}/draft")
    test_client.post(f"/snapshots/{snapshot_id}/draft/approve")

    response = test_client.get(f"/snapshots/{snapshot_id}/report.pdf")

    assert response.status_code == 200
    assert response.headers["content-type"] == "application/pdf"
    assert "attachment" in response.headers.get("content-disposition", "")
    assert response.content[:5] == b"%PDF-"


def test_report_of_an_unknown_snapshot_is_404(client):
    test_client, _, _ = client
    assert test_client.get("/snapshots/999/report.pdf").status_code == 404


def test_download_button_appears_only_after_approval(client):
    test_client, context, _ = client
    snapshot_id = _snapshot_with_a_finding(test_client, context)
    _approve_request(test_client, snapshot_id)
    test_client.post(f"/snapshots/{snapshot_id}/draft")

    before = test_client.get(f"/snapshots/{snapshot_id}/draft").text
    assert "report.pdf" not in before

    test_client.post(f"/snapshots/{snapshot_id}/draft/approve")

    after = test_client.get(f"/snapshots/{snapshot_id}/draft").text
    assert "report.pdf" in after


def test_report_is_503_when_the_print_engine_is_unavailable(client, monkeypatch):
    """PdfBuildError должен доходить до коуча как 503 с указанием, что
    поставить, а не как голая 500-ка."""
    import healthcoach.app.routes_report as routes_report
    from healthcoach.report.pdf import PdfBuildError

    test_client, context, _ = client
    snapshot_id = _snapshot_with_a_finding(test_client, context)
    _approve_request(test_client, snapshot_id)
    test_client.post(f"/snapshots/{snapshot_id}/draft")
    test_client.post(f"/snapshots/{snapshot_id}/draft/approve")

    def _broken(html: str) -> bytes:
        raise PdfBuildError(
            "движок печати недоступен: нет pango. Нужен pango: brew install pango"
        )

    monkeypatch.setattr(routes_report, "report_pdf", _broken)

    response = test_client.get(f"/snapshots/{snapshot_id}/report.pdf")

    assert response.status_code == 503
    assert "pango" in response.text


# План 4, задача 4: отчёт по набору срезов.


def test_report_pdf_is_built_for_a_scope_of_two_snapshots(client):
    """Утверждённый отчёт по набору из двух срезов собирается в PDF."""
    test_client, context, _ = client
    snapshot_id = _snapshot_with_a_finding(test_client, context)

    test_client.post("/clients/CL-0001/snapshots", data={"taken_on": "2026-03-01"})
    with context.session() as repo:
        older = next(
            s for s in repo.snapshots.for_client("CL-0001") if s.id != snapshot_id
        )
    test_client.post(
        f"/snapshots/{older.id}/measurements",
        data={
            "raw_name": "Витамин Д", "value": "30", "units": "нг/мл",
            "taken_on": "2026-02-20",
        },
    )
    with context.session() as repo:
        (stored,) = repo.snapshots.measurements(older.id)
    test_client.post(f"/snapshots/{older.id}/measurements/{stored.id}/confirm")
    with context.session() as repo:
        repo.scopes.set_members(snapshot_id, [older.id, snapshot_id])

    _approve_request(test_client, snapshot_id)
    test_client.post(f"/snapshots/{snapshot_id}/draft")
    test_client.post(f"/snapshots/{snapshot_id}/draft/approve")

    response = test_client.get(f"/snapshots/{snapshot_id}/report.pdf")

    assert response.status_code == 200
    assert response.content[:5] == b"%PDF-"


# План, задача 6: набор срезов виден коучу на экране черновика.


def test_draft_page_lists_the_dates_of_every_snapshot_in_scope(client):
    test_client, context, _ = client
    snapshot_id = _snapshot_with_a_finding(test_client, context)

    test_client.post("/clients/CL-0001/snapshots", data={"taken_on": "2026-03-01"})
    with context.session() as repo:
        older = next(
            s for s in repo.snapshots.for_client("CL-0001") if s.id != snapshot_id
        )
        repo.scopes.set_members(snapshot_id, [older.id, snapshot_id])

    page = test_client.get(f"/snapshots/{snapshot_id}/draft").text

    assert f"/snapshots/{older.id}" in page
    assert "2026-03-01" in page


def test_draft_page_has_no_scope_block_for_a_single_snapshot(client):
    """Хард-требование: срез без сохранённого набора выглядит ровно как
    сегодня — блока с перечислением дат нет вовсе."""
    test_client, context, _ = client
    snapshot_id = _snapshot_with_a_finding(test_client, context)

    page = test_client.get(f"/snapshots/{snapshot_id}/draft").text

    assert "Отчёт собран по срезам" not in page


def test_report_of_a_client_with_an_incomplete_card_is_400_not_409(client):
    """Незаполненная карточка (только у строк со схемы версии 1) — это
    некорректный запрос про клиента, а не конфликт с состоянием черновика.
    Тот же 400, что и при сборке черновика (build_draft/_findings), чтобы
    409 этого маршрута надёжно значило одно: черновик не утверждён."""
    import sqlite3

    test_client, context, _ = client
    snapshot_id = _snapshot_with_a_finding(test_client, context)
    _approve_request(test_client, snapshot_id)
    test_client.post(f"/snapshots/{snapshot_id}/draft")
    test_client.post(f"/snapshots/{snapshot_id}/draft/approve")

    with sqlite3.connect(context.database_path) as connection:
        connection.execute(
            "UPDATE identities SET sex = '', birth_date = '' WHERE code = 'CL-0001'"
        )

    response = test_client.get(f"/snapshots/{snapshot_id}/report.pdf")

    assert response.status_code == 400
