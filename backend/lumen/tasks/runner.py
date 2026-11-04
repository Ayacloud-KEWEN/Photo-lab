"""Background execution of queued tasks."""

from __future__ import annotations

import json
import logging
import sqlite3
import threading
import time
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any

from lumen.core.config import Settings
from lumen.db.connection import Database
from lumen.tasks import queue

logger = logging.getLogger(__name__)

PROGRESS_INTERVAL_S = 0.5
IDLE_POLL_S = 2.0


class RunnerBusyError(Exception):
    """The runner could not be paused: a task did not stop in time."""


class TaskCancelled(Exception):
    """The user cancelled the task (or its storage root was removed)."""


class TaskInterrupted(Exception):
    """The application is shutting down; the task resumes on next start."""


class PermanentTaskError(Exception):
    """A failure that retrying cannot fix (e.g. the drive is disconnected)."""


@dataclass
class TaskContext:
    conn: sqlite3.Connection
    settings: Settings
    task_id: int
    kind: str
    storage_root_id: int | None
    payload: dict[str, Any]
    stop_event: threading.Event
    enqueue: Callable[..., int]
    _last_report: float = field(default=0.0)
    _current: int = field(default=0)
    _total: int | None = field(default=None)

    def progress(self, current: int, total: int | None = None, *, force: bool = False) -> None:
        """Record progress (throttled) and stop the handler if cancelled or shutting down."""
        self._current, self._total = current, total
        now = time.monotonic()
        if force or now - self._last_report >= PROGRESS_INTERVAL_S:
            self._last_report = now
            if not queue.report_progress(self.conn, self.task_id, current, total):
                raise TaskCancelled()
        if self.stop_event.is_set():
            raise TaskInterrupted()

    def check(self) -> None:
        self.progress(self._current, self._total)

    def should_stop(self) -> bool:
        """Cheap check for tight loops (does not hit the database)."""
        return self.stop_event.is_set()


# A handler may return a JSON-serialisable dict: the task's result.
Handler = Callable[[TaskContext], object]


class TaskRunner:
    """Runs one task at a time on a background thread.

    Handlers may parallelize internally (media ingestion does).
    """

    def __init__(self, db: Database, settings: Settings, handlers: Mapping[str, Handler]) -> None:
        self._db = db
        self._settings = settings
        self._handlers = dict(handlers)
        self._wake = threading.Event()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        with self._db.session() as conn:
            recovered = queue.recover_interrupted(conn)
        if recovered:
            logger.info("requeued interrupted tasks", extra={"count": recovered})
        self._thread = threading.Thread(target=self._loop, name="task-runner", daemon=True)
        self._thread.start()

    def wake(self) -> None:
        self._wake.set()

    def stop(self, timeout: float = 15.0) -> None:
        self._stop.set()
        self._wake.set()
        if self._thread is not None:
            self._thread.join(timeout)
            if self._thread.is_alive():
                logger.warning("task runner did not stop in time")

    @contextmanager
    def paused(self, timeout: float = 15.0) -> Iterator[None]:
        """Run a block with no task running (the running one goes back to the queue)."""
        self.stop(timeout)
        if self._thread is not None and self._thread.is_alive():
            # Let it carry on rather than leave the queue without a runner.
            self._stop.clear()
            raise RunnerBusyError("a background task is still running")
        try:
            yield
        finally:
            self._stop = threading.Event()
            self._wake.clear()
            self.start()

    def enqueue(self, kind: str, **kwargs: Any) -> int:
        with self._db.session() as conn:
            task_id = queue.enqueue(conn, kind, **kwargs)
        self.wake()
        return task_id

    def _loop(self) -> None:
        with self._db.session() as conn:
            while not self._stop.is_set():
                try:
                    task = queue.claim_next(conn)
                except sqlite3.Error:
                    logger.exception("could not claim task")
                    task = None
                if task is None:
                    self._wake.wait(IDLE_POLL_S)
                    self._wake.clear()
                    continue
                self._run(conn, task)

    def _run(self, conn: sqlite3.Connection, task: sqlite3.Row) -> None:
        task_id, kind = int(task["id"]), str(task["kind"])
        log = {"task_id": task_id, "kind": kind, "storage_root_id": task["storage_root_id"]}
        handler = self._handlers.get(kind)
        if handler is None:
            queue.mark_failed(conn, task_id, f"Unknown task kind: {kind}", retry=False)
            logger.error("unknown task kind", extra=log)
            return

        ctx = TaskContext(
            conn=conn,
            settings=self._settings,
            task_id=task_id,
            kind=kind,
            storage_root_id=task["storage_root_id"],
            payload=json.loads(task["payload"] or "{}"),
            stop_event=self._stop,
            enqueue=self.enqueue,
        )
        started = time.monotonic()
        logger.info("task started", extra={**log, "attempt": task["attempts"]})
        try:
            outcome = handler(ctx)
        except TaskCancelled:
            queue.mark_cancelled(conn, task_id)
            logger.info("task cancelled", extra=log)
        except TaskInterrupted:
            queue.mark_interrupted(conn, task_id)
            logger.info("task interrupted by shutdown", extra=log)
        except PermanentTaskError as exc:
            queue.mark_failed(conn, task_id, str(exc), retry=False)
            logger.warning("task failed", extra={**log, "error": str(exc)})
        except Exception as exc:
            outcome = queue.mark_failed(conn, task_id, f"{type(exc).__name__}: {exc}", retry=True)
            logger.exception("task error", extra={**log, "outcome": outcome})
        else:
            queue.mark_succeeded(conn, task_id, outcome if isinstance(outcome, dict) else None)
            logger.info(
                "task succeeded",
                extra={**log, "duration_s": round(time.monotonic() - started, 2)},
            )
