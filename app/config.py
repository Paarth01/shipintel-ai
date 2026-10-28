"""Runtime settings, read from environment variables (and an optional local .env file).

Security-relevant defaults are conservative: client requests can never switch on a feature the
operator disabled, API keys are held only as SHA-256 digests, and `SHIPINTEL_ENV=production`
refuses to start without authentication.
"""

from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

from app.errors import ConfigError

_ENV_LOADED = False
MIN_API_KEY_LENGTH = 24


def _load_dotenv_once() -> None:
    """Tiny .env loader (no extra dependency). Real environment variables win."""
    global _ENV_LOADED
    if _ENV_LOADED:
        return
    _ENV_LOADED = True
    path = Path(__file__).resolve().parent.parent / ".env"
    if not path.is_file():
        return
    for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def _env_bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _env_int(name: str, default: int, minimum: int | None = None) -> int:
    try:
        value = int(os.environ.get(name, default))
    except ValueError:
        value = default
    return max(value, minimum) if minimum is not None else value


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, default))
    except ValueError:
        return default


def _env_list(name: str) -> tuple[str, ...]:
    return tuple(x.strip() for x in os.environ.get(name, "").split(",") if x.strip())


@dataclass(frozen=True)
class ApiKey:
    name: str
    digest: str  # sha256 hex of the secret; the secret itself is never stored


def hash_key(secret: str) -> str:
    return hashlib.sha256(secret.encode("utf-8")).hexdigest()


@lru_cache(maxsize=8)
def parse_api_keys(raw: str) -> tuple[ApiKey, ...]:
    """'name1:secret1,name2:secret2' or bare secrets. Weak keys are rejected at startup."""
    keys: list[ApiKey] = []
    for i, item in enumerate(x.strip() for x in raw.split(",") if x.strip()):
        name, sep, secret = item.partition(":")
        if not sep:
            name, secret = f"key{i + 1}", item
        if len(secret) < MIN_API_KEY_LENGTH:
            raise ConfigError(
                f"API key '{name}' is too short; use at least {MIN_API_KEY_LENGTH} random characters."
            )
        keys.append(ApiKey(name=name, digest=hash_key(secret)))
    return tuple(keys)


@dataclass(frozen=True)
class Settings:
    # ---- input limits
    max_upload_bytes: int = 10 * 1024 * 1024
    max_pages: int = 100
    max_text_chars: int = 1_000_000
    allowed_extensions: tuple[str, ...] = (".pdf", ".txt")
    # A PDF page with fewer non-whitespace characters than this is treated as having no text layer.
    min_chars_per_page: int = 25
    # ---- processing limits
    processing_timeout_s: float = 30.0  # per document (cooperative; hard kill in worker mode)
    fuzzy_label_budget: int = 300  # distinct uncached fuzzy label lookups per document
    # ---- OCR
    ocr_enabled: bool = False
    ocr_dpi: int = 200
    ocr_lang: str = "eng"
    ocr_timeout_s: int = 60  # per page
    ocr_max_pixels: int = 25_000_000  # per rendered page; the DPI is reduced to fit
    ocr_min_dpi: int = 100
    ocr_max_pages: int = 20
    ocr_total_timeout_s: int = 120
    tesseract_cmd: str | None = None
    # ---- optional NLP
    nlp_enabled: bool = False
    spacy_model: str = "en_core_web_sm"
    # Heuristic scores below this value are marked needs_review.
    review_threshold: float = 0.6
    # ---- API deployment
    env: str = "development"  # development | production
    api_keys: tuple[ApiKey, ...] = field(default=(), repr=False)
    rate_limit_per_min: int = 60  # per client; 0 disables
    auth_fail_limit_per_min: int = 10  # failed-auth attempts per client IP; 0 disables
    trust_proxy: bool = False  # honour X-Forwarded-For (only behind a trusted proxy)
    enable_docs: bool = True
    cors_origins: tuple[str, ...] = ()
    hsts: bool = False
    isolation: str = "process"  # process (hard timeout, crash isolation) | inline
    workers: int = 2
    worker_memory_mb: int = 2048  # RLIMIT_AS per worker (POSIX)
    queue_timeout_s: float = 10.0  # wait for a free worker before answering 503
    log_level: str = "INFO"
    log_format: str = "text"  # text | json
    # ---- UI
    api_url: str | None = None  # operator-set only; users cannot choose a target URL
    api_key: str | None = field(default=None, repr=False)  # UI -> API credential
    ui_max_history: int = 10

    @property
    def production(self) -> bool:
        return self.env == "production"

    @property
    def auth_required(self) -> bool:
        return bool(self.api_keys) or self.production


def get_settings() -> Settings:
    """Build settings from the environment on every call (keeps tests easy to isolate)."""
    _load_dotenv_once()
    env = os.environ.get("SHIPINTEL_ENV", "development").strip().lower()
    if env not in {"development", "production"}:
        raise ConfigError("SHIPINTEL_ENV must be 'development' or 'production'.")
    isolation = os.environ.get("SHIPINTEL_ISOLATION", "process").strip().lower()
    if isolation not in {"process", "inline"}:
        raise ConfigError("SHIPINTEL_ISOLATION must be 'process' or 'inline'.")
    log_format = os.environ.get("SHIPINTEL_LOG_FORMAT", "text").strip().lower()
    return Settings(
        max_upload_bytes=_env_int("SHIPINTEL_MAX_UPLOAD_MB", 10, 1) * 1024 * 1024,
        max_pages=_env_int("SHIPINTEL_MAX_PAGES", 100, 1),
        max_text_chars=_env_int("SHIPINTEL_MAX_TEXT_CHARS", 1_000_000, 1000),
        processing_timeout_s=_env_float("SHIPINTEL_PROCESSING_TIMEOUT_S", 30.0),
        fuzzy_label_budget=_env_int("SHIPINTEL_FUZZY_LABEL_BUDGET", 300, 0),
        ocr_enabled=_env_bool("SHIPINTEL_OCR_ENABLED", False),
        ocr_dpi=_env_int("SHIPINTEL_OCR_DPI", 200, 72),
        ocr_lang=os.environ.get("SHIPINTEL_OCR_LANG", "eng"),
        ocr_timeout_s=_env_int("SHIPINTEL_OCR_TIMEOUT_S", 60, 1),
        ocr_max_pixels=_env_int("SHIPINTEL_OCR_MAX_PIXELS", 25_000_000, 1_000_000),
        ocr_max_pages=_env_int("SHIPINTEL_OCR_MAX_PAGES", 20, 1),
        ocr_total_timeout_s=_env_int("SHIPINTEL_OCR_TOTAL_TIMEOUT_S", 120, 1),
        tesseract_cmd=os.environ.get("SHIPINTEL_TESSERACT_CMD") or None,
        nlp_enabled=_env_bool("SHIPINTEL_NLP_ENABLED", False),
        spacy_model=os.environ.get("SHIPINTEL_SPACY_MODEL", "en_core_web_sm"),
        env=env,
        api_keys=parse_api_keys(os.environ.get("SHIPINTEL_API_KEYS", "")),
        rate_limit_per_min=_env_int("SHIPINTEL_RATE_LIMIT_PER_MIN", 60, 0),
        auth_fail_limit_per_min=_env_int("SHIPINTEL_AUTH_FAIL_LIMIT_PER_MIN", 10, 0),
        trust_proxy=_env_bool("SHIPINTEL_TRUST_PROXY", False),
        enable_docs=_env_bool("SHIPINTEL_ENABLE_DOCS", env != "production"),
        cors_origins=_env_list("SHIPINTEL_CORS_ORIGINS"),
        hsts=_env_bool("SHIPINTEL_HSTS", False),
        isolation=isolation,
        workers=_env_int("SHIPINTEL_WORKERS", 2, 1),
        worker_memory_mb=_env_int("SHIPINTEL_WORKER_MEMORY_MB", 2048, 256),
        queue_timeout_s=_env_float("SHIPINTEL_QUEUE_TIMEOUT_S", 10.0),
        log_level=os.environ.get("SHIPINTEL_LOG_LEVEL", "INFO").upper(),
        log_format=log_format if log_format in {"text", "json"} else "text",
        api_url=_validated_url(os.environ.get("SHIPINTEL_API_URL")),
        api_key=os.environ.get("SHIPINTEL_API_KEY") or None,
        ui_max_history=_env_int("SHIPINTEL_UI_MAX_HISTORY", 10, 1),
    )


def _validated_url(url: str | None) -> str | None:
    if not url:
        return None
    if not url.startswith(("http://", "https://")):
        raise ConfigError("SHIPINTEL_API_URL must start with http:// or https://")
    return url


def validate_for_startup(settings: Settings) -> list[str]:
    """Raise ConfigError for unsafe production config; return non-fatal warnings."""
    warnings: list[str] = []
    if settings.production and not settings.api_keys:
        raise ConfigError(
            "SHIPINTEL_ENV=production requires SHIPINTEL_API_KEYS (at least one key of "
            f"{MIN_API_KEY_LENGTH}+ characters)."
        )
    if settings.production and settings.enable_docs:
        warnings.append("API docs are enabled in production (SHIPINTEL_ENABLE_DOCS=true).")
    if not settings.api_keys:
        warnings.append(
            "No API keys configured: the API is OPEN. Bind to localhost only, or set SHIPINTEL_API_KEYS."
        )
    if settings.isolation == "inline":
        warnings.append(
            "SHIPINTEL_ISOLATION=inline: no hard per-request timeout or memory cap; use only for dev/tests."
        )
    return warnings
