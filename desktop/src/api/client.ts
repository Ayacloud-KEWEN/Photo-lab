import { toSearchParams, type AssetQuery, type QueryValue } from "./query";
import type {
  AIStatus,
  AnalysisResult,
  AppSettings,
  AppSettingsUpdate,
  AssetBatchUpdate,
  AssetDetail,
  AssetFacets,
  AssetIds,
  AssetPage,
  AssetUpdate,
  BatchResult,
  CloudPreview,
  CloudRequest,
  CloudTestResult,
  ErrorBody,
  HealthResponse,
  MapPoints,
  RenditionVariant,
  SemanticPage,
  StorageRoot,
  StorageRootCreate,
  StorageRootList,
  Tag,
  Task,
  TaskList,
  Timeline,
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
  method: "GET" | "POST" | "PUT" | "PATCH" | "DELETE",
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

const filters = (query: AssetQuery): Record<string, QueryValue> => ({ ...query });

export const api = {
  getHealth: (conn: BackendConnection) => request<HealthResponse>(conn, "GET", "/api/v1/health"),

  listStorageRoots: (conn: BackendConnection) =>
    request<StorageRootList>(conn, "GET", "/api/v1/storage-roots"),

  createStorageRoot: (conn: BackendConnection, body: StorageRootCreate) =>
    request<StorageRoot>(conn, "POST", "/api/v1/storage-roots", body),

  deleteStorageRoot: (conn: BackendConnection, id: number) =>
    request<void>(conn, "DELETE", `/api/v1/storage-roots/${id}`),

  scanStorageRoot: (conn: BackendConnection, id: number) =>
    request<Task>(conn, "POST", `/api/v1/storage-roots/${id}/scan`),

  listTasks: (conn: BackendConnection, options: { active?: boolean; limit?: number } = {}) =>
    request<TaskList>(conn, "GET", `/api/v1/tasks${toSearchParams({ ...options })}`),

  cancelTask: (conn: BackendConnection, id: number) =>
    request<Task>(conn, "POST", `/api/v1/tasks/${id}/cancel`),

  retryTask: (conn: BackendConnection, id: number) =>
    request<Task>(conn, "POST", `/api/v1/tasks/${id}/retry`),

  listAssets: (
    conn: BackendConnection,
    query: AssetQuery,
    page: { cursor?: string | null; limit?: number } = {},
  ) =>
    request<AssetPage>(
      conn,
      "GET",
      `/api/v1/assets${toSearchParams({ ...filters(query), cursor: page.cursor, limit: page.limit })}`,
    ),

  listAssetIds: (conn: BackendConnection, query: AssetQuery) =>
    request<AssetIds>(conn, "GET", `/api/v1/assets/ids${toSearchParams(filters(query))}`),

  getFacets: (conn: BackendConnection) =>
    request<AssetFacets>(conn, "GET", "/api/v1/assets/facets"),

  getAsset: (conn: BackendConnection, id: number) =>
    request<AssetDetail>(conn, "GET", `/api/v1/assets/${id}`),

  updateAsset: (conn: BackendConnection, id: number, body: AssetUpdate) =>
    request<AssetDetail>(conn, "PATCH", `/api/v1/assets/${id}`, body),

  batchUpdate: (conn: BackendConnection, body: AssetBatchUpdate) =>
    request<BatchResult>(conn, "POST", "/api/v1/assets/batch", body),

  getTimeline: (
    conn: BackendConnection,
    query: AssetQuery,
    granularity: "year" | "month" | "day",
  ) =>
    request<Timeline>(
      conn,
      "GET",
      `/api/v1/timeline${toSearchParams({ ...filters(query), granularity })}`,
    ),

  getMapPoints: (conn: BackendConnection, query: AssetQuery) =>
    request<MapPoints>(conn, "GET", `/api/v1/map/points${toSearchParams(filters(query))}`),

  listTags: (conn: BackendConnection) => request<Tag[]>(conn, "GET", "/api/v1/tags"),

  renameTag: (conn: BackendConnection, id: number, name: string) =>
    request<Tag>(conn, "PATCH", `/api/v1/tags/${id}`, { name }),

  deleteTag: (conn: BackendConnection, id: number) =>
    request<void>(conn, "DELETE", `/api/v1/tags/${id}`),

  getSettings: (conn: BackendConnection) =>
    request<AppSettings>(conn, "GET", "/api/v1/settings"),

  updateSettings: (conn: BackendConnection, body: AppSettingsUpdate) =>
    request<AppSettings>(conn, "PATCH", "/api/v1/settings", body),

  getAiStatus: (conn: BackendConnection) => request<AIStatus>(conn, "GET", "/api/v1/ai/status"),

  downloadAiModel: (conn: BackendConnection) =>
    request<Task>(conn, "POST", "/api/v1/ai/model/download", {}),

  indexAi: (conn: BackendConnection) => request<Task>(conn, "POST", "/api/v1/ai/index"),

  aiSearch: (conn: BackendConnection, text: string, query: AssetQuery, limit = 200) =>
    request<SemanticPage>(
      conn,
      "GET",
      `/api/v1/ai/search${toSearchParams({ ...filters(query), text, limit })}`,
    ),

  similarAssets: (conn: BackendConnection, id: number, query: AssetQuery, limit = 200) =>
    request<SemanticPage>(
      conn,
      "GET",
      `/api/v1/assets/${id}/similar${toSearchParams({ ...filters(query), limit })}`,
    ),

  saveCloudKey: (conn: BackendConnection, apiKey: string) =>
    request<void>(conn, "PUT", "/api/v1/ai/cloud/key", { api_key: apiKey }),

  deleteCloudKey: (conn: BackendConnection) =>
    request<void>(conn, "DELETE", "/api/v1/ai/cloud/key"),

  testCloud: (conn: BackendConnection) =>
    request<CloudTestResult>(conn, "POST", "/api/v1/ai/cloud/test"),

  previewCloud: (conn: BackendConnection, body: CloudRequest) =>
    request<CloudPreview>(conn, "POST", "/api/v1/ai/cloud/preview", body),

  /** Sends photos to the cloud provider. Only call after the user confirmed the preview. */
  analyzeCloud: (conn: BackendConnection, body: CloudRequest) =>
    request<AnalysisResult>(conn, "POST", "/api/v1/ai/cloud/analyze", { ...body, confirmed: true }),

  listAnalyses: (conn: BackendConnection, assetId: number) =>
    request<AnalysisResult[]>(conn, "GET", `/api/v1/assets/${assetId}/analyses`),
};

/**
 * URL usable in `<img src>`. Images cannot send headers, so the token goes in the
 * query string (the backend accepts this for media endpoints only). `version`
 * changes with the file content, which makes the response cacheable forever.
 */
export function thumbnailUrl(
  conn: BackendConnection,
  assetId: number,
  version: string,
  variant: RenditionVariant = "thumb",
): string {
  return `${conn.baseUrl}/api/v1/assets/${assetId}/thumbnail${toSearchParams({
    variant,
    v: version,
    token: conn.token,
  })}`;
}

/** The original file (video playback, 1:1 viewing). Read-only; supports HTTP Range. */
export function originalUrl(conn: BackendConnection, assetId: number, version: string): string {
  return `${conn.baseUrl}/api/v1/assets/${assetId}/original${toSearchParams({
    v: version,
    token: conn.token,
  })}`;
}
