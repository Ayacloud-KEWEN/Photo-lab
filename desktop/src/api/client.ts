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
  CollectionCreate,
  CollectionDetail,
  CollectionUpdate,
  CloudPreview,
  CloudRequest,
  CloudTestResult,
  Collection,
  EditBatch,
  EditBatchResult,
  EditRecipe,
  EditState,
  ErrorBody,
  ExportRequest,
  ExportStatus,
  FrameExportResult,
  VideoEditState,
  VideoRecipe,
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
  TripSuggestion,
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

/** A binary response (rendered images); aborted requests reject with an AbortError. */
async function requestBinary(
  conn: BackendConnection,
  path: string,
  body: unknown,
  signal?: AbortSignal,
): Promise<Response> {
  let response: Response;
  try {
    response = await fetch(`${conn.baseUrl}${path}`, {
      method: "POST",
      headers: { Authorization: `Bearer ${conn.token}`, "Content-Type": "application/json" },
      body: JSON.stringify(body),
      ...(signal ? { signal } : {}),
    });
  } catch (cause) {
    if (cause instanceof DOMException && cause.name === "AbortError") throw cause;
    throw new ApiError(0, {
      code: "network_error",
      message: cause instanceof Error ? cause.message : String(cause),
    });
  }
  if (!response.ok) {
    const payload: unknown = await response.json().catch(() => null);
    throw new ApiError(
      response.status,
      isErrorEnvelope(payload)
        ? payload.error
        : { code: "http_error", message: `HTTP ${response.status}` },
    );
  }
  return response;
}

export interface DevelopPreview {
  image: Blob;
  /** Pixel counts per channel (R, G, B), or null if the backend sent none. */
  histogram: number[][] | null;
}

function parseHistogram(header: string | null): number[][] | null {
  if (!header) return null;
  const channels = header.split(";").map((channel) => channel.split(",").map(Number));
  return channels.length === 3 && channels.every((c) => c.every(Number.isFinite)) ? channels : null;
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

  getEdit: (conn: BackendConnection, id: number) =>
    request<EditState>(conn, "GET", `/api/v1/assets/${id}/edit`),

  saveEdit: (conn: BackendConnection, id: number, recipe: EditRecipe) =>
    request<EditState>(conn, "PUT", `/api/v1/assets/${id}/edit`, recipe),

  undoEdit: (conn: BackendConnection, id: number) =>
    request<EditState>(conn, "POST", `/api/v1/assets/${id}/edit/undo`),

  redoEdit: (conn: BackendConnection, id: number) =>
    request<EditState>(conn, "POST", `/api/v1/assets/${id}/edit/redo`),

  /** Apply some settings (pasted, or a preset) to many photos. */
  applyEdits: (conn: BackendConnection, body: EditBatch) =>
    request<EditBatchResult>(conn, "POST", "/api/v1/edits/batch", body),

  listCollections: (conn: BackendConnection) =>
    request<{ items: Collection[] }>(conn, "GET", "/api/v1/collections"),

  suggestTrips: (conn: BackendConnection) =>
    request<{ items: TripSuggestion[] }>(conn, "GET", "/api/v1/collections/suggestions"),

  getCollection: (conn: BackendConnection, id: number) =>
    request<CollectionDetail>(conn, "GET", `/api/v1/collections/${id}`),

  createCollection: (conn: BackendConnection, body: CollectionCreate) =>
    request<CollectionDetail>(conn, "POST", "/api/v1/collections", body),

  updateCollection: (conn: BackendConnection, id: number, body: CollectionUpdate) =>
    request<CollectionDetail>(conn, "PATCH", `/api/v1/collections/${id}`, body),

  deleteCollection: (conn: BackendConnection, id: number) =>
    request<void>(conn, "DELETE", `/api/v1/collections/${id}`),

  addToCollection: (conn: BackendConnection, id: number, assetIds: number[]) =>
    request<{ changed: number }>(conn, "POST", `/api/v1/collections/${id}/items`, {
      asset_ids: assetIds,
    }),

  removeFromCollection: (conn: BackendConnection, id: number, assetIds: number[]) =>
    request<{ changed: number }>(conn, "POST", `/api/v1/collections/${id}/items/remove`, {
      asset_ids: assetIds,
    }),

  reorderCollection: (conn: BackendConnection, id: number, assetIds: number[]) =>
    request<{ changed: number }>(conn, "PUT", `/api/v1/collections/${id}/order`, {
      asset_ids: assetIds,
    }),

  setCaption: (conn: BackendConnection, id: number, assetId: number, caption: string | null) =>
    request<void>(conn, "PATCH", `/api/v1/collections/${id}/items/${assetId}`, { caption }),

  getVideoEdit: (conn: BackendConnection, id: number) =>
    request<VideoEditState>(conn, "GET", `/api/v1/assets/${id}/video-edit`),

  saveVideoEdit: (conn: BackendConnection, id: number, recipe: VideoRecipe) =>
    request<VideoEditState>(conn, "PUT", `/api/v1/assets/${id}/video-edit`, recipe),

  /** Save one video frame as a new JPEG in ``destination``. */
  exportFrame: (conn: BackendConnection, id: number, timeMs: number, destination: string) =>
    request<FrameExportResult>(conn, "POST", `/api/v1/assets/${id}/frame-export`, {
      time_ms: timeMs,
      destination,
    }),

  startExport: (conn: BackendConnection, body: ExportRequest) =>
    request<ExportStatus>(conn, "POST", "/api/v1/exports", body),

  getExport: (conn: BackendConnection, taskId: number) =>
    request<ExportStatus>(conn, "GET", `/api/v1/exports/${taskId}`),

  selectEdit: (conn: BackendConnection, id: number, editId: number | null) =>
    request<EditState>(conn, "POST", `/api/v1/assets/${id}/edit/select`, { edit_id: editId }),

  /** The photo developed with an unsaved recipe, as a JPEG. */
  renderDevelopPreview: (
    conn: BackendConnection,
    id: number,
    recipe: EditRecipe,
    edge: number,
    signal?: AbortSignal,
  ): Promise<DevelopPreview> =>
    requestBinary(conn, `/api/v1/assets/${id}/develop/preview`, { recipe, edge }, signal).then(
      async (response) => ({
        image: await response.blob(),
        histogram: parseHistogram(response.headers.get("X-Histogram")),
      }),
    ),

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
/** A Live Photo's motion clip. */
export function motionUrl(conn: BackendConnection, assetId: number, version: string): string {
  return `${conn.baseUrl}/api/v1/assets/${assetId}/motion${toSearchParams({
    v: version,
    token: conn.token,
  })}`;
}

export function originalUrl(conn: BackendConnection, assetId: number, version: string): string {
  return `${conn.baseUrl}/api/v1/assets/${assetId}/original${toSearchParams({
    v: version,
    token: conn.token,
  })}`;
}
