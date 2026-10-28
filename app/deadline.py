"""Cooperative processing deadline and a bounded work budget for fuzzy matching.

These cap the cost of pathological documents in every deployment mode (UI, library, API). The API
additionally runs extraction in an isolated worker process with a hard kill (see app/sandbox.py),
which also covers time spent inside a single regex or native call that cannot check a deadline.
"""

from __future__ import annotations

import time

from app.errors import ProcessingTimeoutError


class Deadline:
    def __init__(self, seconds: float | None):
        self.limit = seconds
        self.start = time.monotonic()

    def remaining(self) -> float | None:
        return None if self.limit is None else self.limit - (time.monotonic() - self.start)

    def check(self) -> None:
        left = self.remaining()
        if left is not None and left <= 0:
            raise ProcessingTimeoutError(
                f"Processing exceeded the {self.limit:g} s limit for a single document."
            )


class FuzzyBudget:
    """Limits expensive difflib lookups per document (distinct, uncached label spellings)."""

    def __init__(self, limit: int):
        self.left = limit

    def take(self) -> bool:
        if self.left <= 0:
            return False
        self.left -= 1
        return True
