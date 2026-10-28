"""FastAPI service: /extract, /health, /ready, /metrics. Thin layer over app.pipeline.

Hardening (see docs/operations.md and docs/audit_remediation.md):
  * HardeningMiddleware (pure ASGI, runs BEFORE the body is read): authentication, failed-auth
    lockout, per-client rate limiting, streaming request-size limit (also for chunked uploads),
    security headers, request IDs, structured access log, metrics.
  * Extraction runs in isolated worker processes with a hard timeout and memory cap (sandbox.py).
  * Server policy decides OCR/NLP; a client can switch a feature off, never on.
"""

from __future__ import annotations

import json
import logging
import re
import time
import uuid
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, File, Query, Request, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, PlainTextResponse
from pydantic import BaseModel
from starlette.exceptions import HTTPException as StarletteHTTPException

from app import PIPELINE_VERSION, __version__
from app.config import Settings, get_settings, validate_for_startup
from app.errors import FileTooLargeError, ServerBusyError, ShipIntelError
from app.extractors.ocr import ocr_available
from app.logging_config import request_id_var, setup_logging
from app.metrics import METRICS
from app.sandbox import get_pool, shutdown_pool
from app.schemas import ExtractionResult
from app.security import (
    RateLimiter,
    authenticate,
    client_ip,
    extract_presented_key,
    resolve_feature,
)

log = logging.getLogger("shipintel.api")

LIMITER = RateLimiter()  # per client, all protected endpoints
AUTH_FAILS = RateLimiter()  # failed authentication attempts per client IP
_REQUEST_ID = re.compile(r"^[A-Za-z0-9._-]{8,64}$")
_PROTECTED = {("POST", "/extract"), ("GET", "/metrics")}
_NO_CSP_PATHS = {"/docs", "/redoc"}  # Swagger UI needs scripts; everything else is JSON/text

DESCRIPTION = """
Extracts shipping fields from **PDF / TXT** documents with a **rule-based baseline**
(dictionaries + regular expressions; not a trained model), validates and normalises them, and
returns the **evidence** (page, offsets, snippet) for each value. Missing or ambiguous values are
returned as `null` with a status and warnings - nothing is guessed.

Authentication: send `X-API-Key: <key>` (or `Authorization: Bearer <key>`) when the server has
`SHIPINTEL_API_KEYS` configured. OCR/NLP are controlled by the server; `?ocr=false` can only turn a
feature off for one request.
"""


class ErrorBody(BaseModel):
    code: str
    message: str


class ErrorResponse(BaseModel):
    error: ErrorBody


class HealthResponse(BaseModel):
    status: str
    version: str
    pipeline_version: str


class ReadyResponse(BaseModel):
    status: str
    workers: int
    isolation: str
    ocr_enabled: bool
    ocr_available: bool


_ERR = {"model": ErrorResponse}


def _json_error(
    status: int, code: str, message: str, headers: dict[str, str] | None = None
) -> JSONResponse:
    return JSONResponse(
        status_code=status, content={"error": {"code": code, "message": message}}, headers=headers
    )


# --------------------------------------------------------------------------- middleware
class HardeningMiddleware:
    """Pure ASGI so it can gate requests before the body is read and wrap `receive`."""

    def __init__(self, app):
        self.app = app

    def _security_headers(self, settings: Settings, path: str) -> list[tuple[bytes, bytes]]:
        h = {
            "x-content-type-options": "nosniff",
            "x-frame-options": "DENY",
            "referrer-policy": "no-referrer",
            "cache-control": "no-store",
            "cross-origin-resource-policy": "same-origin",
        }
        if path not in _NO_CSP_PATHS:
            h["content-security-policy"] = "default-src 'none'; frame-ancestors 'none'"
        if settings.hsts:
            h["strict-transport-security"] = "max-age=31536000; includeSubDomains"
        return [(k.encode(), v.encode()) for k, v in h.items()]

    def _gate(
        self,
        settings: Settings,
        method: str,
        path: str,
        headers: dict[str, str],
        ip: str,
        state: dict,
    ):
        """Return an early (status, code, message, extra_headers) or None to continue."""
        limit = settings.max_upload_bytes + 64 * 1024  # multipart framing overhead
        declared = headers.get("content-length", "")
        if method in {"POST", "PUT", "PATCH"} and declared.isdigit() and int(declared) > limit:
            METRICS.event("body_too_large")
            err = FileTooLargeError(
                f"The upload exceeds the {settings.max_upload_bytes // 1_048_576} MB limit."
            )
            return err.http_status, err.code, err.message, {}
        if (method, path) not in _PROTECTED:
            return None
        blocked, retry = AUTH_FAILS.peek_blocked(f"ip:{ip}", settings.auth_fail_limit_per_min)
        if blocked:
            METRICS.event("auth_lockout")
            return (
                429,
                "RATE_LIMITED",
                "Too many failed authentication attempts.",
                {"retry-after": str(retry)},
            )
        principal = f"ip:{ip}"
        if settings.auth_required:
            key = authenticate(settings, extract_presented_key(headers))
            if key is None:
                AUTH_FAILS.check(f"ip:{ip}", settings.auth_fail_limit_per_min)
                METRICS.event("auth_failures")
                return (
                    401,
                    "UNAUTHORIZED",
                    "A valid API key is required.",
                    {"www-authenticate": "Bearer"},
                )
            principal = f"key:{key.name}"
        allowed, retry = LIMITER.check(principal, settings.rate_limit_per_min)
        if not allowed:
            METRICS.event("rate_limited")
            return 429, "RATE_LIMITED", "Rate limit exceeded.", {"retry-after": str(retry)}
        state["principal"] = principal
        return None

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        settings = get_settings()
        headers = {k.decode("latin-1").lower(): v.decode("latin-1") for k, v in scope["headers"]}
        method, path = scope["method"], scope["path"]
        rid = headers.get("x-request-id", "")
        rid = rid if _REQUEST_ID.match(rid) else uuid.uuid4().hex
        token = request_id_var.set(rid)
        peer = scope["client"][0] if scope.get("client") else None
        ip = client_ip(headers, peer, settings.trust_proxy)
        started = time.perf_counter()
        state: dict[str, Any] = {
            "status": 500,
            "too_large": False,
            "replaced": False,
            "principal": "-",
        }
        limit = settings.max_upload_bytes + 64 * 1024
        received = 0
        extra_headers = self._security_headers(settings, path) + [(b"x-request-id", rid.encode())]

        async def send_json(
            status: int, code: str, message: str, more: dict[str, str] | None = None
        ):
            body = json.dumps({"error": {"code": code, "message": message}}).encode()
            hdrs = [
                (b"content-type", b"application/json"),
                (b"content-length", str(len(body)).encode()),
            ]
            hdrs += extra_headers + [(k.encode(), v.encode()) for k, v in (more or {}).items()]
            state["status"] = status
            await send({"type": "http.response.start", "status": status, "headers": hdrs})
            await send({"type": "http.response.body", "body": body})

        async def limited_receive():
            nonlocal received
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > limit and not state["too_large"]:
                    state["too_large"] = True  # stop reading: the body is cut off at the limit
                    METRICS.event("body_too_large")
                if state["too_large"]:
                    return {"type": "http.disconnect"}
            return message

        async def send_wrapper(message):
            if state["too_large"]:
                if not state["replaced"] and message["type"] == "http.response.start":
                    state["replaced"] = True
                    err = FileTooLargeError(
                        f"The upload exceeds the {settings.max_upload_bytes // 1_048_576} MB limit."
                    )
                    await send_json(err.http_status, err.code, err.message)
                return  # swallow whatever the app tried to send
            if message["type"] == "http.response.start":
                state["status"] = message["status"]
                message = {**message, "headers": list(message.get("headers", [])) + extra_headers}
            await send(message)

        try:
            early = self._gate(settings, method, path, headers, ip, state)
            if early:
                status, code, msg, more = early
                await send_json(status, code, msg, more)
            else:
                await self.app(scope, limited_receive, send_wrapper)
                if state["too_large"] and not state["replaced"]:
                    err = FileTooLargeError("The upload is too large.")
                    await send_json(err.http_status, err.code, err.message)
        finally:
            elapsed = time.perf_counter() - started
            METRICS.observe_request(method, path, state["status"], elapsed)
            level = logging.WARNING if state["status"] >= 500 else logging.INFO
            log.log(
                level,
                "request",
                extra={
                    "method": method,
                    "path": path if len(path) < 100 else path[:100],
                    "status": state["status"],
                    "duration_ms": round(elapsed * 1000, 1),
                    "client": ip,
                    "principal": state["principal"],
                },
            )
            request_id_var.reset(token)


# --------------------------------------------------------------------------- app factory
def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    setup_logging(settings.log_level, settings.log_format)
    for warning in validate_for_startup(settings):  # raises ConfigError on unsafe production config
        log.warning(warning, extra={"event": "startup_warning"})

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        await run_in_threadpool(get_pool, get_settings())  # pre-start workers
        yield
        shutdown_pool()

    docs = settings.enable_docs
    app = FastAPI(
        title="ShipIntel AI API",
        version=__version__,
        description=DESCRIPTION,
        docs_url="/docs" if docs else None,
        redoc_url=None,
        openapi_url="/openapi.json" if docs else None,
        lifespan=lifespan,
    )
    if settings.cors_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=list(settings.cors_origins),
            allow_methods=["GET", "POST"],
            allow_headers=["X-API-Key", "Authorization", "Content-Type", "X-Request-ID"],
            allow_credentials=False,
        )
    app.add_middleware(HardeningMiddleware)  # added last => outermost

    # ---- consistent error format
    @app.exception_handler(ShipIntelError)
    async def _known(_: Request, exc: ShipIntelError) -> JSONResponse:
        headers = {"retry-after": "5"} if isinstance(exc, ServerBusyError) else None
        METRICS.extract_result(exc.code)
        return _json_error(exc.http_status, exc.code, exc.message, headers)

    @app.exception_handler(StarletteHTTPException)
    async def _http(_: Request, exc: StarletteHTTPException) -> JSONResponse:
        code = {404: "NOT_FOUND", 405: "METHOD_NOT_ALLOWED"}.get(exc.status_code, "HTTP_ERROR")
        message = {404: "Resource not found.", 405: "Method not allowed."}.get(
            exc.status_code, "Request failed."
        )
        return _json_error(exc.status_code, code, message, dict(exc.headers or {}))

    @app.exception_handler(RequestValidationError)
    async def _validation(_: Request, exc: RequestValidationError) -> JSONResponse:
        fields = sorted({".".join(str(p) for p in e["loc"][1:]) or "request" for e in exc.errors()})
        return _json_error(
            422, "INVALID_REQUEST", f"Invalid request: check parameter(s) {', '.join(fields)}."
        )

    @app.exception_handler(Exception)
    async def _unexpected(_: Request, exc: Exception) -> JSONResponse:
        # exception TYPE only: messages can contain document text
        log.error("unexpected error: %s", type(exc).__name__, extra={"event": "unexpected_error"})
        return _json_error(
            500, "INTERNAL_ERROR", "An internal error occurred while processing the document."
        )

    # ---- endpoints
    @app.get("/health", response_model=HealthResponse, tags=["service"])
    async def health() -> HealthResponse:
        """Liveness: the process is up. Cheap and unauthenticated."""
        return HealthResponse(status="ok", version=__version__, pipeline_version=PIPELINE_VERSION)

    @app.get(
        "/ready",
        response_model=ReadyResponse,
        tags=["service"],
        responses={503: {"model": ReadyResponse}},
    )
    async def ready() -> JSONResponse:
        """Readiness: workers are alive (and OCR availability, cached for 60 s)."""
        s = get_settings()
        pool = await run_in_threadpool(get_pool, s)
        workers = pool.healthy_workers()
        body = ReadyResponse(
            status="ready" if workers >= 1 else "unavailable",
            workers=workers,
            isolation=s.isolation,
            ocr_enabled=s.ocr_enabled,
            ocr_available=ocr_available(s) if s.ocr_enabled else False,
        )
        return JSONResponse(status_code=200 if workers >= 1 else 503, content=body.model_dump())

    @app.get(
        "/metrics",
        response_class=PlainTextResponse,
        tags=["service"],
        responses={401: _ERR, 429: _ERR},
    )
    async def metrics() -> PlainTextResponse:
        """Prometheus text metrics. Requires an API key whenever authentication is enabled."""
        pool = await run_in_threadpool(get_pool, get_settings())
        return PlainTextResponse(
            METRICS.render(pool.stats, pool.healthy_workers()),
            media_type="text/plain; version=0.0.4",
        )

    @app.post(
        "/extract",
        response_model=ExtractionResult,
        tags=["extraction"],
        responses={
            400: {**_ERR, "description": "Empty file"},
            401: {**_ERR, "description": "Missing or invalid API key"},
            403: {**_ERR, "description": "Feature disabled on this server (e.g. ocr=true)"},
            413: {**_ERR, "description": "File/text too large, too many pages"},
            415: {**_ERR, "description": "Unsupported file type or content mismatch"},
            422: {**_ERR, "description": "Unreadable/encrypted/scanned PDF, or no text"},
            429: {**_ERR, "description": "Rate limited"},
            503: {**_ERR, "description": "OCR unavailable or all workers busy"},
            504: {**_ERR, "description": "Processing timed out"},
            500: {**_ERR, "description": "Internal error"},
        },
    )
    async def extract(
        file: UploadFile = File(..., description="A .pdf or .txt shipping document"),
        ocr: bool | None = Query(
            None,
            description="false = skip OCR for this request. true is refused unless the server enabled OCR.",
        ),
        nlp: bool | None = Query(
            None,
            description="false = skip spaCy for this request. true is refused unless the server enabled it.",
        ),
        include_text: bool = Query(True, description="Include cleaned page text in the response"),
    ) -> ExtractionResult:
        """Extract, validate and return structured fields with evidence for one document."""
        s = get_settings()
        use_ocr = resolve_feature("OCR", s.ocr_enabled, ocr)
        use_nlp = resolve_feature("NLP", s.nlp_enabled, nlp)
        data = await file.read(s.max_upload_bytes + 1)
        await file.close()
        if len(data) > s.max_upload_bytes:
            raise FileTooLargeError(
                f"The file exceeds the {s.max_upload_bytes // 1_048_576} MB limit."
            )
        pool = await run_in_threadpool(get_pool, s)
        result = await run_in_threadpool(
            pool.run,
            "app.worker_tasks:extract",
            (s, file.filename, data, use_ocr, use_nlp, include_text),
            s.processing_timeout_s + 5,  # hard kill shortly after the cooperative deadline
        )
        METRICS.extract_result(result.status.value)
        return result

    return app


app = create_app()
