from datetime import date, datetime

import pytest

from healthcoach.storage.clients import ClientRepository
from healthcoach.storage.db import open_database
from healthcoach.storage.drafts import DraftRepository
from healthcoach.storage.snapshots import SnapshotRepository


@pytest.fixture
def repositories(tmp_path):
    connection = open_database(tmp_path / "db.sqlite")
    client = ClientRepository(connection).add("Иванова Мария", "ж", date(1990, 5, 17))
    snapshots = SnapshotRepository(connection)
    snapshot = snapshots.create(client.code, date(2026, 9, 1))
    yield snapshot, snapshots, DraftRepository(connection)
    connection.close()


def test_section_is_saved_with_the_findings_it_stands_on(repositories):
    snapshot, _, drafts = repositories
    saved = drafts.save_section(
        snapshot.id, "показатели", "Ферритин снижен.", ("показатель/ферритин",)
    )

    (read_back,) = drafts.sections(snapshot.id)
    assert read_back.id == saved.id
    assert read_back.section_id == "показатели"
    assert read_back.generated == "Ферритин снижен."
    assert read_back.edited == ""
    assert read_back.finding_ids == ("показатель/ферритин",)


def test_editing_keeps_what_the_model_wrote(repositories):
    """Иначе не сравнить правку с исходным и не переспросить."""
    snapshot, _, drafts = repositories
    saved = drafts.save_section(snapshot.id, "показатели", "Ферритин снижен.", ())

    assert drafts.edit_section(saved.id, snapshot.id, "Ферритин заметно снижен.") is True

    (read_back,) = drafts.sections(snapshot.id)
    assert read_back.generated == "Ферритин снижен."
    assert read_back.edited == "Ферритин заметно снижен."


def test_editing_a_section_of_another_snapshot_is_refused(repositories):
    snapshot, snapshots, drafts = repositories
    other = snapshots.create(snapshot.client_code, date(2026, 10, 1))
    saved = drafts.save_section(other.id, "показатели", "Текст", ())

    assert drafts.edit_section(saved.id, snapshot.id, "Подмена") is False
    (untouched,) = drafts.sections(other.id)
    assert untouched.edited == ""


def test_regenerating_a_section_replaces_it_and_drops_the_edit(repositories):
    snapshot, _, drafts = repositories
    saved = drafts.save_section(snapshot.id, "показатели", "Первый вариант", ())
    drafts.edit_section(saved.id, snapshot.id, "Правка коуча")

    drafts.save_section(snapshot.id, "показатели", "Второй вариант", ())

    (read_back,) = drafts.sections(snapshot.id)
    assert read_back.generated == "Второй вариант"
    assert read_back.edited == ""


def test_approval_records_when(repositories):
    snapshot, _, drafts = repositories
    drafts.save_section(snapshot.id, "показатели", "Текст", ())
    when = datetime(2026, 9, 2, 10, 30)

    assert drafts.approve(snapshot.id, when) is True
    assert drafts.approved_at(snapshot.id) == when


def test_approving_an_empty_draft_is_refused(repositories):
    snapshot, _, drafts = repositories
    assert drafts.approve(snapshot.id, datetime(2026, 9, 2)) is False
    assert drafts.approved_at(snapshot.id) is None


def test_saving_a_section_after_approval_is_refused(repositories):
    """Утверждённый отчёт заморожен — иначе клиент получит не то, что утвердили."""
    snapshot, _, drafts = repositories
    drafts.save_section(snapshot.id, "показатели", "Текст", ())
    drafts.approve(snapshot.id, datetime(2026, 9, 2))

    with pytest.raises(ValueError, match="утвержд"):
        drafts.save_section(snapshot.id, "показатели", "Другой текст", ())


def test_editing_a_section_after_approval_is_refused(repositories):
    """Утверждённый отчёт заморожен целиком: правка не должна тайком менять
    то, что клиент получит после того, как коуч уже всё утвердил."""
    snapshot, _, drafts = repositories
    saved = drafts.save_section(snapshot.id, "показатели", "Текст", ())
    drafts.approve(snapshot.id, datetime(2026, 9, 2))

    with pytest.raises(ValueError, match="утвержд"):
        drafts.edit_section(saved.id, snapshot.id, "Правка после утверждения")

    (read_back,) = drafts.sections(snapshot.id)
    assert read_back.edited == ""
