import sys

import pytest

from healthcoach.intake.ocr import (
    OCRError,
    TextLine,
    rows_from_observations,
)


def test_observations_on_the_same_height_become_one_row():
    """Название и значение приходят разными наблюдениями: колонки далеко."""
    observations = [
        TextLine("Гемоглобин (Hb)", x=0.10, y=0.500),
        TextLine("103", x=0.55, y=0.501),
        TextLine("г/л", x=0.80, y=0.499),
        TextLine("Гематокрит (Ht)", x=0.10, y=0.470),
        TextLine("31,4", x=0.55, y=0.470),
    ]
    assert rows_from_observations(observations) == [
        "Гемоглобин (Hb) 103 г/л",
        "Гематокрит (Ht) 31,4",
    ]


def test_row_keeps_left_to_right_order():
    observations = [
        TextLine("г/л", x=0.80, y=0.5),
        TextLine("103", x=0.55, y=0.5),
        TextLine("Гемоглобин", x=0.10, y=0.5),
    ]
    assert rows_from_observations(observations) == ["Гемоглобин 103 г/л"]


def test_rows_go_from_top_to_bottom():
    observations = [
        TextLine("нижняя", x=0.1, y=0.10),
        TextLine("верхняя", x=0.1, y=0.90),
    ]
    assert rows_from_observations(observations) == ["верхняя", "нижняя"]


def test_observations_further_apart_than_the_tolerance_are_separate_rows():
    observations = [
        TextLine("первая", x=0.1, y=0.500),
        TextLine("вторая", x=0.1, y=0.480),
    ]
    assert len(rows_from_observations(observations, tolerance=0.006)) == 2


def test_no_observations_gives_no_rows():
    assert rows_from_observations([]) == []


@pytest.mark.skipif(sys.platform != "darwin", reason="Vision есть только в macOS")
def test_engine_refuses_a_file_that_is_not_an_image(tmp_path):
    from healthcoach.intake.ocr import AppleVisionEngine

    path = tmp_path / "не картинка.jpg"
    path.write_text("просто текст", encoding="utf-8")
    with pytest.raises(OCRError, match="не распознан"):
        AppleVisionEngine().read(path)


@pytest.mark.samples
@pytest.mark.skipif(sys.platform != "darwin", reason="Vision есть только в macOS")
def test_sample_photo_yields_readable_rows(samples_dir):
    from healthcoach.intake.ocr import AppleVisionEngine

    photos = sorted(samples_dir.glob("*.jpg"))
    assert photos, "в samples/ нет ни одной фотографии"
    rows = rows_from_observations(AppleVisionEngine().read(photos[0]))
    assert len(rows) > 20
    assert any("Гемоглобин" in row for row in rows)
