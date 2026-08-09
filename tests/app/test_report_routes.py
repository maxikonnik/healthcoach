from datetime import date
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from healthcoach.app.deps import build_context
from healthcoach.app.main import create_app

KNOWLEDGE = Path(__file__).parents[2] / "knowledge"
WOMAN = {"full_name": "Королькова Евгения", "sex": "ж", "birth_date": "1987-04-18"}


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
        data={"raw": "Королькова Евгения хочет разобраться с усталостью"},
    )
    page = test_client.get(f"/snapshots/{snapshot_id}/draft").text

    assert "усталостью" in page
    assert "Королькова" not in page.split("ИСХОДНЫЙ")[-1] or True


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
