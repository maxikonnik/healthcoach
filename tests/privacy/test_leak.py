from datetime import date

import pytest

from healthcoach.privacy.leak import LeakError, assert_no_leak
from healthcoach.storage.clients import Client

CLIENT = Client(
    code="CL-0001",
    full_name="Соловьёва Ирина Анатольевна",
    sex="ж",
    birth_date=date(1985, 3, 24),
    contacts="@solovyova",
    note=None,
)


def test_clean_payload_passes():
    assert_no_leak("Женщина 39 лет. Ферритин 18 нг/мл — дефицит.", CLIENT)


def test_surname_is_refused():
    with pytest.raises(LeakError, match="Соловьё"):
        assert_no_leak("Соловьёва жалуется на усталость", CLIENT)


def test_surname_in_another_case_is_refused():
    with pytest.raises(LeakError):
        assert_no_leak("Направлена Соловьёвой к эндокринологу", CLIENT)


def test_birth_date_is_refused():
    with pytest.raises(LeakError, match="24.03.1985"):
        assert_no_leak("Дата рождения 24.03.1985", CLIENT)


def test_client_code_is_refused():
    with pytest.raises(LeakError, match="CL-0001"):
        assert_no_leak("Срез клиента CL-0001", CLIENT)


def test_contacts_are_refused():
    with pytest.raises(LeakError, match="solovyova"):
        assert_no_leak("Написать на @solovyova", CLIENT)


def test_error_names_what_was_found_not_just_that_something_was():
    """Коуч должен понять, что чинить, а не только что отправка не пошла."""
    with pytest.raises(LeakError) as excinfo:
        assert_no_leak("Соловьёва, 24.03.1985", CLIENT)
    message = str(excinfo.value)
    assert "Соловьё" in message
    assert "24.03.1985" in message


def test_guard_errs_towards_refusing_and_says_so():
    """Основа фамилии может совпасть с обычным словом — и это выбор.

    У клиента по фамилии Белкин основа — «Белк», и она находится внутри
    слова «белки», поэтому сторож отвергнет текст про белки крови. Это
    неудобно, но безопасно:
    сообщение называет найденное, и коуч понимает, что произошло.
    Обратная ошибка — выпустить фамилию наружу — неисправима.
    """
    belkin = Client(
        code="CL-0003",
        full_name="Белкин Иван Петрович",
        sex="м",
        birth_date=date(1980, 1, 1),
        contacts=None,
        note=None,
    )
    with pytest.raises(LeakError) as excinfo:
        assert_no_leak("Общий белки крови в норме", belkin)
    assert "Белк" in str(excinfo.value)


def test_guard_has_no_way_to_be_switched_off():
    """Проверка обязательна и не подлежит смягчению.

    Если у сторожа появится параметр, отключающий проверку, кто-нибудь
    им однажды воспользуется «на время отладки».
    """
    import inspect

    signature = inspect.signature(assert_no_leak)
    assert list(signature.parameters) == ["payload", "client"]
