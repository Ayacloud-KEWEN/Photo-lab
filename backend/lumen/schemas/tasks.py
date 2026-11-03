from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

TaskStatus = Literal["pending", "running", "succeeded", "failed", "cancelled"]


class Task(BaseModel):
    id: int
    kind: str
    status: TaskStatus
    storage_root_id: int | None
    progress_current: int
    progress_total: int | None
    attempts: int
    max_attempts: int
    cancel_requested: bool
    error: str | None
    result: dict[str, Any] | None = Field(
        default=None, description="Outcome of a finished task (depends on its kind)"
    )
    created_at: str
    updated_at: str
    started_at: str | None
    finished_at: str | None


class TaskList(BaseModel):
    items: list[Task]
