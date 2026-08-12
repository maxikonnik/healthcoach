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


_CORPUS_SERVICE_HEADER = "Показатель Результат Референсные значения Ед.изм."

_CORPUS_SERVICE_LABEL_LINES = [
    "Страница 1 из 3",
    "Страница 1",
    "Страница 1 из 3 Дата печати: 01.01.2026 12:00:00",
    "№ заказа 100200300",
    "№ заказа 100200300 Фамилия пациента Тестова",
]
"""Метки с данными: за самой меткой стоит число — номер страницы или
заказа, а не показатель. Что напечатано на бланке дальше по строке
(«из 3», дата печати, фамилия), значения не имеет: строка целиком
принадлежит форме. Формы взяты из отчёта табло корпуса образцов, числа
и фамилия — выдуманы."""

_CORPUS_SERVICE_PHRASE_LINES = [
    "ПЕЧАТЬ: 01.01.2026 12:00:00 Страница",
    "Дата рождения: 01.01.1990 Возраст: 36",
    "Дата исследования: 01.01.2026",
    "Штрихкод: 1234567890 Вн.№: L01T0001 Материал: Кровь",
    "Материал: Кровь венозная",
    "Вн.№: L01T0001",
    "Адрес пациента г. Тестоград, ул. Придуманная, д. 5, кв. 10",
    "Адрес: 123456, г. Тестоград, ул. Придуманная, д. 5",
    "Адрес ООО «Лаборатория» г. Тестоград",
    "I триместр: 0.05 - 0.50",
]
"""Полные служебные фразы: не первое слово строки, а вся метка целиком.
Каждая форма встречена в отчёте табло корпуса образцов; содержимое после
метки выдумано."""


@pytest.mark.parametrize("line", _CORPUS_SERVICE_LABEL_LINES)
def test_service_label_followed_by_a_number_does_not_become_a_measurement(line):
    """Ни строкой показателя, ни строкой на экран коуча служебная строка
    быть не должна — иначе табло «нераспознано» вечно пополняется тем, что
    коучу читать незачем."""
    table = parse_lab_lines([_CORPUS_SERVICE_HEADER, line])
    assert table.rows == ()
    assert table.unparsed == ()


@pytest.mark.parametrize("line", _CORPUS_SERVICE_PHRASE_LINES)
def test_service_phrase_at_the_start_of_the_line_does_not_become_a_measurement(line):
    table = parse_lab_lines([_CORPUS_SERVICE_HEADER, line])
    assert table.rows == ()
    assert table.unparsed == ()


_SERVICE_LINES_IN_OTHER_CASE = [
    "СТРАНИЦА 1 ИЗ 3",
    "страница 1 из 3",
    "ДАТА ИССЛЕДОВАНИЯ: 01.01.2026",
    "штрихкод: 1234567890",
]


@pytest.mark.parametrize("line", _SERVICE_LINES_IN_OTHER_CASE)
def test_service_lines_are_filtered_regardless_of_letter_case(line):
    """Регресс: отсев различал регистр, и дефект, ради которого он писался,
    выживал в капсе. «СТРАНИЦА 1 ИЗ 3» — обыкновенный колонтитул — снова
    становилась измерением с именем «СТРАНИЦА» и значением 1.
    """
    table = parse_lab_lines([_CORPUS_SERVICE_HEADER, line])
    assert table.rows == ()
    assert table.unparsed == ()


@pytest.mark.parametrize("heading", ["II триместр", "II ТРИМЕСТР", "III триместр:"])
def test_trimester_heading_without_a_colon_is_filtered_too(heading):
    """Двоеточие в конце заголовка — не обязательная часть бланка. Без
    отсева «II триместр» становится `pending_name` и приклеивается к
    следующей настоящей строке результата — та самая склейка, которую
    пломбирует `test_trimester_header_line_is_filtered_and_does_not_swallow_the_next_row`:
    следующая строка начинается с числа, и заголовок встаёт в имя
    показателя — «II триместр» со значением 0.05.
    """
    lines = [_CORPUS_SERVICE_HEADER, heading, "0.05 - 0.50 мЕд/мл"]
    table = parse_lab_lines(lines)
    assert table.rows == ()
    assert table.unparsed == ("0.05 - 0.50 мЕд/мл",)


_UNITS_BEFORE_REFERENCE_HEADER = "Показатель Результат Ед. изм. Референсные пределы"

_LINES_THAT_ONLY_LOOK_SERVICE = [
    ("Страница белка 5 ед 1 - 10", "Страница белка"),
    ("Адрес белок 5 ед 1 - 10", "Адрес белок"),
    ("Материалы исследования 5 ед 1 - 10", "Материалы исследования"),
]


@pytest.mark.parametrize("line,name", _LINES_THAT_ONLY_LOOK_SERVICE)
def test_a_result_line_starting_with_a_service_word_is_not_dropped(line, name):
    """Регресс: отсев шёл по началу строки, и любая строка, первое слово
    которой похоже на служебное, пропадала целиком — ни записи, ни следа
    в unparsed. `\\b` мешает совпасть внутри слова, но не мешает совпасть
    в начале строки: «Страница белка …» отсеивалась вся, а «Материал» без
    `\\b` съедал ещё и «Материалы исследования …». Настоящий результат,
    исчезнувший из списка коуча, хуже результата, который она наберёт
    руками.
    """
    table = parse_lab_lines([_UNITS_BEFORE_REFERENCE_HEADER, line])
    (row,) = table.rows
    assert row.name == name
    assert row.value_text == "5"
    assert row.units == "ед"
    assert row.reference_text == "1 - 10"


def test_trimester_header_line_is_filtered_and_does_not_swallow_the_next_row():
    """«I триместр:» — заголовок раздела бланка при беременности, а не
    строка показателя: после двоеточия нет значения. Без отсева она стала
    бы `pending_name` и склеилась со следующей настоящей строкой результата
    (см. `_STARTS_WITH_NUMBER` в lab_table.py)."""
    lines = [
        _CORPUS_SERVICE_HEADER,
        "I триместр:",
        "ХГЧ 25000 10000 - 60000 мЕд/мл",
    ]
    table = parse_lab_lines(lines)
    assert len(table.rows) == 1
    assert table.rows[0].name == "ХГЧ"


def test_patient_address_line_is_not_stored_as_a_measurement():
    """Адрес пациента — персональные данные, которым не место среди
    измерений: строка содержит цифру (номер дома), поэтому без отсева она
    стала бы записью с домашним адресом в имени показателя. Мутация:
    убрать «Адрес пациента» из `_SERVICE_PHRASE` — этот тест падает.
    """
    lines = [
        _CORPUS_SERVICE_HEADER,
        "Адрес пациента г. Тестоград, ул. Придуманная, д. 5, кв. 10",
        "Ферритин 45 10 - 120 нг/мл",
    ]
    table = parse_lab_lines(lines)
    assert len(table.rows) == 1
    assert table.rows[0].name == "Ферритин"
    assert not any("Адрес" in r.name for r in table.rows)
    assert not any("Адрес" in line for line in table.unparsed)


def test_service_word_match_is_whole_word_not_a_string_prefix():
    """«Пациент» как префикс проглотил бы и «Пациентка беременна» — реальную
    по форме строку бланка, которая служебной не является (в списке отсева
    есть «Адрес пациента», но нет «Пациент»). Строка с числом обязана дойти
    до коуча в unparsed, а не исчезнуть по совпадению первых букв.
    """
    table = parse_lab_lines(
        [_CORPUS_SERVICE_HEADER, "Пациентка беременна 12 недель"]
    )
    assert table.rows == ()
    assert table.unparsed == ("Пациентка беременна 12 недель",)


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


def test_header_units_word_split_by_a_pdf_missing_space_is_still_recognised():
    """«Ед.изм.» без пробела — обычный артефакт извлечения текста из PDF.

    Токенизация шапки режет по точке так же, как по пробелу: иначе
    «Ед.изм.» становится одним нераспознанным словом «ед.изм», и шапка
    отвергается только из-за того, как легли пробелы при извлечении, а не
    потому что колонка правда не опознана.
    """
    lines = [
        "Показатель Результат Ед.изм. Референсные пределы",
        "C-реактивный белок (СРБ) 0.7 мг/л 0 - 5",
    ]
    table = parse_lab_lines(lines)
    row = table.rows[0]
    assert row.value_text == "0.7"
    assert row.units == "мг/л"
    assert row.reference_text == "0 - 5"


@pytest.mark.parametrize("units_spelling", ["Ед.изм.", "Ед. изм.", "Ед изм"])
def test_header_units_word_recognised_regardless_of_spacing(units_spelling):
    """«Ед.изм.», «Ед. изм.» и «Ед изм» — один и тот же смысл, встреченный
    с разной расстановкой пробелов; шапка не должна зависеть от того, как
    легли пробелы при извлечении текста."""
    lines = [
        f"Показатель Результат Референсные значения {units_spelling}",
        "Ферритин 45 10 - 120 нг/мл",
    ]
    table = parse_lab_lines(lines)
    row = table.rows[0]
    assert row.units == "нг/мл"


def test_header_word_edinitsy_is_recognised_as_units():
    """Раньше «Единицы» не входило в словарь ролей — шапка «Исследование
    Результат Единицы Референсные Комментарий» отвергалась целиком, хотя
    ровно это слово стоит в десяти из четырнадцати отказов по корпусу
    образцов."""
    lines = [
        "Показатель Результат Единицы Референсные пределы",
        "C-реактивный белок (СРБ) 0.7 мг/л 0 - 5",
    ]
    table = parse_lab_lines(lines)
    row = table.rows[0]
    assert row.value_text == "0.7"
    assert row.units == "мг/л"
    assert row.reference_text == "0 - 5"


def test_header_with_an_unknown_reference_word_is_refused():
    """«Норма» вместо «Нормальные»/«Референсные» — слово не в словаре.

    Отказ называет само неизвестное слово, а не роль, которой не хватает:
    новое правило судит по опознанности колонки, а не по набору ролей.
    """
    lines = [
        "Показатель Результат Ед. изм. Норма",
        "C-реактивный белок (СРБ) 0.7 мг/л 0 - 5",
    ]
    with pytest.raises(LabTableError) as exc_info:
        parse_lab_lines(lines)
    assert "норма" in str(exc_info.value)


def test_header_without_units_column_is_parsed_with_empty_units():
    """Бланк без колонки единиц — обычное дело: единицы часто стоят прямо
    в названии («Гемоглобин, г/л»), и отсутствие отдельной колонки не
    повод отказывать в разборе всей таблицы."""
    lines = [
        "Параметр Результат Референсные значения",
        "Ферритин 45 10 - 120",
    ]
    table = parse_lab_lines(lines)
    row = table.rows[0]
    assert row.value_text == "45"
    assert row.reference_text == "10 - 120"
    assert row.units == ""


def test_other_column_does_not_leak_into_value_or_units():
    """Колонка «Комментарий» опознана как известная, но не нужная роль —
    её содержимое не должно попасть ни в значение, ни в единицы, ни в
    референс."""
    lines = [
        "Исследование Результат Единицы Референсные Комментарий",
        "Ферритин 45 нг/мл 10 - 120 в норме",
    ]
    table = parse_lab_lines(lines)
    row = table.rows[0]
    assert row.value_text == "45"
    assert row.units == "нг/мл"
    assert row.reference_text == "10 - 120"


def test_free_text_column_that_is_not_last_is_refused():
    """«Комментарий» — свободный текст: в ячейке стоит сколько угодно слов.

    Непоследняя колонка забирает ровно один токен, поэтому из строки
    «Ферритин 45 в норме нг/мл 10 - 120» в единицы встало бы «норме», и
    запись осела бы в бланке с выдуманными единицами — без отказа и без
    следа в unparsed. Свободный текст читается однозначно только
    последней колонкой; в любом другом месте шапки — отказ.
    """
    lines = [
        "Показатель Результат Комментарий Ед. изм. Референсные значения",
        "Ферритин 45 в норме нг/мл 10 - 120",
    ]
    with pytest.raises(LabTableError) as exc_info:
        parse_lab_lines(lines)
    assert "комментарий" in str(exc_info.value).casefold()


def test_free_text_column_right_after_the_name_is_refused():
    """Та же опасность сразу за названием: «Комментарий» съел бы токен,
    который на деле принадлежит результату."""
    lines = [
        "Показатель Комментарий Результат Ед. изм.",
        "Ферритин в норме 45 нг/мл",
    ]
    with pytest.raises(LabTableError) as exc_info:
        parse_lab_lines(lines)
    assert "комментарий" in str(exc_info.value).casefold()


def test_two_free_text_columns_at_the_end_are_parsed():
    """Две колонки свободного текста подряд в конце опасности не несут:
    последняя роль забирает весь хвост, а содержимое «прочего» в запись
    бланка не попадает вовсе."""
    lines = [
        "Исследование Результат Единицы Референсные Комментарий Предыдущий",
        "Ферритин 45 нг/мл 10 - 120 в норме 38",
    ]
    table = parse_lab_lines(lines)
    (row,) = table.rows
    assert row.value_text == "45"
    assert row.units == "нг/мл"
    assert row.reference_text == "10 - 120"


_CORPUS_HEADERS_PARSE = [
    "Показатель Результат Референсные значения Ед.изм.",
    "Исследование Результат Единицы Референсные Комментарий",
    "Показатель Результат Реф. значения Предыдущий",
    "Параметр Результат Референсные значения",
    "Исследование Результат Единицы Референсные значения",
]

_CORPUS_HEADERS_REFUSE_OCR_TYPOS = [
    "Показатель Результат Ел. изм. Референсные пределы",
    "Параметр Результат Референскыю значения Ед. изм.",
    "Параметр Результат Референсные значения En. изм.",
]


@pytest.mark.parametrize("header", _CORPUS_HEADERS_PARSE)
def test_real_corpus_header_with_only_known_words_is_parsed(header):
    parse_lab_lines([header])


@pytest.mark.parametrize("header", _CORPUS_HEADERS_REFUSE_OCR_TYPOS)
def test_real_corpus_header_with_an_ocr_typo_is_still_refused(header):
    """«Ел.», «Референскыю», «En.» — опечатки распознавания, не слова
    словаря. Неточное совпадение — задача 6; здесь они по-прежнему
    отвергаются, а не подставляются под известную роль."""
    with pytest.raises(LabTableError):
        parse_lab_lines([header])


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
