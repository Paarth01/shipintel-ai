"""Digital-PDF text extraction with PyMuPDF. Works fully in memory (no temp files)."""

from __future__ import annotations

from dataclasses import dataclass

import pymupdf

from app.config import Settings
from app.deadline import Deadline
from app.errors import (
    EncryptedPDFError,
    TooManyPagesError,
    UnreadableDocumentError,
)

pymupdf.TOOLS.mupdf_display_errors(False)


@dataclass
class RawPage:
    page: int  # 1-based
    text: str
    image_count: int = 0
    ocr_used: bool = False


def extract_pdf_pages(
    data: bytes, settings: Settings, deadline: Deadline | None = None
) -> list[RawPage]:
    try:
        doc = pymupdf.open(stream=data, filetype="pdf")
    except Exception:
        raise UnreadableDocumentError(
            "The PDF could not be opened. It may be corrupted or not a real PDF."
        ) from None
    try:
        if doc.needs_pass:
            raise EncryptedPDFError("The PDF is password-protected. Remove the password and retry.")
        if doc.page_count == 0:
            raise UnreadableDocumentError("The PDF contains no pages.")
        if doc.page_count > settings.max_pages:
            raise TooManyPagesError(
                f"The PDF has {doc.page_count} pages; the limit is {settings.max_pages}."
            )
        pages: list[RawPage] = []
        for index in range(doc.page_count):
            if deadline is not None:
                deadline.check()
            try:
                page = doc.load_page(index)
                text = page.get_text("text", sort=True)
                images = len(page.get_images(full=True))
            except Exception:
                raise UnreadableDocumentError(
                    f"Page {index + 1} of the PDF could not be read."
                ) from None
            pages.append(RawPage(page=index + 1, text=text, image_count=images))
        return pages
    finally:
        doc.close()


def pages_without_text(pages: list[RawPage], min_chars: int) -> list[RawPage]:
    """Pages whose text layer is (almost) empty - candidates for OCR."""
    return [p for p in pages if len("".join(p.text.split())) < min_chars]
