import pytest

from healthcoach.intake.lab_table import parse_lab_lines
from healthcoach.intake.pdf import PdfError, read_pdf_lines


def test_missing_file_is_refused(tmp_path):
    with pytest.raises(PdfError, match="не прочитан"):
        read_pdf_lines(tmp_path / "нет.pdf")


def test_not_a_pdf_is_refused(tmp_path):
    path = tmp_path / "текст.pdf"
    path.write_text("это не pdf", encoding="utf-8")
    with pytest.raises(PdfError, match="не прочитан"):
        read_pdf_lines(path)


@pytest.mark.samples
def test_every_sample_pdf_has_a_text_layer(samples_dir):
    """Если текстового слоя нет, разбирать нечего и нужен другой путь."""
    pdfs = sorted(samples_dir.glob("*.pdf"))
    assert pdfs, "в samples/ нет ни одного PDF"
    for path in pdfs:
        lines = read_pdf_lines(path)
        assert len(lines) > 20, f"{path.name}: текстового слоя почти нет"


@pytest.mark.samples
def test_every_sample_pdf_yields_rows(samples_dir):
    for path in sorted(samples_dir.glob("*.pdf")):
        table = parse_lab_lines(read_pdf_lines(path))
        assert table.rows, f"{path.name}: не разобрано ни одной строки результата"
