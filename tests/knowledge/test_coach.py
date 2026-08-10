import pytest

from healthcoach.knowledge.coach import CoachError, load_coach


def _write(tmp_path, text: str):
    path = tmp_path / "coach.yaml"
    path.write_text(text, encoding="utf-8")
    return path


def test_profile_is_read(tmp_path):
    path = _write(
        tmp_path,
        "имя: Иконникова Екатерина\nдолжность: нутрициолог\nподпись: С уважением\n",
    )
    coach = load_coach(path)
    assert coach.name == "Иконникова Екатерина"
    assert coach.title == "нутрициолог"
    assert coach.signature == "С уважением"


def test_name_is_required(tmp_path):
    path = _write(tmp_path, "должность: нутрициолог\n")
    with pytest.raises(CoachError, match="имя"):
        load_coach(path)


def test_blank_name_is_refused(tmp_path):
    """Титул с пустым именем специалиста — брак, а не мелочь."""
    path = _write(tmp_path, "имя: '   '\n")
    with pytest.raises(CoachError, match="имя"):
        load_coach(path)


def test_optional_fields_default_to_empty(tmp_path):
    coach = load_coach(_write(tmp_path, "имя: Иконникова Екатерина\n"))
    assert coach.title == ""
    assert coach.signature == ""


def test_missing_file_is_refused(tmp_path):
    with pytest.raises(CoachError, match="не найден"):
        load_coach(tmp_path / "нет.yaml")
