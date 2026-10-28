"""Structured logging with request IDs. Never logs document text or extracted values."""

from __future__ import annotations

import contextvars
import json
import logging
import sys
import time
import traceback

request_id_var: contextvars.ContextVar[str] = contextvars.ContextVar("request_id", default="-")
_CONFIGURED = False


class _RequestIdFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = request_id_var.get()
        return True


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(record.created))
            + f".{int(record.msecs):03d}Z",
            "level": record.levelname,
            "logger": record.name,
            "request_id": getattr(record, "request_id", "-"),
            "message": record.getMessage(),
        }
        for key in ("method", "path", "status", "duration_ms", "client", "principal", "event"):
            if hasattr(record, key):
                payload[key] = getattr(record, key)
        if record.exc_info and record.exc_info[0] is not None:
            # exception TYPE and stack frames only - messages can echo document content
            payload["exc_type"] = record.exc_info[0].__name__
            payload["stack"] = "".join(traceback.format_tb(record.exc_info[2]))[-2000:]
        return json.dumps(payload, ensure_ascii=False)


class TextFormatter(logging.Formatter):
    def formatException(self, ei) -> str:  # noqa: N802 (stdlib override)
        """Exception TYPE and stack frames only: the default would append the message, which can
        echo document text."""
        return ("".join(traceback.format_tb(ei[2]))[-2000:] + str(ei[0].__name__)).strip()

    def format(self, record: logging.LogRecord) -> str:
        base = super().format(record)
        extras = " ".join(
            f"{k}={getattr(record, k)}"
            for k in ("method", "path", "status", "duration_ms", "client", "principal")
            if hasattr(record, k)
        )
        if extras:
            base += " " + extras
        if record.exc_info and record.exc_info[0] is not None:
            base += f" [exc_type={record.exc_info[0].__name__}]"
        return base


def setup_logging(level: str = "INFO", fmt: str = "text") -> None:
    """Idempotent. Replaces handlers on the 'shipintel' logger tree only."""
    global _CONFIGURED
    logger = logging.getLogger("shipintel")
    for h in list(logger.handlers):
        logger.removeHandler(h)
    handler = logging.StreamHandler(sys.stderr)
    handler.addFilter(_RequestIdFilter())
    handler.setFormatter(
        JsonFormatter()
        if fmt == "json"
        else TextFormatter("%(asctime)s %(levelname)s %(name)s [%(request_id)s] %(message)s")
    )
    logger.addHandler(handler)
    logger.setLevel(getattr(logging, level, logging.INFO))
    logger.propagate = False
    _CONFIGURED = True
