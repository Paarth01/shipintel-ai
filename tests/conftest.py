from __future__ import annotations

import io

import pymupdf
import pytest

from app.config import Settings


@pytest.fixture(autouse=True)
def _clean_environment(monkeypatch):
    """Deterministic tests: no ambient SHIPINTEL_* config, inline (in-process) extraction by default,
    and fresh rate-limiter / metrics / worker-pool state."""
    import os

    for key in [k for k in os.environ if k.startswith("SHIPINTEL_")]:
        monkeypatch.delenv(key)
    monkeypatch.setenv("SHIPINTEL_ISOLATION", "inline")
    from app.api import AUTH_FAILS, LIMITER
    from app.metrics import METRICS
    from app.sandbox import shutdown_pool

    LIMITER.reset()
    AUTH_FAILS.reset()
    METRICS.reset()
    yield
    shutdown_pool()


@pytest.fixture
def settings() -> Settings:
    return Settings()


def make_pdf(pages: list[str]) -> bytes:
    """Digital PDF with a real text layer, built in memory with PyMuPDF."""
    doc = pymupdf.open()
    for text in pages:
        page = doc.new_page()
        page.insert_text((72, 72), text, fontsize=11)
    data = doc.tobytes()
    doc.close()
    return data


def make_scanned_pdf(text: str) -> bytes:
    """PDF containing only a raster image of the text (no text layer)."""
    from PIL import Image, ImageDraw, ImageFont

    image = Image.new("RGB", (1240, 700), "white")
    draw = ImageDraw.Draw(image)
    font = ImageFont.load_default(size=34)
    y = 40
    for line in text.splitlines():
        draw.text((40, y), line, fill="black", font=font)
        y += 52
    buf = io.BytesIO()
    image.save(buf, format="PNG")
    doc = pymupdf.open()
    page = doc.new_page(width=620, height=350)
    page.insert_image(page.rect, stream=buf.getvalue())
    data = doc.tobytes()
    doc.close()
    return data


@pytest.fixture
def pdf_factory():
    return make_pdf


@pytest.fixture
def scanned_pdf_factory():
    return make_scanned_pdf


SAMPLE_BL = (
    "BILL OF LADING\n"
    "B/L No.: MSK2025-04417\n"
    "Shipper: Meridian Bulk Trading Ltd\n"
    "Vessel: M/V NORDIC AURORA\n"
    "Port of Loading: Rotterdam\n"
    "Port of Discharge: Singapore\n"
    "Description of Goods: 45,000 MT Thermal Coal\n"
    "Shipped on Board: 12 March 2025\n"
)
