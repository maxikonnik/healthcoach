from pathlib import Path

import pytest

from healthcoach.intake.documents import DocumentError, read_document
from healthcoach.intake.lab_table import LabTableError
from healthcoach.intake.ocr import OCRError, TextLine
from healthcoach.intake.pdf import PdfError
from healthcoach.storage.snapshots import SOURCE_PDF, SOURCE_PHOTO

FIXTURES = Path(__file__).parent / "fixtures"


class FakeEngine:
    """Движок распознавания, отдающий заранее известные наблюдения."""

    def __init__(self, observations):
        self._observations = observations

    def read(self, path: Path):
        return self._observations


class FailingEngine:
    """Движок распознавания, который всегда отказывает."""

    def read(self, path: Path):
        raise OCRError(f"{path.name}: изображение не распознано")


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


# Регресс: read_document — единственный вход, но раньше пропускал наружу
# PdfError, OCRError и LabTableError необёрнутыми. Коуч, ловящий заявленный
# DocumentError, получал бы необработанное исключение на самом обычном
# случае — сфотографированном бланке, сохранённом как PDF без текстового
# слоя. Все четыре пути ниже должны давать DocumentError с исходной
# причиной в __cause__.


def test_a_photo_saved_as_pdf_is_wrapped_not_leaked(tmp_path):
    """Файл с расширением .pdf, но не PDF по содержимому — типичный случай
    сфотографированного бланка, сохранённого не тем приложением."""
    path = tmp_path / "бланк.pdf"
    path.write_bytes(b"\xff\xd8\xff")  # байты JPEG под чужим расширением
    with pytest.raises(DocumentError) as exc_info:
        read_document(path)
    assert path.name in str(exc_info.value)
    assert isinstance(exc_info.value.__cause__, PdfError)


def test_a_missing_pdf_is_wrapped_not_leaked(tmp_path):
    path = tmp_path / "нет.pdf"
    with pytest.raises(DocumentError) as exc_info:
        read_document(path)
    assert isinstance(exc_info.value.__cause__, PdfError)


def test_a_pdf_without_a_recognisable_table_is_wrapped_not_leaked(tmp_path, monkeypatch):
    """Скан без текстового слоя даёт пустые строки — разбору нечего искать,
    и `parse_lab_lines` отказывает LabTableError."""
    path = tmp_path / "скан.pdf"
    path.write_bytes(b"%PDF-1.4 content is irrelevant, read_pdf_lines is patched")
    monkeypatch.setattr(
        "healthcoach.intake.documents.read_pdf_lines", lambda _path: []
    )
    with pytest.raises(DocumentError) as exc_info:
        read_document(path)
    assert isinstance(exc_info.value.__cause__, LabTableError)


def test_an_ocr_failure_is_wrapped_not_leaked(tmp_path):
    path = tmp_path / "бланк.jpg"
    path.write_bytes(b"\xff\xd8\xff")
    with pytest.raises(DocumentError) as exc_info:
        read_document(path, FailingEngine())
    assert isinstance(exc_info.value.__cause__, OCRError)
