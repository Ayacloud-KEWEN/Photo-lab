from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from typing import Annotated

from fastapi import Depends, Request

from lumen.db.connection import Database


def get_database(request: Request) -> Database:
    db: Database = request.app.state.db
    return db


def get_connection(
    db: Annotated[Database, Depends(get_database)],
) -> Iterator[sqlite3.Connection]:
    with db.session() as conn:
        yield conn


Connection = Annotated[sqlite3.Connection, Depends(get_connection)]


def wake_task_runner(request: Request) -> None:
    """Tell the background runner new work was queued (no-op when tasks are disabled)."""
    runner = getattr(request.app.state, "task_runner", None)
    if runner is not None:
        runner.wake()
