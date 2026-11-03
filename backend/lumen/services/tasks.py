from __future__ import annotations

import sqlite3

from lumen.schemas.tasks import Task
from lumen.tasks import queue


def _to_model(row: sqlite3.Row) -> Task:
    return Task(
        id=row["id"],
        kind=row["kind"],
        status=row["status"],
        storage_root_id=row["storage_root_id"],
        progress_current=row["progress_current"],
        progress_total=row["progress_total"],
        attempts=row["attempts"],
        max_attempts=row["max_attempts"],
        cancel_requested=bool(row["cancel_requested"]),
        error=row["error"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        started_at=row["started_at"],
        finished_at=row["finished_at"],
    )


def list_tasks(conn: sqlite3.Connection, *, active_only: bool, limit: int) -> list[Task]:
    if active_only:
        rows = conn.execute(
            "SELECT * FROM tasks WHERE status IN ('pending', 'running') "
            "ORDER BY priority DESC, id LIMIT ?",
            (limit,),
        )
    else:
        rows = conn.execute("SELECT * FROM tasks ORDER BY id DESC LIMIT ?", (limit,))
    return [_to_model(row) for row in rows]


def get_task(conn: sqlite3.Connection, task_id: int) -> Task:
    return _to_model(queue.get(conn, task_id))


def cancel_task(conn: sqlite3.Connection, task_id: int) -> Task:
    queue.request_cancel(conn, task_id)
    return get_task(conn, task_id)


def retry_task(conn: sqlite3.Connection, task_id: int) -> Task:
    queue.retry(conn, task_id)
    return get_task(conn, task_id)
