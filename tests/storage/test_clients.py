import pytest

from healthcoach.storage.clients import ClientRepository
from healthcoach.storage.db import open_database


@pytest.fixture
def repository(tmp_path):
    with open_database(tmp_path / "db.sqlite") as connection:
        yield ClientRepository(connection)


def test_adds_client_with_generated_code(repository):
    client = repository.add("Иванова Мария Петровна", contacts="@masha")
    assert client.code == "CL-0001"
    assert client.full_name == "Иванова Мария Петровна"
    assert client.contacts == "@masha"


def test_codes_increment(repository):
    first = repository.add("Первая")
    second = repository.add("Вторая")
    assert (first.code, second.code) == ("CL-0001", "CL-0002")


def test_get_returns_none_for_unknown_code(repository):
    assert repository.get("CL-9999") is None


def test_all_is_sorted_by_code(repository):
    repository.add("Вторая")
    repository.add("Первая")
    assert [c.code for c in repository.all()] == ["CL-0001", "CL-0002"]


def test_full_name_is_required(repository):
    with pytest.raises(ValueError, match="ФИО"):
        repository.add("   ")
