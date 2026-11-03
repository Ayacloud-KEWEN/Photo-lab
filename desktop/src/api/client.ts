import type {
  ErrorBody,
  HealthResponse,
  StorageRoot,
  StorageRootCreate,
  StorageRootList,
} from "./types";

export interface BackendConnection {
  baseUrl: string;
  token: string;
}

/** A failed API call. `code` mirrors the backend error envelope (`network_error` if unreachable). */
export class ApiError extends Error {
  readonly status: number;
  readonly code: string;
  readonly details: Record<string, unknown>;

  constructor(status: number, body: ErrorBody) {
    super(body.message);
    this.name = "ApiError";
    this.status = status;
    this.code = body.code;
    this.details = body.details ?? {};
  }
}

function isErrorEnvelope(value: unknown): value is { error: ErrorBody } {
  if (typeof value !== "object" || value === null || !("error" in value)) return false;
  const error = (value as { error: unknown }).error;
  return typeof error === "object" && error !== null && "code" in error && "message" in error;
}

async function request<T>(
  conn: BackendConnection,
  method: "GET" | "POST" | "DELETE",
  path: string,
  body?: unknown,
): Promise<T> {
  const headers: Record<string, string> = { Authorization: `Bearer ${conn.token}` };
  const init: RequestInit = { method, headers };
  if (body !== undefined) {
    headers["Content-Type"] = "application/json";
    init.body = JSON.stringify(body);
  }

  let response: Response;
  try {
    response = await fetch(`${conn.baseUrl}${path}`, init);
  } catch (cause) {
    throw new ApiError(0, {
      code: "network_error",
      message: cause instanceof Error ? cause.message : String(cause),
    });
  }

  if (response.status === 204) return undefined as T;
  const payload: unknown = await response.json().catch(() => null);
  if (!response.ok) {
    throw new ApiError(
      response.status,
      isErrorEnvelope(payload)
        ? payload.error
        : { code: "http_error", message: `HTTP ${response.status}` },
    );
  }
  return payload as T;
}

export const api = {
  getHealth: (conn: BackendConnection) => request<HealthResponse>(conn, "GET", "/api/v1/health"),

  listStorageRoots: (conn: BackendConnection) =>
    request<StorageRootList>(conn, "GET", "/api/v1/storage-roots"),

  createStorageRoot: (conn: BackendConnection, body: StorageRootCreate) =>
    request<StorageRoot>(conn, "POST", "/api/v1/storage-roots", body),

  deleteStorageRoot: (conn: BackendConnection, id: number) =>
    request<void>(conn, "DELETE", `/api/v1/storage-roots/${id}`),
};
