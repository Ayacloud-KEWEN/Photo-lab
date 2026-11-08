"""Task queue operations on the ``tasks`` table.

Lifecycle::

    pending ──claim──▶ running ──▶ succeeded
       ▲                 │ ├────▶ failed     (attempts exhausted / permanent error)
       │                 │ └────▶ cancelled  (cancel requested)
       └──retry/interrupt┘
"""

from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime, timedelta
from typing import Any

from lumen.core.errors import ConflictError, NotFoundError
from lumen.db.connection import transaction, utc_now

ACTIVE_STATUSES = ("pending", "running")
RETRY_BASE_DELAY = timedelta(seconds=10)

# Work derived from imported media (ADR-030): it picks up where it stopped, so it runs
# after anything else and gives way when other work is queued (scanning a new folder,
# an export…). Kept as strings: the handlers import this module.
BACKGROUND_KINDS = frozenset(
    {"geo_locate_assets", "quality_score_assets", "ai_index_assets", "vlm_describe_assets"}
)
BACKGROUND_PRIORITY = 0
FOREGROUND_PRIORITY = 10


def priority_for(kind: str) -> int:
    return BACKGROUND_PRIORITY if kind in BACKGROUND_KINDS else FOREGROUND_PRIORITY


def _later(delay: timedelta) -> str:
    return (datetime.now(UTC) + delay).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def get(conn: sqlite3.Connection, task_id: int) -> sqlite3.Row:
    row: sqlite3.Row | None = conn.execute(
        "SELECT * FROM tasks WHERE id = ?", (task_id,)
    ).fetchone()
    if row is None:
        raise NotFoundError("Task not found", details={"id": task_id})
    return row


def enqueue(
    conn: sqlite3.Connection,
    kind: str,
    *,
    storage_root_id: int | None = None,
    payload: dict[str, Any] | None = None,
    priority: int | None = None,
    unique: bool = True,
) -> int:
    """Queue a task, or return the id of an identical one that is already active.

    ``unique=False`` always queues a new task (e.g. two exports of different photos).
    ``priority`` defaults to the kind's (``priority_for``).
    """
    if priority is None:
        priority = priority_for(kind)
    now = utc_now()
    with transaction(conn):
        existing = (
            None
            if not unique
            else conn.execute(
                """
            SELECT id FROM tasks
            WHERE kind = ? AND storage_root_id IS ? AND cancel_requested = 0
              AND status IN ('pending', 'running')
            ORDER BY id LIMIT 1
            """,
                (kind, storage_root_id),
            ).fetchone()
        )
        if existing is not None:
            return int(existing["id"])
        cursor = conn.execute(
            """
            INSERT INTO tasks (kind, status, priority, storage_root_id, payload,
                               created_at, updated_at)
            VALUES (?, 'pending', ?, ?, ?, ?, ?)
            """,
            (kind, priority, storage_root_id, json.dumps(payload or {}), now, now),
        )
        return int(cursor.lastrowid or 0)


def claim_next(conn: sqlite3.Connection) -> sqlite3.Row | None:
    now = utc_now()
    with transaction(conn):
        row = conn.execute(
            """
            SELECT id FROM tasks
            WHERE status = 'pending' AND (run_after IS NULL OR run_after <= ?)
            ORDER BY priority DESC, id
            LIMIT 1
            """,
            (now,),
        ).fetchone()
        if row is None:
            return None
        conn.execute(
            """
            UPDATE tasks
            SET status = 'running', attempts = attempts + 1, started_at = ?, updated_at = ?,
                finished_at = NULL, error = NULL, run_after = NULL
            WHERE id = ?
            """,
            (now, now, row["id"]),
        )
    return get(conn, int(row["id"]))


def has_higher_pending(conn: sqlite3.Connection, priority: int) -> bool:
    """Whether a task that outranks ``priority`` is waiting and could run now."""
    row = conn.execute(
        """
        SELECT EXISTS (
            SELECT 1 FROM tasks
            WHERE status = 'pending' AND priority > ? AND (run_after IS NULL OR run_after <= ?)
        )
        """,
        (priority, utc_now()),
    ).fetchone()
    return bool(row[0])


def apply_priorities(conn: sqlite3.Connection) -> int:
    """Give active tasks their kind's priority (tasks queued by earlier versions had 0)."""
    marks = ",".join("?" * len(BACKGROUND_KINDS))
    cursor = conn.execute(
        f"""
        UPDATE tasks
        SET priority = CASE WHEN kind IN ({marks}) THEN ? ELSE ? END
        WHERE status IN ('pending', 'running')
          AND priority != CASE WHEN kind IN ({marks}) THEN ? ELSE ? END
        """,
        (
            *sorted(BACKGROUND_KINDS), BACKGROUND_PRIORITY, FOREGROUND_PRIORITY,
            *sorted(BACKGROUND_KINDS), BACKGROUND_PRIORITY, FOREGROUND_PRIORITY,
        ),
    )  # fmt: skip
    return cursor.rowcount


def report_progress(
    conn: sqlite3.Connection, task_id: int, current: int, total: int | None
) -> bool:
    """Store progress. Returns False if the task was cancelled or deleted meanwhile."""
    cursor = conn.execute(
        """
        UPDATE tasks SET progress_current = ?, progress_total = ?, updated_at = ?
        WHERE id = ? AND status = 'running'
        """,
        (max(0, current), total, utc_now(), task_id),
    )
    if cursor.rowcount == 0:
        return False
    return not cancel_requested(conn, task_id)


def cancel_requested(conn: sqlite3.Connection, task_id: int) -> bool:
    row = conn.execute(
        "SELECT cancel_requested, status FROM tasks WHERE id = ?", (task_id,)
    ).fetchone()
    return row is None or bool(row["cancel_requested"]) or row["status"] != "running"


def mark_succeeded(
    conn: sqlite3.Connection, task_id: int, result: dict[str, Any] | None = None
) -> None:
    now = utc_now()
    conn.execute(
        """
        UPDATE tasks
        SET status = 'succeeded', finished_at = ?, updated_at = ?, error = NULL,
            progress_current = COALESCE(progress_total, progress_current), result = ?
        WHERE id = ? AND status = 'running'
        """,
        (now, now, json.dumps(result) if result is not None else None, task_id),
    )


def mark_cancelled(conn: sqlite3.Connection, task_id: int) -> None:
    now = utc_now()
    conn.execute(
        """
        UPDATE tasks SET status = 'cancelled', finished_at = ?, updated_at = ?
        WHERE id = ? AND status IN ('pending', 'running')
        """,
        (now, now, task_id),
    )


def mark_failed(conn: sqlite3.Connection, task_id: int, error: str, *, retry: bool) -> str:
    """Record a failure; requeue with exponential backoff while attempts remain."""
    now = utc_now()
    with transaction(conn):
        row = conn.execute(
            "SELECT attempts, max_attempts FROM tasks WHERE id = ?", (task_id,)
        ).fetchone()
        if row is None:
            return "deleted"
        attempts, max_attempts = int(row["attempts"]), int(row["max_attempts"])
        if retry and attempts < max_attempts:
            delay = RETRY_BASE_DELAY * (2 ** (attempts - 1))
            conn.execute(
                """
                UPDATE tasks SET status = 'pending', error = ?, run_after = ?, updated_at = ?
                WHERE id = ?
                """,
                (error, _later(delay), now, task_id),
            )
            return "pending"
        conn.execute(
            """
            UPDATE tasks SET status = 'failed', error = ?, finished_at = ?, updated_at = ?
            WHERE id = ?
            """,
            (error, now, now, task_id),
        )
        return "failed"


def mark_interrupted(conn: sqlite3.Connection, task_id: int) -> None:
    """Put a running task back in the queue without counting the attempt.

    Used on app shutdown and when a background task gives way to other work.
    """
    conn.execute(
        """
        UPDATE tasks
        SET status = 'pending', attempts = MAX(attempts - 1, 0), updated_at = ?
        WHERE id = ? AND status = 'running'
        """,
        (utc_now(), task_id),
    )


def recover_interrupted(conn: sqlite3.Connection) -> int:
    """At startup, tasks left 'running' were interrupted by a crash: queue them again.

    Media ingestion tracks attempts per file, so a file that crashes the process is
    skipped after a few tries; the task itself is not charged for the interruption.
    """
    cursor = conn.execute(
        """
        UPDATE tasks
        SET status = 'pending', attempts = MAX(attempts - 1, 0), updated_at = ?
        WHERE status = 'running'
        """,
        (utc_now(),),
    )
    return cursor.rowcount


def request_cancel(conn: sqlite3.Connection, task_id: int) -> None:
    now = utc_now()
    with transaction(conn):
        row = get(conn, task_id)
        if row["status"] == "pending":
            conn.execute(
                """
                UPDATE tasks SET status = 'cancelled', cancel_requested = 1,
                                 finished_at = ?, updated_at = ?
                WHERE id = ?
                """,
                (now, now, task_id),
            )
        elif row["status"] == "running":
            conn.execute(
                "UPDATE tasks SET cancel_requested = 1, updated_at = ? WHERE id = ?",
                (now, task_id),
            )
        else:
            raise ConflictError(
                f"Task is already {row['status']}", details={"id": task_id, "status": row["status"]}
            )


def retry(conn: sqlite3.Connection, task_id: int) -> None:
    with transaction(conn):
        row = get(conn, task_id)
        if row["status"] not in ("failed", "cancelled"):
            raise ConflictError(
                "Only failed or cancelled tasks can be retried",
                details={"id": task_id, "status": row["status"]},
            )
        conn.execute(
            """
            UPDATE tasks
            SET status = 'pending', attempts = 0, error = NULL, run_after = NULL,
                cancel_requested = 0, progress_current = 0, progress_total = NULL,
                started_at = NULL, finished_at = NULL, updated_at = ?
            WHERE id = ?
            """,
            (utc_now(), task_id),
        )
