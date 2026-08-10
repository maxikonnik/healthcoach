from datetime import date

import pytest

from healthcoach.privacy.redact import redact
from healthcoach.storage.clients import Client

CLIENT = Client(
    code="CL-0001",
    full_name="Соловьёва Ирина Анатольевна",
    sex="ж",
    birth_date=date(1985, 3, 24),
    contacts="@solovyova, +7 916 123-45-67",
    note=None,
)


def test_full_name_is_removed_in_any_order():
    text = "Пациент: СОЛОВЬЁВА Ирина Анатольевна. Ирина жалуется на усталость."
    result = redact(text, CLIENT)
    assert "СОЛОВЬЁВА" not in result.text
    assert "Ирина" not in result.text
    assert "Анатольевна" not in result.text


def test_surname_is_removed_in_other_cases():
    """В бланках и в речи фамилия склоняется."""
    result = redact("Направлена Соловьёвой на анализ", CLIENT)
    assert "Соловьё" not in result.text


def test_birth_date_is_removed_in_several_notations():
    text = "Дата рождения: 24.03.1985, она же 1985-03-24 и 24/03/1985"
    result = redact(text, CLIENT)
    assert "24.03.1985" not in result.text
    assert "1985-03-24" not in result.text
    assert "24/03/1985" not in result.text


def test_contacts_and_client_code_are_removed():
    result = redact("Связь: @solovyova, +7 916 123-45-67, код CL-0001", CLIENT)
    assert "@solovyova" not in result.text
    assert "916" not in result.text
    assert "CL-0001" not in result.text


def test_removed_items_are_listed_for_the_coach():
    """Коуч должен видеть, что именно убрано, а не только результат."""
    result = redact("СОЛОВЬЁВА Ирина, 24.03.1985", CLIENT)
    assert result.removed


def test_text_without_identifying_data_is_untouched():
    text = "Хочу разобраться с усталостью и наладить сон."
    assert redact(text, CLIENT).text == text
    assert redact(text, CLIENT).removed == ()


def test_short_name_parts_do_not_eat_ordinary_words():
    """Фамилия из трёх букв не должна вычищать половину текста."""
    short = Client(
        code="CL-0002",
        full_name="Ли Ан Бо",
        sex="м",
        birth_date=date(1990, 1, 1),
        contacts=None,
        note=None,
    )
    text = "Клиент хочет наладить сон и питание"
    assert redact(text, short).text == text
