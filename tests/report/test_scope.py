from datetime import date

import pytest

from healthcoach.report.scope import build_subject_at, collect_inputs, to_measurements
from healthcoach.storage.clients import ClientRepository
from healthcoach.storage.db import open_database
from healthcoach.storage.scopes import ReportScopeRepository
from healthcoach.storage.snapshots import SnapshotRepository


class Repos:
    """Срезы и набор на одном соединении — как их выдаёт Context.session()."""

    def __init__(self, connection):
        self.clients = ClientRepository(connection)
        self.snapshots = SnapshotRepository(connection)
        self.scopes = ReportScopeRepository(connection)


@pytest.fixture
def repo(tmp_path):
    connection = open_database(tmp_path / "db.sqlite")
    yield Repos(connection)
    connection.close()


def _client(repo):
    return repo.clients.add("Соловьёва Ирина", "ж", date(1985, 3, 24))


def test_single_snapshot_scope_matches_todays_behaviour(repo):
    """Срез без сохранённого набора — набор из себя одного (правило 7)."""
    client = _client(repo)
    snapshot = repo.snapshots.create(client.code, date(2026, 9, 1))
    confirmed = repo.snapshots.add_measurement(
        snapshot.id, "ферритин", "Ферритин", 18.0, "18", "нг/мл", date(2026, 8, 20)
    )
    repo.snapshots.add_measurement(
        snapshot.id, "калий", "Калий", 4.2, "4.2", "ммоль/л", date(2026, 8, 20)
    )
    repo.snapshots.confirm_measurement(confirmed.id, snapshot.id)

    result = collect_inputs(repo, snapshot)

    assert [m.id for m in result.measurements] == [confirmed.id]
    assert result.member_ids == (snapshot.id,)
    assert result.dates == (date(2026, 8, 20),)


def test_indicator_in_two_snapshots_keeps_the_newer_value(repo):
    """Свёртка по показателю: выживает более свежее сверенное значение (правило 1)."""
    client = _client(repo)
    old = repo.snapshots.create(client.code, date(2026, 1, 1))
    new = repo.snapshots.create(client.code, date(2026, 9, 1))
    old_m = repo.snapshots.add_measurement(
        old.id, "ферритин", "Ферритин", 18.0, "18", "нг/мл", date(2026, 1, 1)
    )
    new_m = repo.snapshots.add_measurement(
        new.id, "ферритин", "Ферритин", 45.0, "45", "нг/мл", date(2026, 8, 25)
    )
    repo.snapshots.confirm_measurement(old_m.id, old.id)
    repo.snapshots.confirm_measurement(new_m.id, new.id)
    repo.scopes.set_members(new.id, [old.id, new.id])

    result = collect_inputs(repo, new)

    assert [m.id for m in result.measurements] == [new_m.id]
    assert [m.value for m in result.measurements] == [45.0]


def test_indicator_only_in_the_older_snapshot_is_included(repo):
    """Показатель, сданный лишь в старом срезе, всё равно попадает в свод."""
    client = _client(repo)
    old = repo.snapshots.create(client.code, date(2026, 1, 1))
    new = repo.snapshots.create(client.code, date(2026, 9, 1))
    old_m = repo.snapshots.add_measurement(
        old.id, "витамин-д", "Витамин Д", 30.0, "30", "нг/мл", date(2026, 1, 1)
    )
    repo.snapshots.confirm_measurement(old_m.id, old.id)
    repo.scopes.set_members(new.id, [old.id, new.id])

    result = collect_inputs(repo, new)

    assert [m.id for m in result.measurements] == [old_m.id]


def test_unconfirmed_measurements_are_never_included(repo):
    """Ворота сверки держатся и здесь, независимо от того, в каком срезе набора."""
    client = _client(repo)
    old = repo.snapshots.create(client.code, date(2026, 1, 1))
    new = repo.snapshots.create(client.code, date(2026, 9, 1))
    repo.snapshots.add_measurement(
        old.id, "ферритин", "Ферритин", 18.0, "18", "нг/мл", date(2026, 1, 1)
    )
    repo.snapshots.add_measurement(
        new.id, "ферритин", "Ферритин", 45.0, "45", "нг/мл", date(2026, 8, 25)
    )
    repo.scopes.set_members(new.id, [old.id, new.id])

    result = collect_inputs(repo, new)

    assert result.measurements == ()


def test_same_date_tie_break_is_won_by_the_larger_id(repo):
    """Ключ сравнения — (taken_on, id) самого измерения, а не среза (правило 1)."""
    client = _client(repo)
    snapshot = repo.snapshots.create(client.code, date(2026, 9, 1))
    first = repo.snapshots.add_measurement(
        snapshot.id, "ферритин", "Ферритин", 18.0, "18", "нг/мл", date(2026, 8, 20)
    )
    second = repo.snapshots.add_measurement(
        snapshot.id, "ферритин", "Ферритин", 20.0, "20", "нг/мл", date(2026, 8, 20)
    )
    repo.snapshots.confirm_measurement(first.id, snapshot.id)
    repo.snapshots.confirm_measurement(second.id, snapshot.id)
    assert second.id > first.id

    result = collect_inputs(repo, snapshot)

    assert [m.id for m in result.measurements] == [second.id]


def test_unrecognised_rows_are_never_collapsed_together(repo):
    """Показатели без analyte_id идут по одному на строку (правило 2)."""
    client = _client(repo)
    snapshot = repo.snapshots.create(client.code, date(2026, 9, 1))
    first = repo.snapshots.add_measurement(
        snapshot.id, "", "Гомоцистеин", 12.0, "12", "мкмоль/л", date(2026, 8, 20)
    )
    second = repo.snapshots.add_measurement(
        snapshot.id, "", "Инсулин", 8.0, "8", "мкЕд/мл", date(2026, 8, 20)
    )
    repo.snapshots.confirm_measurement(first.id, snapshot.id)
    repo.snapshots.confirm_measurement(second.id, snapshot.id)

    result = collect_inputs(repo, snapshot)

    assert {m.id for m in result.measurements} == {first.id, second.id}


def test_answers_come_from_the_freshest_snapshot_that_has_them(repo):
    """Анкета не объединяется — берётся анкета самого свежего заполненного среза (правило 3)."""
    client = _client(repo)
    old = repo.snapshots.create(client.code, date(2026, 1, 1))
    new = repo.snapshots.create(client.code, date(2026, 9, 1))
    repo.snapshots.save_answers(old.id, {"q1": 2})
    repo.scopes.set_members(new.id, [old.id, new.id])

    result = collect_inputs(repo, new)

    assert result.answers == {"q1": 2}
    assert result.answers_from == old.id


def test_answers_prefer_the_freshest_snapshot_when_several_have_them(repo):
    """Свёртки анкеты нет: побеждает целиком анкета более свежего среза."""
    client = _client(repo)
    old = repo.snapshots.create(client.code, date(2026, 1, 1))
    new = repo.snapshots.create(client.code, date(2026, 9, 1))
    repo.snapshots.save_answers(old.id, {"q1": 2})
    repo.snapshots.save_answers(new.id, {"q1": 4})
    repo.scopes.set_members(new.id, [old.id, new.id])

    result = collect_inputs(repo, new)

    assert result.answers == {"q1": 4}
    assert result.answers_from == new.id


def test_answers_from_is_none_when_no_snapshot_has_answers(repo):
    client = _client(repo)
    old = repo.snapshots.create(client.code, date(2026, 1, 1))
    new = repo.snapshots.create(client.code, date(2026, 9, 1))
    repo.scopes.set_members(new.id, [old.id, new.id])

    result = collect_inputs(repo, new)

    assert result.answers == {}
    assert result.answers_from is None


def test_dates_are_deduplicated_and_sorted(repo):
    client = _client(repo)
    old = repo.snapshots.create(client.code, date(2026, 1, 1))
    new = repo.snapshots.create(client.code, date(2026, 9, 1))
    m1 = repo.snapshots.add_measurement(
        old.id, "ферритин", "Ферритин", 18.0, "18", "нг/мл", date(2026, 1, 5)
    )
    m2 = repo.snapshots.add_measurement(
        new.id, "калий", "Калий", 4.2, "4.2", "ммоль/л", date(2026, 8, 25)
    )
    m3 = repo.snapshots.add_measurement(
        new.id, "натрий", "Натрий", 140.0, "140", "ммоль/л", date(2026, 8, 25)
    )
    for m, s in ((m1, old), (m2, new), (m3, new)):
        repo.snapshots.confirm_measurement(m.id, s.id)
    repo.scopes.set_members(new.id, [old.id, new.id])

    result = collect_inputs(repo, new)

    assert result.dates == (date(2026, 1, 5), date(2026, 8, 25))


def test_member_ids_cover_the_whole_scope_in_date_order(repo):
    client = _client(repo)
    old = repo.snapshots.create(client.code, date(2026, 1, 1))
    new = repo.snapshots.create(client.code, date(2026, 9, 1))
    repo.scopes.set_members(new.id, [new.id, old.id])

    result = collect_inputs(repo, new)

    assert result.member_ids == (old.id, new.id)


def test_two_draws_in_one_snapshot_both_survive(repo):
    """Ревью: свёртка не должна применяться внутри одного среза (правило 1
    говорит «среди выбранных срезов») — два бланка одного показателя,
    сданные в один визит с разными датами забора, не «повторный ввод
    того же среза», а нормальная запись, и обе должны попасть в находки."""
    client = _client(repo)
    snapshot = repo.snapshots.create(client.code, date(2026, 9, 1))
    first = repo.snapshots.add_measurement(
        snapshot.id, "ферритин", "Ферритин", 18.0, "18", "нг/мл", date(2026, 8, 20)
    )
    second = repo.snapshots.add_measurement(
        snapshot.id, "ферритин", "Ферритин", 42.0, "42", "нг/мл", date(2026, 8, 28)
    )
    repo.snapshots.confirm_measurement(first.id, snapshot.id)
    repo.snapshots.confirm_measurement(second.id, snapshot.id)

    result = collect_inputs(repo, snapshot)

    assert {m.id for m in result.measurements} == {first.id, second.id}
    assert {m.value for m in result.measurements} == {18.0, 42.0}


def test_within_snapshot_survival_and_cross_snapshot_collapse_combine(repo):
    """Смешанный случай: новый срез несёт два бланка одного показателя (обе
    даты забора внутри него выживают), а старый срез с тем же показателем
    полностью проигрывает — его значение уже видно в динамике."""
    client = _client(repo)
    old = repo.snapshots.create(client.code, date(2026, 1, 1))
    new = repo.snapshots.create(client.code, date(2026, 9, 1))
    old_m = repo.snapshots.add_measurement(
        old.id, "ферритин", "Ферритин", 9.0, "9", "нг/мл", date(2026, 1, 1)
    )
    new_first = repo.snapshots.add_measurement(
        new.id, "ферритин", "Ферритин", 18.0, "18", "нг/мл", date(2026, 8, 20)
    )
    new_second = repo.snapshots.add_measurement(
        new.id, "ферритин", "Ферритин", 42.0, "42", "нг/мл", date(2026, 8, 28)
    )
    repo.snapshots.confirm_measurement(old_m.id, old.id)
    repo.snapshots.confirm_measurement(new_first.id, new.id)
    repo.snapshots.confirm_measurement(new_second.id, new.id)
    repo.scopes.set_members(new.id, [old.id, new.id])

    result = collect_inputs(repo, new)

    assert {m.id for m in result.measurements} == {new_first.id, new_second.id}


def test_surviving_measurements_carry_their_own_snapshot_id(repo):
    """Задачам 3 и 4 нужен snapshot_id каждого выжившего измерения."""
    client = _client(repo)
    old = repo.snapshots.create(client.code, date(2026, 1, 1))
    new = repo.snapshots.create(client.code, date(2026, 9, 1))
    old_m = repo.snapshots.add_measurement(
        old.id, "витамин-д", "Витамин Д", 30.0, "30", "нг/мл", date(2026, 1, 1)
    )
    repo.snapshots.confirm_measurement(old_m.id, old.id)
    repo.scopes.set_members(new.id, [old.id, new.id])

    result = collect_inputs(repo, new)

    (survivor,) = result.measurements
    assert survivor.snapshot_id == old.id


def test_to_measurements_carries_snapshot_id(repo):
    """Ревью: три копии этой проекции могли разойтись на snapshot_id — без
    него compute_derived тихо перестаёт различать срезы операндов
    (правило 5). Общий сайт обязан нести snapshot_id всегда."""
    client = _client(repo)
    snapshot = repo.snapshots.create(client.code, date(2026, 9, 1))
    stored = repo.snapshots.add_measurement(
        snapshot.id, "ферритин", "Ферритин", 18.0, "18", "нг/мл", date(2026, 8, 20)
    )

    (measurement,) = to_measurements([stored])

    assert measurement.snapshot_id == snapshot.id
    assert measurement.taken_on == date(2026, 8, 20)
    assert measurement.analyte_id == "ферритин"
    assert measurement.value == 18.0


def test_build_subject_at_uses_clients_age_on_the_given_date(repo):
    """Ревью: три копии `subject_at` строили один и тот же коллбэк — общий
    сайт исключает расхождение."""
    client = repo.clients.add("Петров Пётр", "м", date(1985, 3, 2))

    subject = build_subject_at(client)(date(2026, 9, 1))

    assert subject.sex == "м"
    assert subject.age == client.age_on(date(2026, 9, 1))
