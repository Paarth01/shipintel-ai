"""Security controls added for audit findings S1-S11: auth, lockout, rate limits, size limits,
server-side policy, headers, error format, logging hygiene."""

from __future__ import annotations

import asyncio
import hmac
import json
import logging

import pytest
from fastapi.testclient import TestClient

from app.api import AUTH_FAILS, LIMITER, create_app
from app.config import (
    MIN_API_KEY_LENGTH,
    ConfigError,
    get_settings,
    parse_api_keys,
    validate_for_startup,
)
from app.security import RateLimiter, client_ip, extract_presented_key, resolve_feature
from tests.conftest import SAMPLE_BL

KEY = "k_live_0123456789abcdef0123456789"
OTHER = "k_live_ABCDEFGHIJKLMNOPQRSTUVWXYZ"
DOC = {"file": ("bl.txt", SAMPLE_BL.encode())}


@pytest.fixture
def client():
    return TestClient(create_app(), raise_server_exceptions=False)


def with_keys(monkeypatch, value=f"alice:{KEY}"):
    monkeypatch.setenv("SHIPINTEL_API_KEYS", value)


# ------------------------------------------------------------------ authentication
def test_extract_requires_key_when_configured(client, monkeypatch):
    with_keys(monkeypatch)
    r = client.post("/extract", files=DOC)
    assert r.status_code == 401 and r.json()["error"]["code"] == "UNAUTHORIZED"
    assert r.headers["www-authenticate"] == "Bearer"


def test_wrong_key_is_rejected_right_key_accepted_both_header_styles(client, monkeypatch):
    with_keys(monkeypatch)
    assert client.post("/extract", files=DOC, headers={"X-API-Key": OTHER}).status_code == 401
    assert client.post("/extract", files=DOC, headers={"X-API-Key": KEY}).status_code == 200
    assert (
        client.post("/extract", files=DOC, headers={"Authorization": f"Bearer {KEY}"}).status_code
        == 200
    )
    assert (
        client.post("/extract", files=DOC, headers={"Authorization": f"Basic {KEY}"}).status_code
        == 401
    )


def test_auth_is_checked_before_the_body_is_read(client, monkeypatch):
    """An unauthenticated client must be refused without the server parsing its upload."""
    with_keys(monkeypatch)
    calls = []
    monkeypatch.setattr("app.worker_tasks.process_document", lambda *a, **k: calls.append(1))
    assert client.post("/extract", files=DOC).status_code == 401
    assert not calls


def test_health_and_ready_stay_open_but_metrics_needs_a_key(client, monkeypatch):
    with_keys(monkeypatch)
    assert client.get("/health").status_code == 200
    assert client.get("/ready").status_code == 200
    assert client.get("/metrics").status_code == 401
    assert client.get("/metrics", headers={"X-API-Key": KEY}).status_code == 200


def test_open_mode_without_keys_still_works_in_development(client):
    assert client.post("/extract", files=DOC).status_code == 200


def test_keys_are_stored_only_as_digests():
    keys = parse_api_keys(f"alice:{KEY}")
    assert (
        keys[0].name == "alice"
        and KEY not in repr(keys)
        and keys[0].digest != KEY
        and len(keys[0].digest) == 64
    )
    assert KEY not in repr(get_settings())


def test_weak_keys_are_rejected_at_startup():
    with pytest.raises(ConfigError):
        parse_api_keys("alice:short")
    assert MIN_API_KEY_LENGTH >= 24


def test_production_refuses_to_start_without_keys(monkeypatch):
    monkeypatch.setenv("SHIPINTEL_ENV", "production")
    with pytest.raises(ConfigError):
        create_app()
    monkeypatch.setenv("SHIPINTEL_API_KEYS", KEY)
    assert create_app() is not None


def test_key_comparison_is_constant_time_and_checks_every_key(monkeypatch):
    from app import security

    monkeypatch.setenv("SHIPINTEL_API_KEYS", f"a:{KEY},b:{OTHER}")
    calls = []
    real = hmac.compare_digest
    monkeypatch.setattr(security.hmac, "compare_digest", lambda a, b: calls.append(1) or real(a, b))
    assert security.authenticate(get_settings(), KEY).name == "a"
    assert len(calls) == 2  # did not stop at the first match


def test_failed_auth_lockout_blocks_even_a_correct_key(client, monkeypatch):
    with_keys(monkeypatch)
    monkeypatch.setenv("SHIPINTEL_AUTH_FAIL_LIMIT_PER_MIN", "3")
    for _ in range(3):
        assert client.post("/extract", files=DOC, headers={"X-API-Key": OTHER}).status_code == 401
    r = client.post("/extract", files=DOC, headers={"X-API-Key": KEY})
    assert (
        r.status_code == 429
        and "retry-after" in r.headers
        and r.json()["error"]["code"] == "RATE_LIMITED"
    )


# ------------------------------------------------------------------ rate limiting
def test_rate_limit_per_client_with_retry_after(client, monkeypatch):
    monkeypatch.setenv("SHIPINTEL_RATE_LIMIT_PER_MIN", "3")
    codes = [client.post("/extract", files=DOC).status_code for _ in range(5)]
    assert codes == [200, 200, 200, 429, 429]
    r = client.post("/extract", files=DOC)
    assert int(r.headers["retry-after"]) >= 1


def test_rate_limit_buckets_are_per_key(client, monkeypatch):
    with_keys(monkeypatch, f"a:{KEY},b:{OTHER}")
    monkeypatch.setenv("SHIPINTEL_RATE_LIMIT_PER_MIN", "2")
    ha, hb = {"X-API-Key": KEY}, {"X-API-Key": OTHER}
    assert [client.post("/extract", files=DOC, headers=ha).status_code for _ in range(3)] == [
        200,
        200,
        429,
    ]
    assert client.post("/extract", files=DOC, headers=hb).status_code == 200


def test_rate_limiter_window_and_bounded_memory():
    rl = RateLimiter(max_keys=100)
    assert [rl.check("a", 2, now=t)[0] for t in (0, 1, 2, 61.5)] == [True, True, False, True]
    for i in range(5000):
        rl.check(f"ip:{i}", 5, now=1000.0 + i * 0.001)
    assert len(rl._hits) <= 200  # eviction keeps memory bounded under a key flood


def test_limits_can_be_disabled():
    rl = RateLimiter()
    assert all(rl.check("x", 0)[0] for _ in range(1000))


def test_client_ip_ignores_forwarded_header_unless_proxy_is_trusted():
    h = {"x-forwarded-for": "6.6.6.6, 10.0.0.9"}
    assert client_ip(h, "1.2.3.4", False) == "1.2.3.4"  # spoofing attempt ignored
    assert client_ip(h, "1.2.3.4", True) == "10.0.0.9"  # rightmost hop, added by the trusted proxy


def test_forwarded_header_cannot_bypass_rate_limit(client, monkeypatch):
    monkeypatch.setenv("SHIPINTEL_RATE_LIMIT_PER_MIN", "2")
    codes = [
        client.post("/extract", files=DOC, headers={"X-Forwarded-For": f"9.9.9.{i}"}).status_code
        for i in range(4)
    ]
    assert codes == [200, 200, 429, 429]


# ------------------------------------------------------------------ server-side feature policy
def test_client_cannot_enable_ocr_or_nlp_the_server_disabled(client):
    for q in ("ocr=true", "nlp=true"):
        r = client.post(f"/extract?{q}", files=DOC)
        assert r.status_code == 403 and r.json()["error"]["code"] == "FEATURE_DISABLED"


def test_client_may_turn_features_off(client):
    assert client.post("/extract?ocr=false&nlp=false", files=DOC).status_code == 200


def test_scanned_pdf_with_ocr_param_is_refused_not_silently_processed(client, scanned_pdf_factory):
    r = client.post(
        "/extract?ocr=true", files={"file": ("s.pdf", scanned_pdf_factory("Vessel: X"))}
    )
    assert r.status_code == 403  # was: 200 with OCR run (audit S4)


def test_resolve_feature_truth_table():
    assert (
        resolve_feature("OCR", False, None) is False and resolve_feature("OCR", True, None) is True
    )
    assert (
        resolve_feature("OCR", True, False) is False and resolve_feature("OCR", True, True) is True
    )
    with pytest.raises(Exception, match="disabled"):
        resolve_feature("OCR", False, True)


# ------------------------------------------------------------------ request size (S3)
def _asgi_post(app, chunks, headers):
    """Drive the ASGI app directly with a lazily consumed chunked body; report bytes consumed."""
    consumed = {"n": 0, "calls": 0}
    sent: list[dict] = []
    queue = list(chunks)

    async def receive():
        consumed["calls"] += 1
        if queue:
            body = queue.pop(0)
            consumed["n"] += len(body)
            return {"type": "http.request", "body": body, "more_body": bool(queue)}
        return {"type": "http.disconnect"}

    async def send(message):
        sent.append(message)

    scope = {
        "type": "http",
        "method": "POST",
        "path": "/extract",
        "headers": headers,
        "query_string": b"",
        "client": ("127.0.0.1", 1),
        "http_version": "1.1",
        "scheme": "http",
        "server": ("t", 80),
        "root_path": "",
        "raw_path": b"/extract",
    }
    asyncio.run(app(scope, receive, send))
    start = next(m for m in sent if m["type"] == "http.response.start")
    body = b"".join(m.get("body", b"") for m in sent if m["type"] == "http.response.body")
    return start["status"], json.loads(body), consumed


def test_chunked_upload_is_cut_off_at_the_limit(monkeypatch):
    monkeypatch.setenv("SHIPINTEL_MAX_UPLOAD_MB", "1")
    app = create_app()
    chunk = b"A" * 65536
    headers = [
        (b"content-type", b"multipart/form-data; boundary=x"),
        (b"transfer-encoding", b"chunked"),
    ]
    prefix = (
        b'--x\r\nContent-Disposition: form-data; name="file"; filename="big.txt"\r\n'
        b"Content-Type: text/plain\r\n\r\n"
    )
    # a VALID multipart stream (otherwise the parser would reject it on the first chunk)
    status, body, consumed = _asgi_post(
        app, [prefix + chunk] + [chunk] * 200, headers
    )  # ~12.5 MB offered, no Content-Length
    assert status == 413 and body["error"]["code"] == "FILE_TOO_LARGE"
    assert consumed["n"] <= 1024 * 1024 + 64 * 1024 + 2 * 65536, (
        consumed
    )  # stopped reading near 1 MB
    assert consumed["n"] < 200 * 65536 / 4


def test_declared_oversize_is_rejected_without_reading_anything(monkeypatch):
    monkeypatch.setenv("SHIPINTEL_MAX_UPLOAD_MB", "1")
    app = create_app()
    headers = [
        (b"content-type", b"multipart/form-data; boundary=x"),
        (b"content-length", b"99999999"),
    ]
    status, body, consumed = _asgi_post(app, [b"x" * 10], headers)
    assert status == 413 and consumed["n"] == 0


def test_text_over_the_character_limit_is_413_not_500(client, monkeypatch):
    monkeypatch.setenv("SHIPINTEL_MAX_TEXT_CHARS", "1000")
    r = client.post("/extract", files={"file": ("a.txt", ("Vessel: MV A ONE\n" * 200).encode())})
    assert r.status_code == 413 and r.json()["error"]["code"] == "TEXT_TOO_LARGE"


# ------------------------------------------------------------------ headers, errors, docs, CORS
def test_security_headers_on_every_response(client):
    for r in (
        client.get("/health"),
        client.get("/nope"),
        client.post("/extract", files={"file": ("a.docx", b"x")}),
    ):
        h = r.headers
        assert h["x-content-type-options"] == "nosniff" and h["x-frame-options"] == "DENY"
        assert (
            h["cache-control"] == "no-store"
            and "default-src 'none'" in h["content-security-policy"]
        )
        assert h["referrer-policy"] == "no-referrer" and h["x-request-id"]
    assert "strict-transport-security" not in client.get("/health").headers


def test_hsts_when_enabled(monkeypatch):
    monkeypatch.setenv("SHIPINTEL_HSTS", "true")
    assert "max-age" in TestClient(create_app()).get("/health").headers["strict-transport-security"]


def test_docs_page_is_not_blocked_by_the_json_csp(client):
    r = client.get("/docs")
    assert r.status_code == 200 and "content-security-policy" not in r.headers


def test_docs_are_disabled_in_production(monkeypatch):
    monkeypatch.setenv("SHIPINTEL_ENV", "production")
    monkeypatch.setenv("SHIPINTEL_API_KEYS", KEY)
    c = TestClient(create_app())
    assert c.get("/docs").status_code == 404 and c.get("/openapi.json").status_code == 404


def test_unknown_route_and_wrong_method_use_the_standard_error_format(client):
    r = client.get("/nope")
    assert r.status_code == 404 and r.json() == {
        "error": {"code": "NOT_FOUND", "message": "Resource not found."}
    }
    r = client.get("/extract")
    assert (
        r.status_code == 405
        and r.json()["error"]["code"] == "METHOD_NOT_ALLOWED"
        and "POST" in r.headers["allow"]
    )


def test_request_id_is_echoed_and_unsafe_values_are_replaced(client):
    assert (
        client.get("/health", headers={"X-Request-ID": "abc-12345_XYZ"}).headers["x-request-id"]
        == "abc-12345_XYZ"
    )
    bad = client.get("/health", headers={"X-Request-ID": "x" * 200}).headers["x-request-id"]
    assert len(bad) == 32 and bad != "x" * 200


def test_no_cors_by_default_and_allowlist_when_configured(client, monkeypatch):
    r = client.get("/health", headers={"Origin": "https://evil.example"})
    assert "access-control-allow-origin" not in r.headers
    monkeypatch.setenv("SHIPINTEL_CORS_ORIGINS", "https://app.example")
    c = TestClient(create_app())
    ok = c.options(
        "/extract",
        headers={"Origin": "https://app.example", "Access-Control-Request-Method": "POST"},
    )
    bad = c.options(
        "/extract",
        headers={"Origin": "https://evil.example", "Access-Control-Request-Method": "POST"},
    )
    assert ok.headers.get("access-control-allow-origin") == "https://app.example"
    assert "access-control-allow-origin" not in bad.headers


def test_ready_and_metrics(client, monkeypatch):
    assert client.get("/ready").json()["status"] == "ready"
    client.post("/extract", files=DOC)
    client.post("/extract", files={"file": ("a.docx", b"x")})
    text = client.get("/metrics").text
    assert 'shipintel_http_requests_total{method="POST",path="/extract",status="200"} 1' in text
    assert 'status="415"' in text and "shipintel_workers_healthy 1" in text
    monkeypatch.setenv("SHIPINTEL_RATE_LIMIT_PER_MIN", "1")
    client.post("/extract", files=DOC)
    client.post("/extract", files=DOC)
    monkeypatch.setenv(
        "SHIPINTEL_RATE_LIMIT_PER_MIN", "0"
    )  # unlimited, so reading metrics is not itself limited
    assert 'event="rate_limited"' in client.get("/metrics").text


def test_metrics_label_cardinality_is_bounded(client):
    for i in range(50):
        client.get(f"/random-path-{i}")
    text = client.get("/metrics").text
    assert 'path="other"' in text and "random-path" not in text


# ------------------------------------------------------------------ logging hygiene
def test_logs_contain_request_ids_but_never_document_content():
    records: list[logging.LogRecord] = []

    class Grab(logging.Handler):
        def emit(self, record):
            records.append(record)

    handler = Grab()
    c = TestClient(create_app())  # setup_logging() resets handlers, so attach ours afterwards
    logging.getLogger("shipintel").addHandler(handler)
    try:
        marker = "SECRETMARKER-7731"
        c.post(
            "/extract",
            files={"file": ("bl.txt", f"Vessel: MV {marker} ONE\nShipper: {marker} Ltd".encode())},
            headers={"X-Request-ID": "req-test-0001"},
        )
        c.post("/extract", files={"file": ("a.docx", marker.encode())})
    finally:
        logging.getLogger("shipintel").removeHandler(handler)
    assert records and all(
        marker not in r.getMessage() and marker not in json.dumps(r.__dict__, default=str)
        for r in records
    )
    assert any(
        getattr(r, "path", "") == "/extract" and getattr(r, "status", 0) == 200 for r in records
    )


def test_unexpected_error_log_has_type_only(monkeypatch):
    records: list[logging.LogRecord] = []

    class Grab(logging.Handler):
        def emit(self, record):
            records.append(record)

    h = Grab()
    logging.getLogger("shipintel").addHandler(h)
    monkeypatch.setattr(
        "app.worker_tasks.process_document",
        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("DOC-SECRET-TEXT")),
    )
    try:
        r = TestClient(create_app(), raise_server_exceptions=False).post("/extract", files=DOC)
    finally:
        logging.getLogger("shipintel").removeHandler(h)
    assert r.status_code == 500 and "DOC-SECRET-TEXT" not in r.text
    assert not any("DOC-SECRET-TEXT" in r.getMessage() for r in records)


def test_startup_warnings():
    from app.config import Settings

    assert any("OPEN" in w for w in validate_for_startup(Settings()))
    assert not any(
        "OPEN" in w for w in validate_for_startup(Settings(api_keys=parse_api_keys(KEY)))
    )


def test_extract_presented_key_variants():
    assert extract_presented_key({"x-api-key": " abc "}) == "abc"
    assert extract_presented_key({"authorization": "Bearer tok"}) == "tok"
    assert (
        extract_presented_key({"authorization": "Basic tok"}) is None
        and extract_presented_key({}) is None
    )
    LIMITER.reset()
    AUTH_FAILS.reset()
