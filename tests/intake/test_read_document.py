from pathlib import Path

import pytest

from healthcoach.intake.documents import DocumentError, read_document
from healthcoach.intake.ocr import TextLine
from healthcoach.storage.snapshots import SOURCE_PDF, SOURCE_PHOTO

FIXTURES = Path(__file__).parent / "fixtures"


class FakeEngine:
    """Движок распознавания, отдающий заранее известные наблюдения."""

    def __init__(self, observations):
        self._observations = observations

    def read(self, path: Path):
        return self._observations


def test_photo_goes_through_the_engine(tmp_path):
    path = tmp_path / "бланк.jpg"
    path.write_bytes(b"\xff\xd8\xff")
    engine = FakeEngine(
        [
            TextLine("Показатель", x=0.10, y=0.90),
            TextLine("Результат", x=0.40, y=0.90),
            TextLine("Ед. изм.", x=0.65, y=0.90),
            TextLine("Референсные пределы", x=0.85, y=0.90),
            TextLine("Гемоглобин", x=0.10, y=0.80),
            TextLine("103", x=0.40, y=0.80),
            TextLine("г/л", x=0.65, y=0.80),
            TextLine("117 - 155", x=0.85, y=0.80),
        ]
    )

    document = read_document(path, engine)
    assert document.source == SOURCE_PHOTO
    (row,) = document.table.rows
    assert row.name == "Гемоглобин"
    assert row.value_text == "103"
    assert row.units == "г/л"
    assert row.reference_text == "117 - 155"


def test_photo_without_an_engine_is_refused(tmp_path):
    path = tmp_path / "бланк.jpg"
    path.write_bytes(b"\xff\xd8\xff")
    with pytest.raises(DocumentError, match="распознавание"):
        read_document(path, None)


def test_unknown_extension_is_refused(tmp_path):
    path = tmp_path / "бланк.docx"
    path.write_bytes(b"nope")
    with pytest.raises(DocumentError, match="не поддерживается"):
        read_document(path)


@pytest.mark.samples
def test_sample_pdf_is_read_as_pdf(samples_dir):
    path = sorted(samples_dir.glob("*.pdf"))[0]
    document = read_document(path)
    assert document.source == SOURCE_PDF
    assert document.table.rows
