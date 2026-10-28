"""Authentication, rate limiting and server-side feature policy for the API."""

from __future__ import annotations

import hmac
import threading
import time
from collections import deque

from app.config import ApiKey, Settings, hash_key
from app.errors import FeatureDisabledError


def extract_presented_key(headers: dict[str, str]) -> str | None:
    """API key from `X-API-Key` or `Authorization: Bearer <key>` (header names lower-cased)."""
    key = headers.get("x-api-key")
    if key:
        return key.strip()
    auth = headers.get("authorization", "")
    scheme, _, token = auth.partition(" ")
    if scheme.lower() == "bearer" and token.strip():
        return token.strip()
    return None


def authenticate(settings: Settings, presented: str | None) -> ApiKey | None:
    """Constant-time check against the configured key digests (never short-circuits on a match)."""
    if not presented or len(presented) > 512:
        return None
    digest = hash_key(presented)
    matched: ApiKey | None = None
    for key in settings.api_keys:
        if hmac.compare_digest(digest, key.digest):
            matched = key
    return matched


def client_ip(headers: dict[str, str], peer: str | None, trust_proxy: bool) -> str:
    """Peer address, or (only when a trusted proxy is configured) the rightmost X-Forwarded-For hop."""
    if trust_proxy:
        parts = [p.strip() for p in headers.get("x-forwarded-for", "").split(",") if p.strip()]
        if parts:
            return parts[-1][:64]
    return (peer or "unknown")[:64]


class RateLimiter:
    """Sliding-window limiter (in-process, per instance). Bounded memory: at most `max_keys` clients.

    For several API replicas use a shared limiter at the gateway; this guards a single instance.
    """

    def __init__(self, max_keys: int = 10_000, window_s: float = 60.0):
        self._hits: dict[str, deque[float]] = {}
        self._lock = threading.Lock()
        self.max_keys, self.window_s = max_keys, window_s

    def reset(self) -> None:
        with self._lock:
            self._hits.clear()

    def check(self, key: str, limit: int, now: float | None = None) -> tuple[bool, int]:
        """Record a hit. Returns (allowed, retry_after_seconds)."""
        if limit <= 0:
            return True, 0
        now = time.monotonic() if now is None else now
        with self._lock:
            q = self._hits.setdefault(key, deque())
            cutoff = now - self.window_s
            while q and q[0] <= cutoff:
                q.popleft()
            if len(q) >= limit:
                return False, max(1, int(q[0] + self.window_s - now) + 1)
            q.append(now)
            if len(self._hits) > self.max_keys:
                self._evict(cutoff)
            return True, 0

    def peek_blocked(self, key: str, limit: int, now: float | None = None) -> tuple[bool, int]:
        """Is `key` already at its limit? Does not record a hit."""
        if limit <= 0:
            return False, 0
        now = time.monotonic() if now is None else now
        with self._lock:
            q = self._hits.get(key)
            if not q:
                return False, 0
            cutoff = now - self.window_s
            while q and q[0] <= cutoff:
                q.popleft()
            if len(q) >= limit:
                return True, max(1, int(q[0] + self.window_s - now) + 1)
            return False, 0

    def _evict(self, cutoff: float) -> None:
        for k in [k for k, q in self._hits.items() if not q or q[-1] <= cutoff]:
            del self._hits[k]
        if len(self._hits) > self.max_keys:  # still too many: drop the oldest tenth
            oldest = sorted(self._hits, key=lambda k: self._hits[k][-1])[: self.max_keys // 10 + 1]
            for k in oldest:
                del self._hits[k]


def resolve_feature(name: str, server_enabled: bool, requested: bool | None) -> bool:
    """Server policy decides. A client may turn a feature OFF for its request, never ON.

    requested=None -> server setting; requested=False -> off; requested=True -> only if the
    operator enabled it, otherwise 403 FEATURE_DISABLED.
    """
    if requested is None:
        return server_enabled
    if requested and not server_enabled:
        raise FeatureDisabledError(f"{name} is disabled on this server.")
    return requested
