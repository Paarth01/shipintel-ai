"""Minimal in-process metrics in Prometheus text format (no extra dependency)."""

from __future__ import annotations

import threading
from collections import defaultdict

KNOWN_PATHS = {"/extract", "/health", "/ready", "/metrics", "/docs", "/openapi.json", "/redoc"}


class Metrics:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.requests: dict[tuple[str, str, int], int] = defaultdict(int)
        self.duration_sum: dict[str, float] = defaultdict(float)
        self.duration_count: dict[str, int] = defaultdict(int)
        self.events: dict[str, int] = defaultdict(int)  # auth_failures, rate_limited, ...
        self.extract_by_status: dict[str, int] = defaultdict(int)

    def reset(self) -> None:
        with self._lock:
            for d in (
                self.requests,
                self.duration_sum,
                self.duration_count,
                self.events,
                self.extract_by_status,
            ):
                d.clear()

    def observe_request(self, method: str, path: str, status: int, seconds: float) -> None:
        path = path if path in KNOWN_PATHS else "other"  # bounded label cardinality
        with self._lock:
            self.requests[(method, path, status)] += 1
            self.duration_sum[path] += seconds
            self.duration_count[path] += 1

    def event(self, name: str, n: int = 1) -> None:
        with self._lock:
            self.events[name] += n

    def extract_result(self, status: str) -> None:
        with self._lock:
            self.extract_by_status[status] += 1

    def render(
        self, pool_stats: dict[str, int] | None = None, healthy_workers: int | None = None
    ) -> str:
        out = ["# TYPE shipintel_http_requests_total counter"]
        with self._lock:
            for (m, p, s), n in sorted(self.requests.items()):
                out.append(
                    f'shipintel_http_requests_total{{method="{m}",path="{p}",status="{s}"}} {n}'
                )
            out.append("# TYPE shipintel_http_request_duration_seconds summary")
            for p in sorted(self.duration_count):
                out.append(
                    f'shipintel_http_request_duration_seconds_sum{{path="{p}"}} {self.duration_sum[p]:.6f}'
                )
                out.append(
                    f'shipintel_http_request_duration_seconds_count{{path="{p}"}} {self.duration_count[p]}'
                )
            out.append("# TYPE shipintel_events_total counter")
            for name, n in sorted(self.events.items()):
                out.append(f'shipintel_events_total{{event="{name}"}} {n}')
            out.append("# TYPE shipintel_extractions_total counter")
            for status, n in sorted(self.extract_by_status.items()):
                out.append(f'shipintel_extractions_total{{status="{status}"}} {n}')
        for name, n in sorted((pool_stats or {}).items()):
            out.append(f'shipintel_worker_events_total{{event="{name}"}} {n}')
        if healthy_workers is not None:
            out.append("# TYPE shipintel_workers_healthy gauge")
            out.append(f"shipintel_workers_healthy {healthy_workers}")
        return "\n".join(out) + "\n"


METRICS = Metrics()
