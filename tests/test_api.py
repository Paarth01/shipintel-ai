from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.api import app
from tests.conftest import SAMPLE_BL

client = TestClient(app, raise_server_exceptions=False)


def post(name: str, data: bytes, ctype: str = "application/octet-stream", **params):
    return client.post("/extract", files={"file": (name, data, ctype)}, params=params)


def test_health():
    r = client.get("/health")
    assert r.status_code == 200
    body = r.json()
    assert body == {
        "status": "ok",
        "version": body["version"],
        "pipeline_version": body["pipeline_version"],
    }


def test_extract_txt():
    r = post("bl.txt", SAMPLE_BL.encode(), "text/plain")
    assert r.status_code == 200
    body = r.json()
    assert body["fields"]["vessel_name"]["value"] == "NORDIC AURORA"
    assert body["fields"]["origin_port"]["evidence"][0]["page"] == 1
    assert body["metadata"]["processing_ms"] >= 0 and body["pages"]


def test_extract_pdf(pdf_factory):
    r = post("bl.pdf", pdf_factory([SAMPLE_BL]), "application/pdf")
    assert r.status_code == 200
    assert r.json()["fields"]["cargo_quantity"]["value"] == 45000.0


def test_include_text_false():
    r = post("bl.txt", SAMPLE_BL.encode(), include_text="false")
    assert r.status_code == 200 and r.json()["pages"] is None


def test_unsupported_type_415():
    r = post("notes.docx", b"hello")
    assert r.status_code == 415 and r.json()["error"]["code"] == "UNSUPPORTED_FILE_TYPE"


def test_content_mismatch_415():
    r = post("fake.pdf", b"not really a pdf")
    assert r.status_code == 415


def test_empty_file_400():
    r = post("a.txt", b"")
    assert r.status_code == 400 and r.json()["error"]["code"] == "EMPTY_FILE"


def test_empty_text_422():
    r = post("a.txt", b"   \n  ")
    assert r.status_code == 422 and r.json()["error"]["code"] == "NO_TEXT_FOUND"


def test_unreadable_pdf_422():
    r = post("bad.pdf", b"%PDF-1.4\ngarbage garbage\n")
    assert r.status_code == 422 and r.json()["error"]["code"] == "UNREADABLE_DOCUMENT"


def test_scanned_pdf_422_with_actionable_message(scanned_pdf_factory):
    r = post("scan.pdf", scanned_pdf_factory("Vessel: NORDIC AURORA"))
    assert r.status_code == 422
    assert (
        r.json()["error"]["code"] == "SCANNED_PDF_NO_TEXT" and "OCR" in r.json()["error"]["message"]
    )


def test_oversized_file_413(monkeypatch):
    monkeypatch.setenv("SHIPINTEL_MAX_UPLOAD_MB", "1")
    r = post("big.txt", b"A" * (1024 * 1024 + 10))
    assert r.status_code == 413 and r.json()["error"]["code"] == "FILE_TOO_LARGE"


def test_oversized_declared_content_length_413_early(monkeypatch):
    monkeypatch.setenv("SHIPINTEL_MAX_UPLOAD_MB", "1")
    r = post("huge.txt", b"A" * (1024 * 1024 + 100_000))
    assert r.status_code == 413


def test_missing_file_422_clean_error():
    r = client.post("/extract")
    assert r.status_code == 422 and r.json()["error"]["code"] == "INVALID_REQUEST"


def test_internal_error_hides_details(monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("secret path /home/user/x.txt")

    monkeypatch.setattr("app.worker_tasks.process_document", boom)
    r = post("bl.txt", SAMPLE_BL.encode())
    assert r.status_code == 500
    text = r.text
    assert (
        "secret" not in text
        and "Traceback" not in text
        and r.json()["error"]["code"] == "INTERNAL_ERROR"
    )


def test_openapi_documents_endpoints():
    spec = client.get("/openapi.json").json()
    assert "/health" in spec["paths"] and "/extract" in spec["paths"]
    assert {"400", "413", "415", "422", "500"} <= set(
        spec["paths"]["/extract"]["post"]["responses"]
    )


@pytest.mark.parametrize("name", ["../../etc/passwd.txt", "C:\\Windows\\a.txt"])
def test_filename_is_sanitised_in_response(name):
    r = post(name, SAMPLE_BL.encode())
    assert r.status_code == 200 and "/" not in r.json()["metadata"]["filename"]
    assert "\\" not in r.json()["metadata"]["filename"]
