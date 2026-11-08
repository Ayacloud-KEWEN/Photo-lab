from __future__ import annotations

import sqlite3
import threading
import time

import pytest

from lumen.core.config import Settings
from lumen.core.errors import ConflictError
from lumen.db.connection import Database
from lumen.tasks import queue
from lumen.tasks.runner import PermanentTaskError, TaskContext, TaskRunner


def _status(conn: sqlite3.Connection, task_id: int) -> str:
    return str(queue.get(conn, task_id)["status"])


def test_enqueue_reuses_active_task(conn: sqlite3.Connection) -> None:
    first = queue.enqueue(conn, "demo")
    assert queue.enqueue(conn, "demo") == first
    assert queue.enqueue(conn, "other") != first
    queue.claim_next(conn)
    assert queue.enqueue(conn, "demo") == first  # still running
    queue.mark_succeeded(conn, first)
    assert queue.enqueue(conn, "demo") != first


def test_claim_respects_priority_and_order(conn: sqlite3.Connection) -> None:
    low = queue.enqueue(conn, "a")
    high = queue.enqueue(conn, "b", priority=20)
    later = queue.enqueue(conn, "c")
    claimed = [queue.claim_next(conn)["id"] for _ in range(3)]  # type: ignore[index]
    assert claimed == [high, low, later]
    assert queue.claim_next(conn) is None
    row = queue.get(conn, high)
    assert (row["status"], row["attempts"]) == ("running", 1)


def test_background_kinds_queue_after_other_work(conn: sqlite3.Connection) -> None:
    from lumen.ai.pipeline import AI_INDEX_TASK
    from lumen.geo.tasks import GEO_TASK
    from lumen.library.common import SCAN_TASK
    from lumen.library.quality import QUALITY_TASK
    from lumen.vlm.pipeline import VLM_TASK

    assert {AI_INDEX_TASK, GEO_TASK, QUALITY_TASK, VLM_TASK} == queue.BACKGROUND_KINDS
    quality = queue.enqueue(conn, QUALITY_TASK)
    ai = queue.enqueue(conn, AI_INDEX_TASK)
    scan = queue.enqueue(conn, SCAN_TASK, storage_root_id=None)
    assert queue.has_higher_pending(conn, queue.BACKGROUND_PRIORITY)
    claimed = [queue.claim_next(conn)["id"] for _ in range(3)]  # type: ignore[index]
    assert claimed == [scan, quality, ai]
    assert not queue.has_higher_pending(conn, queue.BACKGROUND_PRIORITY)


def test_apply_priorities_fixes_tasks_from_earlier_versions(conn: sqlite3.Connection) -> None:
    finished = queue.enqueue(conn, "export_assets", priority=0)
    queue.claim_next(conn)
    queue.mark_succeeded(conn, finished)
    quality = queue.enqueue(conn, "quality_score_assets", priority=0)
    scan = queue.enqueue(conn, "scan_storage_root", priority=0)
    assert queue.apply_priorities(conn) == 1  # only the scan was wrong
    assert queue.get(conn, scan)["priority"] == queue.FOREGROUND_PRIORITY
    assert queue.get(conn, quality)["priority"] == queue.BACKGROUND_PRIORITY
    assert queue.get(conn, finished)["priority"] == 0  # finished tasks are left alone
    assert queue.claim_next(conn)["id"] == scan  # type: ignore[index]
    assert queue.apply_priorities(conn) == 0


def test_failure_is_retried_with_backoff_then_failed(conn: sqlite3.Connection) -> None:
    task_id = queue.enqueue(conn, "flaky")
    for attempt in (1, 2):
        queue.claim_next(conn)
        assert queue.mark_failed(conn, task_id, "boom", retry=True) == "pending"
        row = queue.get(conn, task_id)
        assert row["attempts"] == attempt and row["run_after"] is not None
        assert queue.claim_next(conn) is None  # waiting for backoff
        conn.execute("UPDATE tasks SET run_after = NULL WHERE id = ?", (task_id,))
    queue.claim_next(conn)
    assert queue.mark_failed(conn, task_id, "boom", retry=True) == "failed"
    assert queue.get(conn, task_id)["error"] == "boom"


def test_permanent_failure_is_not_retried(conn: sqlite3.Connection) -> None:
    task_id = queue.enqueue(conn, "x")
    queue.claim_next(conn)
    assert queue.mark_failed(conn, task_id, "offline", retry=False) == "failed"


def test_cancel_and_retry(conn: sqlite3.Connection) -> None:
    pending = queue.enqueue(conn, "a")
    queue.request_cancel(conn, pending)
    assert _status(conn, pending) == "cancelled"

    running = queue.enqueue(conn, "b")
    queue.claim_next(conn)
    queue.request_cancel(conn, running)
    assert _status(conn, running) == "running"
    assert queue.report_progress(conn, running, 1, 10) is False

    with pytest.raises(ConflictError):
        queue.retry(conn, running)
    queue.mark_cancelled(conn, running)
    with pytest.raises(ConflictError):
        queue.request_cancel(conn, running)

    queue.retry(conn, running)
    row = queue.get(conn, running)
    assert (row["status"], row["attempts"], row["cancel_requested"]) == ("pending", 0, 0)


def test_recover_interrupted(conn: sqlite3.Connection) -> None:
    task_id = queue.enqueue(conn, "a")
    queue.claim_next(conn)
    assert queue.recover_interrupted(conn) == 1
    row = queue.get(conn, task_id)
    assert (row["status"], row["attempts"]) == ("pending", 0)


def _wait_for(conn: sqlite3.Connection, task_id: int, statuses: set[str]) -> str:
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        status = _status(conn, task_id)
        if status in statuses:
            return status
        time.sleep(0.02)
    raise AssertionError(f"task stuck in {_status(conn, task_id)}")


def test_runner_executes_handlers(db: Database, settings: Settings) -> None:
    seen: list[dict[str, object]] = []
    gate = threading.Event()

    def ok(ctx: TaskContext) -> None:
        seen.append(ctx.payload)
        ctx.progress(5, 5, force=True)

    def offline(ctx: TaskContext) -> None:
        raise PermanentTaskError("drive offline")

    def slow(ctx: TaskContext) -> None:
        gate.set()
        while True:
            ctx.progress(1, None)
            time.sleep(0.01)

    runner = TaskRunner(db, settings, {"ok": ok, "offline": offline, "slow": slow})
    runner.start()
    try:
        with db.session() as conn:
            ok_id = runner.enqueue("ok", payload={"n": 1})
            assert _wait_for(conn, ok_id, {"succeeded"}) == "succeeded"
            assert queue.get(conn, ok_id)["progress_current"] == 5
            assert seen == [{"n": 1}]

            offline_id = runner.enqueue("offline")
            assert _wait_for(conn, offline_id, {"failed"}) == "failed"

            unknown_id = runner.enqueue("nope")
            assert _wait_for(conn, unknown_id, {"failed"}) == "failed"

            slow_id = runner.enqueue("slow")
            assert gate.wait(5)
            queue.request_cancel(conn, slow_id)
            assert _wait_for(conn, slow_id, {"cancelled"}) == "cancelled"
    finally:
        runner.stop()


def test_runner_shutdown_requeues_running_task(db: Database, settings: Settings) -> None:
    started = threading.Event()

    def endless(ctx: TaskContext) -> None:
        started.set()
        while True:
            ctx.progress(0)
            time.sleep(0.01)

    runner = TaskRunner(db, settings, {"endless": endless})
    runner.start()
    task_id = runner.enqueue("endless")
    assert started.wait(5)
    runner.stop()
    with db.session() as conn:
        row = queue.get(conn, task_id)
        assert (row["status"], row["attempts"]) == ("pending", 0)


def test_background_task_gives_way_to_queued_work(db: Database, settings: Settings) -> None:
    """A long background task (AI analysis…) pauses while a new folder is scanned."""
    order: list[str] = []
    started = threading.Event()
    runs = {"n": 0}

    def background(ctx: TaskContext) -> None:
        runs["n"] += 1
        order.append(f"background-{runs['n']}")
        started.set()
        if runs["n"] > 1:
            return  # resumed after the scan: the remaining work is done
        while True:
            ctx.progress(1, 2)
            time.sleep(0.01)

    def scan(ctx: TaskContext) -> None:
        order.append("scan")

    runner = TaskRunner(db, settings, {"ai_index_assets": background, "scan_storage_root": scan})
    runner.start()
    try:
        with db.session() as conn:
            background_id = runner.enqueue("ai_index_assets")
            assert started.wait(5)
            scan_id = runner.enqueue("scan_storage_root")
            assert _wait_for(conn, scan_id, {"succeeded"}) == "succeeded"
            assert _wait_for(conn, background_id, {"succeeded"}) == "succeeded"
            assert order == ["background-1", "scan", "background-2"]
            assert queue.get(conn, background_id)["attempts"] == 1  # yielding is free
    finally:
        runner.stop()


def test_foreground_tasks_do_not_yield(db: Database, settings: Settings) -> None:
    order: list[str] = []
    started = threading.Event()
    release = threading.Event()

    def ingest(ctx: TaskContext) -> None:
        order.append("ingest")
        started.set()
        while not release.is_set():
            ctx.progress(1, 2)
            time.sleep(0.01)

    def export(ctx: TaskContext) -> None:
        order.append("export")

    runner = TaskRunner(db, settings, {"ingest_storage_root": ingest, "export_assets": export})
    runner.start()
    try:
        with db.session() as conn:
            ingest_id = runner.enqueue("ingest_storage_root")
            assert started.wait(5)
            export_id = runner.enqueue("export_assets")
            time.sleep(1.2)  # a couple of progress reports
            assert _status(conn, ingest_id) == "running"
            release.set()
            assert _wait_for(conn, export_id, {"succeeded"}) == "succeeded"
            assert order == ["ingest", "export"]
    finally:
        runner.stop()
