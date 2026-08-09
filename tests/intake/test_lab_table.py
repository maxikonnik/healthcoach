from pathlib import Path

import pytest

from healthcoach.intake.lab_table import (
    LabTableError,
    parse_lab_lines,
    parse_number,
)

FIXTURES = Path(__file__).parent / "fixtures"


def _lines(name: str) -> list[str]:
    return (FIXTURES / f"{name}.txt").read_text(encoding="utf-8").splitlines()


def test_units_before_reference():
    """У СМ-Клиники шапка: Показатель, Результат, Ед. изм., Референсные пределы."""
    table = parse_lab_lines(_lines("smclinic"))
    row = next(r for r in table.rows if "реактивный" in r.name)
    assert row.value_text == "1.2"
    assert row.units == "мг/л"
    assert row.reference_text == "0 - 5"


def test_units_after_reference():
    """У Медицинского Менеджмента единицы стоят последними — читать по шапке."""
    table = parse_lab_lines(_lines("medmenedzhment"))
    row = next(r for r in table.rows if "лейкоцитов" in r.name)
    assert row.value_text == "5.82"
    assert row.units == "10⁹/л"
    assert row.reference_text == "4.50-11.00"


def test_laboratory_code_is_stripped_from_the_name():
    table = parse_lab_lines(_lines("gemotest"))
    row = next(r for r in table.rows if r.name.startswith("Общий белок"))
    assert row.name == "Общий белок"
    assert row.value_text == "76.5"
    assert row.units == "г/л"


def test_non_numeric_value_is_kept_as_text():
    """«<0.60» — ниже порога чувствительности метода, а не 0.60."""
    table = parse_lab_lines(_lines("gemotest"))
    row = next(r for r in table.rows if "реактивный" in r.name)
    assert row.value_text == "<0.50"
    assert parse_number(row.value_text) is None


def test_wrapped_name_is_joined_with_the_next_line():
    table = parse_lab_lines(_lines("medmenedzhment"))
    row = next(r for r in table.rows if r.value_text == "335.00")
    assert row.name == "Средняя концентрация гемоглобина в эритроцитах"
    assert row.units == "г/л"


def test_wrapped_name_reaches_unparsed_together_with_the_failed_value_line():
    """Регресс: имя, перенесённое на отдельную строку, терялось, если
    следующая строка со значением не складывалась в запись бланка — коуч
    видел голое число «341.00 320.00-360.00» без единиц измерения (нет
    роли «единицы» в этой шапке, значит запись невалидна) и без названия
    показателя вовсе. Это ровно форма, которую даёт путь с фотографии.
    """
    lines = [
        "Параметр Результат Референсные значения Ед. изм.",
        "Средняя концентрация гемоглобина в эритроцитах",
        "341.00 320.00-360.00",
    ]
    table = parse_lab_lines(lines)
    assert table.rows == ()
    assert len(table.unparsed) == 1
    assert "Средняя концентрация гемоглобина в эритроцитах" in table.unparsed[0]
    assert "341.00 320.00-360.00" in table.unparsed[0]


def test_line_with_a_broken_laboratory_code_is_reported_not_guessed():
    """Значение внутри незакрытой скобки читается неоднозначно.

    Угадать здесь — значит поставить в анализ живого человека число,
    которого в бланке не было.
    """
    table = parse_lab_lines(_lines("gemotest"))
    assert not any("Гликированный" in r.name for r in table.rows)
    assert any("Гликированный" in line for line in table.unparsed)


def test_lab_code_with_a_qualifying_parenthesis_is_not_stripped_from_the_name():
    """Регресс: lab_table.py держал свою — жадную — копию кода лаборатории и
    съедал вместе с кодом любую следующую скобку, включая квалификатор вроде
    «(ионизированный)». «Кальций A09.05.206 (ионизированный)» превращался бы
    в «Кальций» и находился по имени общего кальция — с другим коридором и
    другими единицами. Теперь код без «Приказ» внутри скобки, за которой
    следует другая скобка, не трогается вовсе — как и в resolve.py, откуда
    правило теперь приходит одной общей регуляркой (см. test_resolve.py:43).
    """
    lines = [
        "Исследование Результат Ед. изм. Референсные значения",
        "Кальций A09.05.206 (ионизированный) 5.2 мг/дл 4.5 - 5.6",
    ]
    table = parse_lab_lines(lines)
    (row,) = table.rows
    assert row.name == "Кальций A09.05.206 (ионизированный)"
    assert row.value_text == "5.2"
    assert row.units == "мг/дл"


def test_service_lines_are_not_taken_for_results():
    table = parse_lab_lines(_lines("gemotest"))
    assert not any("Дата исследования" in r.name for r in table.rows)
    assert not any("Дата исследования" in line for line in table.unparsed)


def test_line_with_a_number_that_did_not_parse_reaches_the_coach():
    """Строка с числом может быть результатом — молча выбросить её нельзя."""
    table = parse_lab_lines(_lines("gemotest"))
    assert any("Нормальный уровень" in line for line in table.unparsed)
    assert not any("Нормальный уровень" in r.name for r in table.rows)


def test_value_column_that_is_not_numeric_is_refused_not_smeared():
    """Регресс-пломба на охранник `_split_row`, который проверяет, что
    колонка значения действительно содержит число.

    Здесь единицы в шапке стоят раньше результата («Ед. изм.» перед
    «Результат»), и без этой проверки строка «Ферритин 45 нг/мл 10 - 120»
    разобралась бы как запись с value_text='нг/мл' и units='45' — значение
    и единицы поменялись бы местами. Строка обязана уйти в unparsed, а не
    осесть записью с перепутанными колонками.
    """
    lines = [
        "Исследование Ед. изм. Результат Нормальные значения",
        "Ферритин 45 нг/мл 10 - 120",
    ]
    table = parse_lab_lines(lines)
    assert table.rows == ()
    assert any("Ферритин 45 нг/мл 10 - 120" in line for line in table.unparsed)


def test_document_without_a_header_is_refused():
    with pytest.raises(LabTableError, match="шапк"):
        parse_lab_lines(["просто текст", "и ещё строка"])


def test_parse_number_accepts_both_decimal_separators():
    """В PDF разделитель — точка, на фотографиях — запятая."""
    assert parse_number("7.93") == 7.93
    assert parse_number("7,93") == 7.93
    assert parse_number("341") == 341.0
    assert parse_number("Смотри текст") is None
    assert parse_number("") is None


def test_parse_number_rejects_non_finite_values():
    """nan/inf молча испортили бы любое дальнейшее сравнение с коридором."""
    assert parse_number("nan") is None
    assert parse_number("inf") is None
    assert parse_number("-inf") is None


def test_header_missing_units_word_due_to_pdf_spacing_is_refused():
    """«Ед.изм.» без пробела — обычный артефакт извлечения текста из PDF.

    Не опознав колонку единиц, разбор не имеет права отдать хвост строки
    референсу: «C-реактивный белок ... 0.7 мг/л 0 - 5» стал бы записью с
    units='' и reference_text='мг/л 0 - 5' — единицы потеряны, а референс
    неверен. Отказ безопаснее угадывания.
    """
    lines = [
        "Показатель Результат Ед.изм. Референсные пределы",
        "C-реактивный белок (СРБ) 0.7 мг/л 0 - 5",
    ]
    with pytest.raises(LabTableError) as exc_info:
        parse_lab_lines(lines)
    message = str(exc_info.value)
    assert "Показатель Результат Ед.изм. Референсные пределы" in message
    assert "единицы" in message


def test_header_with_an_unknown_units_word_is_refused():
    """«Единицы» вместо «Ед. изм.» — тоже не входит в словарь ролей."""
    lines = [
        "Показатель Результат Единицы Референсные пределы",
        "C-реактивный белок (СРБ) 0.7 мг/л 0 - 5",
    ]
    with pytest.raises(LabTableError) as exc_info:
        parse_lab_lines(lines)
    assert "единицы" in str(exc_info.value)


def test_header_with_an_unknown_reference_word_is_refused():
    """«Норма» вместо «Нормальные»/«Референсные» — слово не в словаре."""
    lines = [
        "Показатель Результат Ед. изм. Норма",
        "C-реактивный белок (СРБ) 0.7 мг/л 0 - 5",
    ]
    with pytest.raises(LabTableError) as exc_info:
        parse_lab_lines(lines)
    assert "референс" in str(exc_info.value)


def test_units_last_header_with_a_spaced_reference_range_is_parsed_as_a_range():
    """«117.00 - 155.00» с пробелами вокруг тире, как в smclinic — но здесь
    единицы стоят последними в шапке. Диапазон опознаётся по тире между
    двумя числами и забирает три токена целиком, оставляя единицам
    ровно один — «г/л», а не весь хвост строки.
    """
    lines = [
        "Параметр Результат Референсные значения Ед. изм.",
        "Гемоглобин (Hb) 134.00 117.00 - 155.00 г/л",
    ]
    table = parse_lab_lines(lines)
    row = next(r for r in table.rows if "Гемоглобин" in r.name)
    assert row.value_text == "134.00"
    assert row.reference_text == "117.00 - 155.00"
    assert row.units == "г/л"


def test_photograph_reference_range_with_comma_decimals_and_spaced_dash():
    """Реальная фотография: разделитель — запятая, референс — с пробелами
    вокруг тире. Диапазон опознаётся явно (число, тире, число), а не по
    счёту слов — иначе единицы получили бы «- 9,23 10%/л».
    """
    lines = [
        "Параметр Результат Референсные значения Ед. изм.",
        "Общее количество лейкоцитов (WBC) 7,93 3,89 - 9,23 10%/л",
    ]
    table = parse_lab_lines(lines)
    row = next(r for r in table.rows if "лейкоцитов" in r.name)
    assert row.value_text == "7,93"
    assert row.reference_text == "3,89 - 9,23"
    assert row.units == "10%/л"


def test_non_range_tail_still_refuses_rather_than_smearing_into_units():
    """Если хвост после значения не складывается ни в одну из форм
    диапазона, референс, как и раньше, берёт только один токен — а раз
    единицам в конце достаётся больше одного токена, строка отказывается,
    а не смешивает лишние слова с единицами.
    """
    lines = [
        "Параметр Результат Референсные значения Ед. изм.",
        "Триглицериды 0.98 Смотри текст ммоль/л",
    ]
    table = parse_lab_lines(lines)
    assert not table.rows
    assert any("Смотри текст ммоль/л" in line for line in table.unparsed)


def test_a_line_resembling_a_header_but_carrying_a_digit_is_not_dropped():
    """Цифра исключает строку из кандидатов в шапку — а раз она не шапка,
    её результат не должен пропасть без следа, как раньше, когда шапка
    искалась заново на каждой строке.
    """
    lines = [
        "Показатель Результат Ед. изм. Референсные пределы",
        "Исследование выполнено на анализаторе, результат 2 измерений усреднён",
        "Показатель: Глюкоза Результат: 5.2 ммоль/л 3.9 - 5.9",
    ]
    table = parse_lab_lines(lines)
    seen = [r.line for r in table.rows] + list(table.unparsed)
    assert any("анализаторе" in line for line in seen)
    assert any("Глюкоза" in line for line in seen)
