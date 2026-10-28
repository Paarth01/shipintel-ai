"""Process isolation: hard timeout, crash containment, memory cap, backpressure, recovery."""

from __future__ import annotations

import sys
import threading
import time

import pytest
from fastapi.testclient import TestClient

from app.errors import (
    DocumentProcessingFailedError,
    ProcessingTimeoutError,
    ResourceLimitError,
    ServerBusyError,
    TextTooLargeError,
)
from app.sandbox import WorkerPool
from tests.conftest import SAMPLE_BL


@pytest.fixture(scope="module")
def pool():
    p = WorkerPool(size=2, memory_mb=2048, queue_timeout_s=3).start()
    time.sleep(1.0)  # let the warm imports finish
    yield p
    p.close()


def wait_healthy(pool, n, seconds=20):
    end = time.time() + seconds
    while time.time() < end:
        if pool.healthy_workers() >= n and pool._idle.qsize() >= n:
            return True
        time.sleep(0.1)
    return False


def test_jobs_run_in_a_different_process(pool):
    import os

    assert pool.run("tests.helpers:getpid", (None,), 10) != os.getpid()
    assert pool.run("tests.helpers:echo", ("hi",), 10) == "hi"


def test_hard_timeout_kills_a_hung_job_and_the_pool_recovers(pool):
    start = time.perf_counter()
    with pytest.raises(ProcessingTimeoutError):
        pool.run("tests.helpers:sleep_forever", (None,), 1)
    assert time.perf_counter() - start < 4
    assert wait_healthy(pool, 2)
    assert pool.run("tests.helpers:echo", ("again",), 10) == "again"


def test_a_native_crash_is_contained(pool):
    with pytest.raises(DocumentProcessingFailedError):
        pool.run("tests.helpers:crash_hard", (None,), 10)
    assert wait_healthy(pool, 2)
    assert pool.run("tests.helpers:echo", (1,), 10) == 1


def test_typed_errors_cross_the_process_boundary(pool):
    with pytest.raises(TextTooLargeError) as exc:
        pool.run("tests.helpers:raise_typed", (None,), 10)
    assert exc.value.http_status == 413


def test_unexpected_exception_messages_never_leak(pool):
    with pytest.raises(DocumentProcessingFailedError) as exc:
        pool.run("tests.helpers:raise_unexpected", (None,), 10)
    assert "secret" not in exc.value.message and "secret" not in str(exc.value)


@pytest.mark.skipif(
    not sys.platform.startswith("linux"), reason="RLIMIT_AS enforcement is Linux-specific"
)
def test_memory_cap_turns_runaway_allocation_into_a_clean_error(pool):
    with pytest.raises(ResourceLimitError):
        pool.run("tests.helpers:allocate", (3000,), 20)


def test_disallowed_job_targets_are_refused(pool):
    with pytest.raises(DocumentProcessingFailedError):
        pool.run("os:system", ("echo pwned",), 10)


def test_busy_pool_answers_503_instead_of_queueing_forever():
    p = WorkerPool(size=1, memory_mb=2048, queue_timeout_s=0.5).start()
    outcome: list[str] = []

    def occupy():
        try:
            p.run("tests.helpers:sleep_forever", (None,), 2)
        except ProcessingTimeoutError:
            outcome.append("timed out as expected")

    try:
        time.sleep(1.0)
        t = threading.Thread(target=occupy)
        t.start()
        time.sleep(0.3)
        with pytest.raises(ServerBusyError):
            p.run("tests.helpers:echo", (1,), 5)
        t.join()
        assert p.stats["busy"] == 1 and outcome == ["timed out as expected"]
    finally:
        p.close()


def test_real_extraction_through_the_api_in_process_mode(monkeypatch):
    monkeypatch.setenv("SHIPINTEL_ISOLATION", "process")
    monkeypatch.setenv("SHIPINTEL_WORKERS", "1")
    from app.api import create_app

    with TestClient(create_app()) as c:  # runs lifespan: pre-starts the workers
        assert c.get("/ready").json() == {
            "status": "ready",
            "workers": 1,
            "isolation": "process",
            "ocr_enabled": False,
            "ocr_available": False,
        }
        r = c.post("/extract", files={"file": ("bl.txt", SAMPLE_BL.encode())})
        assert (
            r.status_code == 200 and r.json()["fields"]["vessel_name"]["value"] == "NORDIC AURORA"
        )
        bad = c.post("/extract", files={"file": ("a.txt", b"   \n  ")})
        assert (
            bad.status_code == 422 and bad.json()["error"]["code"] == "NO_TEXT_FOUND"
        )  # typed error survives


def test_api_timeout_returns_504_and_server_keeps_serving(monkeypatch):
    monkeypatch.setenv("SHIPINTEL_ISOLATION", "process")
    monkeypatch.setenv("SHIPINTEL_WORKERS", "1")
    monkeypatch.setenv(
        "SHIPINTEL_PROCESSING_TIMEOUT_S", "0.001"
    )  # cooperative deadline fires inside the worker
    from app.api import create_app

    with TestClient(create_app()) as c:
        r = c.post("/extract", files={"file": ("big.txt", ("Vessel: MV A ONE\n" * 30000).encode())})
        assert r.status_code == 504 and r.json()["error"]["code"] == "PROCESSING_TIMEOUT"
        monkeypatch.setenv("SHIPINTEL_PROCESSING_TIMEOUT_S", "30")
        assert c.post("/extract", files={"file": ("bl.txt", SAMPLE_BL.encode())}).status_code == 200


def test_a_worker_that_died_while_idle_is_replaced_transparently(pool):
    """Regression (found by live SIGKILL test): the next request used to fail with 422."""
    assert wait_healthy(pool, 2)
    victim = next(iter(pool._workers))
    victim.process.kill()
    victim.process.join(timeout=5)
    # several requests right after the kill: none may fail
    for i in range(4):
        assert pool.run("tests.helpers:echo", (i,), 10) == i
    assert pool.stats["dead_idle"] >= 1
    assert wait_healthy(pool, 2)


def test_a_crash_during_a_job_is_not_retried(pool):
    """A poison document must not be replayed on another worker."""
    before = pool.stats["crashes"]
    with pytest.raises(DocumentProcessingFailedError):
        pool.run("tests.helpers:crash_hard", (None,), 10)
    assert pool.stats["crashes"] == before + 1  # exactly one worker lost, not several
    assert wait_healthy(pool, 2)
