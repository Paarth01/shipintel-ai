"""Optional OCR adapter (Tesseract via pytesseract). Disabled unless explicitly enabled.

Tesseract is an external system dependency; see README. Images are rendered in memory and passed to
Tesseract through pytesseract (argument-list subprocess call, no shell).

Resource bounds (a 520-byte PDF can declare a huge page, so the *declared* size is never trusted):
page count, total OCR time, per-page time, and a pixel cap per rendered page (the DPI is reduced to
fit; if that would drop below `ocr_min_dpi` the page is refused).
"""

from __future__ import annotations

import threading
import time

import pymupdf

from app.config import Settings
from app.deadline import Deadline
from app.errors import (
    OCRUnavailableError,
    PageTooLargeError,
    ProcessingTimeoutError,
    ResourceLimitError,
    UnreadableDocumentError,
)
from app.extractors.pdf_text import RawPage

_AVAIL_LOCK = threading.Lock()
_AVAIL_CACHE: dict[str | None, tuple[float, bool]] = {}
_AVAIL_TTL_S = 60.0


def _import_pytesseract(settings: Settings):
    try:
        import pytesseract
    except ImportError:
        raise OCRUnavailableError(
            "OCR requires the 'pytesseract' package (pip install -r requirements-ocr.txt)."
        ) from None
    if settings.tesseract_cmd:
        pytesseract.pytesseract.tesseract_cmd = settings.tesseract_cmd
    return pytesseract


def ocr_available(settings: Settings) -> bool:
    """Whether Tesseract works. Cached for 60 s so health checks do not spawn a process each call."""
    now = time.monotonic()
    with _AVAIL_LOCK:
        hit = _AVAIL_CACHE.get(settings.tesseract_cmd)
        if hit and now - hit[0] < _AVAIL_TTL_S:
            return hit[1]
    try:
        _import_pytesseract(settings).get_tesseract_version()
        ok = True
    except Exception:
        ok = False
    with _AVAIL_LOCK:
        _AVAIL_CACHE[settings.tesseract_cmd] = (now, ok)
    return ok


def render_dpi(width_pt: float, height_pt: float, settings: Settings, page_number: int) -> int:
    """DPI to render a page at: the configured DPI, reduced so the pixmap stays under the cap."""
    w_in, h_in = width_pt / 72.0, height_pt / 72.0
    if w_in <= 0 or h_in <= 0:
        raise UnreadableDocumentError(f"Page {page_number} has an invalid size.")
    dpi = settings.ocr_dpi
    if (w_in * dpi) * (h_in * dpi) <= settings.ocr_max_pixels:
        return dpi
    dpi = int((settings.ocr_max_pixels / (w_in * h_in)) ** 0.5)
    if dpi < settings.ocr_min_dpi:
        raise PageTooLargeError(
            f"Page {page_number} is {w_in:.0f} x {h_in:.0f} inches, too large to OCR safely."
        )
    return dpi


def ocr_pdf_pages(
    data: bytes,
    page_numbers: list[int],
    settings: Settings,
    deadline: Deadline | None = None,
) -> list[RawPage]:
    """OCR the given 1-based pages of a PDF."""
    if len(page_numbers) > settings.ocr_max_pages:
        raise ResourceLimitError(
            f"OCR is limited to {settings.ocr_max_pages} pages per document "
            f"({len(page_numbers)} need it)."
        )
    pytesseract = _import_pytesseract(settings)
    if not ocr_available(settings):
        raise OCRUnavailableError(
            "Tesseract OCR is not installed or not on PATH. See the README section 'Optional OCR'."
        )
    from PIL import Image

    try:
        doc = pymupdf.open(stream=data, filetype="pdf")
    except Exception:
        raise UnreadableDocumentError("The PDF could not be opened for OCR.") from None
    started = time.monotonic()
    results: list[RawPage] = []
    try:
        for number in page_numbers:
            if deadline is not None:
                deadline.check()
            left = settings.ocr_total_timeout_s - (time.monotonic() - started)
            if left <= 0:
                raise ProcessingTimeoutError(
                    f"OCR exceeded the {settings.ocr_total_timeout_s} s limit for one document."
                )
            page = doc.load_page(number - 1)
            dpi = render_dpi(page.rect.width, page.rect.height, settings, number)
            # Grayscale straight into PIL: 1 byte/pixel and no PNG encode/decode round trip
            # (~3x less peak memory than RGB + PNG). Tesseract converts to grayscale anyway.
            pix = page.get_pixmap(dpi=dpi, colorspace=pymupdf.csGRAY, alpha=False)
            image = Image.frombytes("L", (pix.width, pix.height), pix.samples)
            del pix
            try:
                text = pytesseract.image_to_string(
                    image, lang=settings.ocr_lang, timeout=max(1, min(settings.ocr_timeout_s, left))
                )
            except RuntimeError:  # pytesseract raises RuntimeError on timeout
                raise ProcessingTimeoutError(f"OCR timed out on page {number}.") from None
            except Exception:
                raise UnreadableDocumentError(f"OCR failed on page {number}.") from None
            results.append(RawPage(page=number, text=text, ocr_used=True))
    finally:
        doc.close()
    return results
