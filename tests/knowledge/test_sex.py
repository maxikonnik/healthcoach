import pytest

from healthcoach.knowledge.sex import SexError, normalize_sex


@pytest.mark.parametrize("raw", ["м", "М", " ж ", "Ж"])
def test_normalize_accepts_both_cases(raw):
    assert normalize_sex(raw) in {"м", "ж"}


@pytest.mark.parametrize("raw", ["m", "муж", "", "мужской", "x"])
def test_normalize_rejects_anything_else(raw):
    with pytest.raises(SexError, match="пол должен быть"):
        normalize_sex(raw)
