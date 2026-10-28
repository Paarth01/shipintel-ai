"""Tiny HTTP client so the UI can call the FastAPI service instead of the in-process pipeline."""

from __future__ import annotations

import httpx

from app.errors import ShipIntelError
from app.schemas import ExtractionResult


class APIError(ShipIntelError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def extract_via_api(
    base_url: str,
    filename: str,
    data: bytes,
    ocr: bool | None = None,
    nlp: bool | None = None,
    client: httpx.Client | None = None,
    timeout: float = 120.0,
    api_key: str | None = None,
) -> ExtractionResult:
    params = {k: str(v).lower() for k, v in (("ocr", ocr), ("nlp", nlp)) if v is not None}
    owns = client is None
    client = client or httpx.Client(timeout=timeout)
    url = base_url.rstrip("/") + "/extract" if owns else "/extract"
    try:
        headers = {"X-API-Key": api_key} if api_key else None
        resp = client.post(url, files={"file": (filename, data)}, params=params, headers=headers)
    except httpx.HTTPError as exc:
        raise APIError(
            "API_UNREACHABLE", f"Could not reach the API at {base_url}: {type(exc).__name__}"
        ) from None
    finally:
        if owns:
            client.close()
    if resp.status_code != 200:
        try:
            err = resp.json()["error"]
            raise APIError(err["code"], err["message"])
        except (ValueError, KeyError, TypeError):
            raise APIError("API_ERROR", f"The API returned HTTP {resp.status_code}.") from None
    return ExtractionResult.model_validate(resp.json())
