from __future__ import annotations

import pytest

from app.config import Settings
from app.errors import (
    EmptyFileError,
    EncryptedPDFError,
    FileTooLargeError,
    NoTextError,
    OCRUnavailableError,
    ScannedPDFError,
    TooManyPagesError,
    UnreadableDocumentError,
    UnsupportedFileTypeError,
)
from app.extractors.ocr import ocr_available
from app.pipeline import extract_document_text
from tests.conftest import SAMPLE_BL


def test_txt_end_to_end_text_extraction(settings):
    result = extract_document_text("bl.txt", SAMPLE_BL.encode(), settings)
    assert result.file_type == "txt"
    assert result.text_source == "txt"
    assert len(result.pages) == 1
    assert "NORDIC AURORA" in result.pages[0].text
    assert len(result.sha256) == 64


def test_pdf_text_extraction_keeps_pages(settings, pdf_factory):
    data = pdf_factory(["Page one: Vessel NORDIC AURORA", "Page two: Port of Loading Rotterdam"])
    result = extract_document_text("two.pdf", data, settings)
    assert result.file_type == "pdf" and result.text_source == "pdf_text"
    assert [p.page for p in result.pages] == [1, 2]
    assert "NORDIC AURORA" in result.pages[0].text
    assert "Rotterdam" in result.pages[1].text


def test_pdf_multiline_content_roundtrip(settings, pdf_factory):
    result = extract_document_text("bl.pdf", pdf_factory([SAMPLE_BL]), settings)
    text = result.pages[0].text
    assert "Port of Loading" in text and "Rotterdam" in text and "Thermal Coal" in text


def test_cp1252_text_is_decoded(settings):
    result = extract_document_text(
        "x.txt", "Vessel: SÃO PAULO – café".encode("cp1252", "replace"), settings
    )
    assert "Vessel" in result.pages[0].text


def test_unsupported_extension(settings):
    with pytest.raises(UnsupportedFileTypeError):
        extract_document_text("report.docx", b"hello", settings)


def test_pdf_extension_but_not_pdf(settings):
    with pytest.raises(UnsupportedFileTypeError):
        extract_document_text("fake.pdf", b"just some text, not a pdf", settings)


def test_txt_extension_but_is_pdf(settings, pdf_factory):
    with pytest.raises(UnsupportedFileTypeError):
        extract_document_text("fake.txt", pdf_factory(["hello world text here"]), settings)


def test_empty_file(settings):
    with pytest.raises(EmptyFileError):
        extract_document_text("a.txt", b"", settings)


def test_whitespace_only_text_is_no_text(settings):
    with pytest.raises(NoTextError):
        extract_document_text("a.txt", b"  \n \n\t ", settings)


def test_oversized_file(settings):
    small = Settings(max_upload_bytes=100)
    with pytest.raises(FileTooLargeError):
        extract_document_text("a.txt", b"x" * 101, small)


def test_binary_garbage_in_txt(settings):
    with pytest.raises(UnreadableDocumentError):
        extract_document_text("a.txt", b"abc\x00\x01\x02def", settings)


def test_corrupt_pdf(settings):
    with pytest.raises(UnreadableDocumentError):
        extract_document_text("bad.pdf", b"%PDF-1.7\nthis is not a valid pdf body\n%%EOF", settings)


def test_too_many_pages(pdf_factory):
    with pytest.raises(TooManyPagesError):
        extract_document_text("a.pdf", pdf_factory(["page text"] * 3), Settings(max_pages=2))


def test_encrypted_pdf(settings):
    import pymupdf

    doc = pymupdf.open()
    doc.new_page().insert_text((72, 72), "secret document text")
    data = doc.tobytes(encryption=pymupdf.PDF_ENCRYPT_AES_256, user_pw="pw", owner_pw="pw")
    with pytest.raises(EncryptedPDFError):
        extract_document_text("enc.pdf", data, settings)


def test_scanned_pdf_gives_clear_message(settings, scanned_pdf_factory):
    data = scanned_pdf_factory("Vessel: NORDIC AURORA\nPort of Loading: Rotterdam")
    with pytest.raises(ScannedPDFError) as exc:
        extract_document_text("scan.pdf", data, settings)
    assert "OCR" in exc.value.message


def test_ocr_requested_but_unavailable(scanned_pdf_factory, monkeypatch):
    monkeypatch.setattr("app.pipeline.ocr_available", lambda s: False)
    data = scanned_pdf_factory("Vessel: NORDIC AURORA")
    with pytest.raises(OCRUnavailableError):
        extract_document_text("scan.pdf", data, Settings(ocr_enabled=True))


@pytest.mark.skipif(not ocr_available(Settings()), reason="Tesseract not installed")
def test_ocr_reads_scanned_pdf(scanned_pdf_factory):
    data = scanned_pdf_factory("Vessel: NORDIC AURORA\nPort of Loading: Rotterdam")
    result = extract_document_text("scan.pdf", data, Settings(), ocr=True)
    assert result.ocr_used and result.text_source == "pdf_ocr"
    assert "ROTTERDAM" in result.pages[0].text.upper()
    assert any(w.code == "OCR_USED" for w in result.warnings)


def test_path_in_filename_is_stripped(settings):
    result = extract_document_text("../../etc/C:\\evil\\bl.txt", SAMPLE_BL.encode(), settings)
    assert result.filename == "bl.txt"


def test_no_temp_files_left_behind(settings, pdf_factory):
    import os
    import tempfile

    before = set(os.listdir(tempfile.gettempdir()))
    extract_document_text("a.pdf", pdf_factory([SAMPLE_BL]), settings)
    extract_document_text("a.txt", SAMPLE_BL.encode(), settings)
    assert set(os.listdir(tempfile.gettempdir())) == before
