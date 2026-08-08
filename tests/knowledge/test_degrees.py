from healthcoach.knowledge.degrees import (
    DEGREE_ORDER,
    DEGREE_SEVERITY,
    degree_rank,
    degree_severity,
    normalize_degree,
)


def test_normalize_lowers_case_and_folds_yo():
    assert normalize_degree("  Тяжёлая ") == "тяжелая"
    assert normalize_degree("ОЧЕНЬ ТЯЖЁЛЫЙ") == "очень тяжелый"


def test_every_entry_in_order_is_already_normalized():
    """Ненормализованная запись была бы недостижима через degree_rank."""
    for name in DEGREE_ORDER:
        assert normalize_degree(name) == name


def test_rank_is_monotonic_within_each_family():
    feminine = ("низкая", "средняя", "умеренная", "высокая", "тяжелая", "очень тяжелая")
    masculine = ("нормальный", "средний", "умеренный", "тяжелый", "очень тяжелый")
    for family in (feminine, masculine):
        ranks = [degree_rank(name) for name in family]
        assert ranks == sorted(ranks)


def test_yo_and_e_spellings_rank_the_same():
    assert degree_rank("Тяжёлая") == degree_rank("тяжелая")


def test_unknown_degree_has_no_rank():
    assert degree_rank("странная") is None


def test_every_degree_in_order_has_a_severity():
    """Две структуры уже расходились однажды — тест не даёт этому повториться."""
    assert set(DEGREE_SEVERITY) == set(DEGREE_ORDER)


def test_severity_does_not_depend_on_gender():
    pairs = (
        ("средняя", "средний"),
        ("умеренная", "умеренный"),
        ("тяжелая", "тяжелый"),
        ("очень тяжелая", "очень тяжелый"),
    )
    for feminine, masculine in pairs:
        assert degree_severity(feminine) == degree_severity(masculine)


def test_severity_ignores_case_and_yo():
    assert degree_severity("Тяжёлая") == degree_severity("тяжелая")


def test_dass_key_sheet_names_are_all_known():
    """Названия градаций DASS взяты с листа «РЕЗУЛЬТАТ КЛЮЧ» дословно."""
    for name in ("Нормальный", "Средний", "Умеренный", "Тяжелый", "Очень тяжелый"):
        assert degree_severity(name) is not None
