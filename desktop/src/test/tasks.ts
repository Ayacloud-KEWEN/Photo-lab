import type { Task } from "@/api/types";

/** A background task as /tasks reports it. */
export function makeTask(id: number, kind: string, overrides: Partial<Task> = {}): Task {
  return {
    id, kind, status: "running", storage_root_id: null,
    progress_current: 0, progress_total: null, attempts: 1, max_attempts: 3,
    cancel_requested: false, error: null, result: null, created_at: "2026-11-05T07:40:00Z",
    updated_at: "2026-11-05T07:40:00Z", started_at: "2026-11-05T07:40:00Z", finished_at: null,
    ...overrides,
  }; // prettier-ignore
}
