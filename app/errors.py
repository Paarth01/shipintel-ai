"""Typed errors with stable codes. The API maps them to HTTP responses; the UI shows `message`."""

from __future__ import annotations


class ShipIntelError(Exception):
    code = "INTERNAL_ERROR"
    http_status = 500

    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


class EmptyFileError(ShipIntelError):
    code, http_status = "EMPTY_FILE", 400


class UnsupportedFileTypeError(ShipIntelError):
    code, http_status = "UNSUPPORTED_FILE_TYPE", 415


class FileTooLargeError(ShipIntelError):
    code, http_status = "FILE_TOO_LARGE", 413


class TooManyPagesError(ShipIntelError):
    code, http_status = "TOO_MANY_PAGES", 413


class UnreadableDocumentError(ShipIntelError):
    code, http_status = "UNREADABLE_DOCUMENT", 422


class EncryptedPDFError(ShipIntelError):
    code, http_status = "PDF_ENCRYPTED", 422


class ScannedPDFError(ShipIntelError):
    code, http_status = "SCANNED_PDF_NO_TEXT", 422


class NoTextError(ShipIntelError):
    code, http_status = "NO_TEXT_FOUND", 422


class OCRUnavailableError(ShipIntelError):
    code, http_status = "OCR_UNAVAILABLE", 503


class TextTooLargeError(ShipIntelError):
    code, http_status = "TEXT_TOO_LARGE", 413


class PageTooLargeError(ShipIntelError):
    code, http_status = "PAGE_TOO_LARGE", 413


class ProcessingTimeoutError(ShipIntelError):
    code, http_status = "PROCESSING_TIMEOUT", 504


class ResourceLimitError(ShipIntelError):
    code, http_status = "RESOURCE_LIMIT_EXCEEDED", 413


class DocumentProcessingFailedError(ShipIntelError):
    """The isolated worker crashed on this document (e.g. a native-parser fault)."""

    code, http_status = "DOCUMENT_PROCESSING_FAILED", 422


class ServerBusyError(ShipIntelError):
    code, http_status = "SERVER_BUSY", 503


class FeatureDisabledError(ShipIntelError):
    code, http_status = "FEATURE_DISABLED", 403


class UnauthorizedError(ShipIntelError):
    code, http_status = "UNAUTHORIZED", 401


class RateLimitedError(ShipIntelError):
    code, http_status = "RATE_LIMITED", 429


class RequestTooLargeError(ShipIntelError):
    code, http_status = "FILE_TOO_LARGE", 413


class ConfigError(Exception):
    """Invalid or unsafe configuration; raised at startup, never per request."""


ERROR_TYPES: dict[str, type[ShipIntelError]] = {
    cls.__name__: cls for cls in ShipIntelError.__subclasses__()
} | {"ShipIntelError": ShipIntelError}
