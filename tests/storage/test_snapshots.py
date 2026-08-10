from datetime import date
from pathlib import Path

import pytest

from healthcoach.storage.clients import ClientRepository
from healthcoach.storage.db import open_database
from healthcoach.storage.snapshots import SnapshotRepository


@pytest.fixture
def repositories(tmp_path):
    with open_database(tmp_path / "db.sqlite") as connection:
        clients = ClientRepository(connection)
        client = clients.add("Иванова Мария", "ж", date(1990, 5, 17))
        yield client.code, SnapshotRepository(connection)


def test_creates_and_reads_snapshot(repositories):
    code, snapshots = repositories
    created = snapshots.create(code, date(2026, 9, 1), note="первичный")
    fetched = snapshots.get(created.id)
    assert fetched.client_code == code
    assert fetched.taken_on == date(2026, 9, 1)
    assert fetched.note == "первичный"


def test_snapshots_for_client_are_sorted_by_date(repositories):
    code, snapshots = repositories
    snapshots.create(code, date(2026, 9, 1))
    snapshots.create(code, date(2026, 1, 15))
    assert [s.taken_on for s in snapshots.for_client(code)] == [
        date(2026, 1, 15),
        date(2026, 9, 1),
    ]


def test_measurement_round_trip(repositories):
    code, snapshots = repositories
    snapshot = snapshots.create(code, date(2026, 9, 1))
    stored = snapshots.add_measurement(
        snapshot.id,
        analyte_id="ферритин",
        raw_name="Ферритин (S-Ferritin)",
        value=18.0,
        raw_value="18.0",
        units="нг/мл",
        taken_on=date(2026, 8, 20),
    )
    assert stored.confirmed is False
    (read_back,) = snapshots.measurements(snapshot.id)
    assert read_back.analyte_id == "ферритин"
    assert read_back.value == 18.0
    assert read_back.taken_on == date(2026, 8, 20)


def test_confirming_a_measurement_sticks(repositories):
    code, snapshots = repositories
    snapshot = snapshots.create(code, date(2026, 9, 1))
    stored = snapshots.add_measurement(
        snapshot.id, "ферритин", "Ферритин", 18.0, "18.0", "нг/мл", date(2026, 8, 20)
    )
    assert snapshots.confirm_measurement(stored.id, snapshot.id) is True
    (read_back,) = snapshots.measurements(snapshot.id)
    assert read_back.confirmed is True


def test_confirmation_does_not_reach_another_snapshot(repositories):
    """Иначе подтверждение из одного среза меняло бы данные другого клиента."""
    code, snapshots = repositories
    mine = snapshots.create(code, date(2026, 9, 1))
    other = snapshots.create(code, date(2026, 10, 1))
    stored = snapshots.add_measurement(
        other.id, "ферритин", "Ферритин", 18.0, "18.0", "нг/мл", date(2026, 8, 20)
    )

    assert snapshots.confirm_measurement(stored.id, mine.id) is False
    (untouched,) = snapshots.measurements(other.id)
    assert untouched.confirmed is False


def test_confirming_a_measurement_that_does_not_exist_reports_failure(repositories):
    """Молчаливый успех на несуществующий идентификатор скрывал бы опечатку."""
    code, snapshots = repositories
    snapshot = snapshots.create(code, date(2026, 9, 1))
    assert snapshots.confirm_measurement(99999, snapshot.id) is False


def test_history_spans_snapshots_and_sorts_by_sampling_date(repositories):
    """Динамика строится по дате забора, а не по дате загрузки."""
    code, snapshots = repositories
    later = snapshots.create(code, date(2026, 9, 1))
    earlier = snapshots.create(code, date(2026, 1, 15))
    snapshots.add_measurement(
        later.id, "ферритин", "Ферритин", 45.0, "45.0", "нг/мл", date(2026, 8, 20)
    )
    snapshots.add_measurement(
        earlier.id, "ферритин", "Ферритин", 18.0, "18.0", "нг/мл", date(2026, 1, 10)
    )
    assert [m.value for m in snapshots.history(code, "ферритин")] == [18.0, 45.0]


def test_answers_round_trip(repositories):
    code, snapshots = repositories
    snapshot = snapshots.create(code, date(2026, 9, 1))
    snapshots.save_answers(snapshot.id, {"pitanie.а.1": 2, "pitanie.а.2": 0})
    assert snapshots.answers(snapshot.id) == {"pitanie.а.1": 2, "pitanie.а.2": 0}


def test_saving_answers_replaces_previous(repositories):
    code, snapshots = repositories
    snapshot = snapshots.create(code, date(2026, 9, 1))
    snapshots.save_answers(snapshot.id, {"pitanie.а.1": 2})
    snapshots.save_answers(snapshot.id, {"pitanie.а.1": 3})
    assert snapshots.answers(snapshot.id) == {"pitanie.а.1": 3}


def test_unverified_snapshot_ids_only_include_unconfirmed_measurements(repositories):
    code, snapshots = repositories
    fully_confirmed = snapshots.create(code, date(2026, 1, 1))
    m = snapshots.add_measurement(
        fully_confirmed.id, "натрий", "Натрий", 140.0, "140", "ммоль/л", date(2025, 12, 20)
    )
    snapshots.confirm_measurement(m.id, fully_confirmed.id)
    partly = snapshots.create(code, date(2026, 3, 1))
    a = snapshots.add_measurement(
        partly.id, "ферритин", "Ферритин", 18.0, "18.0", "нг/мл", date(2026, 2, 20)
    )
    snapshots.add_measurement(
        partly.id, "", "Калий", 4.2, "4.2", "ммоль/л", date(2026, 2, 20)
    )
    snapshots.confirm_measurement(a.id, partly.id)
    assert snapshots.unverified_snapshot_ids(code) == [partly.id]


def test_unverified_snapshot_ids_are_scoped_to_the_client(repositories):
    """Иначе долг одного клиента подмешивался бы в счётчик другого."""
    code, snapshots = repositories
    other = ClientRepository(snapshots._connection).add(
        "Петров Олег", "м", date(1980, 1, 1)
    )
    mine = snapshots.create(code, date(2026, 3, 1))
    snapshots.add_measurement(
        mine.id, "ферритин", "Ферритин", 18.0, "18.0", "нг/мл", date(2026, 2, 20)
    )
    theirs = snapshots.create(other.code, date(2026, 3, 1))
    snapshots.add_measurement(
        theirs.id, "ферритин", "Ферритин", 18.0, "18.0", "нг/мл", date(2026, 2, 20)
    )
    assert snapshots.unverified_snapshot_ids(code) == [mine.id]


def _guarded_storage_modules() -> list[Path]:
    """Модули хранилища, которым имя клиента знать не положено.

    Изначально страж проверял только snapshots.py — и когда в documents.py
    завели `from healthcoach.storage.clients import ClientRepository` и метод
    `SELECT full_name FROM identities`, весь набор тестов прошёл молча.
    Поэтому здесь перечисляются файлы каталога, а не один захардкоженный
    путь: новый модуль хранилища подпадает под проверку по факту появления.

    Исключены clients.py — владелец identities/full_name, которому это и
    положено, — и schema.py: она объявляет DDL таблицы identities как
    часть общей схемы для всего приложения, а не читает чужие данные.
    """
    storage_dir = Path("src/healthcoach/storage")
    exempt = {"clients.py", "schema.py"}
    modules = sorted(p for p in storage_dir.glob("*.py") if p.name not in exempt)
    assert modules, "не нашлось модулей хранилища для проверки"
    return modules


@pytest.mark.parametrize("module", _guarded_storage_modules(), ids=lambda p: p.name)
def test_storage_module_never_touches_the_identity_table(module):
    """Реестр ФИО читает только ClientRepository — граница закреплена тестом
    для каждого модуля хранилища, а не только для срезов."""
    source = module.read_text(encoding="utf-8")
    assert "identities" not in source
    assert "full_name" not in source


@pytest.mark.parametrize("module", _guarded_storage_modules(), ids=lambda p: p.name)
def test_storage_module_does_not_delegate_to_the_client_repository(module):
    """Вторая дорога к именам — импорт репозитория клиентов; она тоже закрыта
    для каждого модуля хранилища.

    Проверка по дереву импортов, а не по строкам: делегирование не содержало бы
    ни слова 'identities', ни 'full_name', и текстовый страж его пропустил бы.
    """
    import ast

    source = module.read_text(encoding="utf-8")
    imported: set[str] = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)
        elif isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)

    leaking = {name for name in imported if "storage.clients" in name}
    assert not leaking, f"модуль {module} импортирует {sorted(leaking)}"
