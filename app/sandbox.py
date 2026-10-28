"""Process-isolated extraction workers: hard timeouts, memory caps, crash isolation, backpressure.

Why processes: a regex or a native-library call (PyMuPDF, Tesseract) cannot be interrupted from a
thread, and Python's `re` holds the GIL, so one pathological document could stall the whole server.
Each job runs in a pre-started worker process that is KILLED on timeout and replaced; a segfault in
a native parser only costs that one job. Workers are warm (modules imported at start), so isolation
adds ~1 ms per request, not a process start.

    pool = WorkerPool(size=2, memory_mb=2048, queue_timeout_s=10)
    result = pool.run("app.worker_tasks:extract", (settings, name, data, ocr, nlp, True), timeout_s=35)

Errors raised for the caller: ProcessingTimeoutError (job killed), DocumentProcessingFailedError
(worker crashed or hit its memory cap), ServerBusyError (no free worker within `queue_timeout_s`),
plus any typed ShipIntelError raised by the job itself (re-created in the parent).
"""

from __future__ import annotations

import importlib
import logging
import multiprocessing as mp
import queue
import threading
from dataclasses import dataclass
from multiprocessing.connection import Connection
from multiprocessing.process import BaseProcess
from typing import Any

from app.errors import (
    ERROR_TYPES,
    DocumentProcessingFailedError,
    ProcessingTimeoutError,
    ServerBusyError,
    ShipIntelError,
)

log = logging.getLogger("shipintel.sandbox")
_ALLOWED_PREFIXES = ("app.", "tests.")


def _resolve(target: str):
    module, _, func = target.partition(":")
    if not module.startswith(_ALLOWED_PREFIXES) or not func:
        raise ValueError("target not allowed")
    return getattr(importlib.import_module(module), func)


def _limit_memory(memory_mb: int) -> None:
    try:
        import resource  # POSIX only

        limit = memory_mb * 1024 * 1024
        resource.setrlimit(resource.RLIMIT_AS, (limit, limit))
    except Exception:  # Windows or restricted environment: no cap, still process-isolated
        pass


def _worker_main(conn: Connection, memory_mb: int, warm: bool) -> None:
    if warm:
        import app.pipeline  # noqa: F401  (import cost paid once, at worker start)
    _limit_memory(memory_mb)
    while True:
        try:
            job = conn.recv()
        except (EOFError, OSError):
            return
        if job is None:
            return
        target, args = job
        try:
            out = _resolve(target)(*args)
            conn.send(("ok", out))
        except ShipIntelError as exc:
            conn.send(("typed", type(exc).__name__, exc.message))
        except MemoryError:
            conn.send(
                ("typed", "ResourceLimitError", "The document needs more memory than allowed.")
            )
        except BaseException as exc:  # noqa: BLE001 - report the TYPE only, never document content
            conn.send(("crash", type(exc).__name__))


@dataclass(eq=False)  # identity hashing: workers live in a set
class _Worker:
    process: BaseProcess
    conn: Connection

    def alive(self) -> bool:
        return self.process.is_alive()

    def kill(self) -> None:
        try:
            self.process.kill()
            self.process.join(timeout=5)
        finally:
            try:
                self.conn.close()
            except OSError:
                pass


class WorkerPool:
    def __init__(self, size: int, memory_mb: int, queue_timeout_s: float, warm: bool = True):
        self.size, self.memory_mb, self.queue_timeout_s, self.warm = (
            size,
            memory_mb,
            queue_timeout_s,
            warm,
        )
        self._ctx = mp.get_context(
            "spawn"
        )  # same behaviour on Linux/macOS/Windows; no fork+threads hazards
        self._idle: queue.Queue[_Worker] = queue.Queue()
        self._lock = threading.Lock()
        self._workers: set[_Worker] = set()
        self._closed = False
        self.stats = {"timeouts": 0, "crashes": 0, "busy": 0, "replaced": 0, "dead_idle": 0}

    # ------------------------------------------------------------------ lifecycle
    def _spawn(self) -> _Worker:
        parent, child = self._ctx.Pipe()
        proc = self._ctx.Process(
            target=_worker_main, args=(child, self.memory_mb, self.warm), daemon=True
        )
        proc.start()
        child.close()
        worker = _Worker(proc, parent)
        with self._lock:
            self._workers.add(worker)
        return worker

    def start(self) -> WorkerPool:
        threads = [
            threading.Thread(target=lambda: self._idle.put(self._spawn())) for _ in range(self.size)
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        return self

    def close(self) -> None:
        self._closed = True
        with self._lock:
            workers, self._workers = list(self._workers), set()
        for w in workers:
            try:
                w.conn.send(None)
            except (OSError, ValueError):
                pass
            w.process.join(timeout=2)
            if w.process.is_alive():
                w.kill()

    def healthy_workers(self) -> int:
        with self._lock:
            return sum(1 for w in self._workers if w.alive())

    def _replace_async(self, dead: _Worker) -> None:
        with self._lock:
            self._workers.discard(dead)
        self.stats["replaced"] += 1

        def work() -> None:
            if self._closed:
                return
            try:
                self._idle.put(self._spawn())
            except Exception:  # noqa: BLE001
                log.error("could not replace a worker; pool capacity reduced")

        threading.Thread(target=work, daemon=True).start()

    # ------------------------------------------------------------------ jobs
    def _discard(self, worker: _Worker) -> None:
        worker.kill()
        self._replace_async(worker)

    def _acquire_and_send(self, target: str, args: tuple) -> _Worker:
        """Get a LIVE worker and hand it the job. A worker that died while idle (OOM kill, operator
        `kill -9`) is discarded and another is used: the job has not started, so retrying is safe.
        (A crash AFTER the job was sent is never retried: a poison document would kill every worker.)
        """
        for _ in range(self.size + 2):
            try:
                worker = self._idle.get(timeout=self.queue_timeout_s)
            except queue.Empty:
                self.stats["busy"] += 1
                raise ServerBusyError("All workers are busy; retry shortly.") from None
            if not worker.alive():
                self.stats["dead_idle"] += 1
                self._discard(worker)
                continue
            try:
                worker.conn.send((target, args))
                return worker
            except (OSError, ValueError):  # pipe broke before the job was delivered
                self.stats["dead_idle"] += 1
                self._discard(worker)
        self.stats["busy"] += 1
        raise ServerBusyError("No healthy worker is available; retry shortly.")

    def run(self, target: str, args: tuple, timeout_s: float) -> Any:
        if self._closed:
            raise ServerBusyError("The service is shutting down.")
        worker = self._acquire_and_send(target, args)
        healthy = True
        try:
            if not worker.conn.poll(timeout_s):
                healthy = False
                self.stats["timeouts"] += 1
                worker.kill()
                raise ProcessingTimeoutError(
                    f"Processing exceeded the {timeout_s:g} s limit and was stopped."
                )
            message = worker.conn.recv()
        except (EOFError, OSError, BrokenPipeError):
            healthy = False
            self.stats["crashes"] += 1
            worker.kill()
            raise DocumentProcessingFailedError(
                "The document could not be processed safely (the worker was terminated)."
            ) from None
        finally:
            if healthy:
                self._idle.put(worker)
            else:
                self._replace_async(worker)
        kind = message[0]
        if kind == "ok":
            return message[1]
        if kind == "typed":
            raise ERROR_TYPES.get(message[1], ShipIntelError)(message[2])
        log.error("worker raised %s", message[1])
        raise DocumentProcessingFailedError("The document could not be processed.")


class InlinePool:
    """No isolation: runs the job in the calling thread. For tests/development only."""

    size = 1
    stats: dict[str, int] = {"timeouts": 0, "crashes": 0, "busy": 0, "replaced": 0, "dead_idle": 0}

    def start(self) -> InlinePool:
        return self

    def close(self) -> None:
        pass

    def healthy_workers(self) -> int:
        return 1

    def run(self, target: str, args: tuple, timeout_s: float) -> Any:  # noqa: ARG002
        return _resolve(target)(*args)


_POOL: WorkerPool | InlinePool | None = None
_POOL_KEY: tuple | None = None
_POOL_LOCK = threading.Lock()


def get_pool(settings) -> WorkerPool | InlinePool:
    """Process-wide pool (lazy: also works under test clients that do not run lifespan events)."""
    global _POOL, _POOL_KEY
    key = (
        settings.isolation,
        settings.workers,
        settings.worker_memory_mb,
        settings.queue_timeout_s,
    )
    with _POOL_LOCK:
        if _POOL is not None and _POOL_KEY == key:
            return _POOL
        if _POOL is not None:
            _POOL.close()
        if settings.isolation == "inline":
            _POOL = InlinePool()
        else:
            _POOL = WorkerPool(
                settings.workers, settings.worker_memory_mb, settings.queue_timeout_s
            ).start()
        _POOL_KEY = key
        return _POOL


def shutdown_pool() -> None:
    global _POOL, _POOL_KEY
    with _POOL_LOCK:
        if _POOL is not None:
            _POOL.close()
        _POOL, _POOL_KEY = None, None
