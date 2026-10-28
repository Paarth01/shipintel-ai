"""Plain-text decoding. Form feeds (\\f) are treated as page breaks."""

from __future__ import annotations

from app.errors import UnreadableDocumentError
from app.extractors.pdf_text import RawPage


def decode_text_bytes(data: bytes) -> str:
    if b"\x00" in data[:8192]:
        raise UnreadableDocumentError("The file looks binary, not plain text.")
    for encoding in ("utf-8-sig", "utf-8"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    return data.decode("cp1252", errors="replace")  # common legacy encoding on Windows


def extract_txt_pages(data: bytes) -> list[RawPage]:
    text = decode_text_bytes(data)
    parts = text.split("\f") if "\f" in text else [text]
    return [RawPage(page=i + 1, text=part) for i, part in enumerate(parts)]
