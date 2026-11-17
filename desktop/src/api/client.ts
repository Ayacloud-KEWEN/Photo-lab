import { toSearchParams, type AssetQuery, type QueryValue } from "./query";
import type {
  AIStatus,
  AnalysisResult,
  AskAnswer,
  Diary,
  FootprintPhotos,
  LayerFootprint,
  LayerPlan,
  LayerPlanSummary,
  LayerTrack,
  FolderList,
  StoryWriter,
  AppSettings,
  AppSettingsUpdate,
  AssetBatchUpdate,
  AssetDetail,
  AssetFacets,
  AssetIds,
  AssetPage,
  AssetUpdate,
  BatchResult,
  BackupInfo,
  BackupList,
  CacheStatus,
  CollectionCreate,
  DuplicateKind,
  DuplicateReport,
  CollectionDetail,
  CollectionRoute,
  MapWebPlan,
  NearbyResult,
  PlaceMatch,
  MapWebSendRequest,
  MapWebStatus,
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
  LiveInfo,
  VlmStatus,
  Lut,
  LutImportResult,
  PhoneImport,
  PhoneList,
  PhoneSummary,
  LutSpace,
  LutUpdate,
  MotionEffect,
  VideoEditState,
  VideoRecipe,
  HealthResponse,
  MapPoints,
  MergeRequest,
  MergeResult,
  RejectedFiles,
  RenditionVariant,
  RestoreRequest,
  RestoreResult,
  SemanticPage,
  SimilarGroups,
  StorageRoot,
  Suspects,
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

  listFolders: (conn: BackendConnection, rootId: number, path: string) =>
    request<FolderList>(
      conn,
      "GET",
      `/api/v1/folders${toSearchParams({ storage_root_id: rootId, path })}`,
    ),

  searchFolders: (conn: BackendConnection, q: string) =>
    request<FolderList>(conn, "GET", `/api/v1/folders/search${toSearchParams({ q })}`),

  revealFolder: (conn: BackendConnection, rootId: number, path: string) =>
    request<void>(
      conn,
      "POST",
      `/api/v1/folders/reveal${toSearchParams({ storage_root_id: rootId, path })}`,
    ),

  mapWebFootprints: (conn: BackendConnection) =>
    request<LayerFootprint[]>(conn, "GET", "/api/v1/mapweb/layers/footprints"),

  mapWebFootprintPhotos: (conn: BackendConnection, pointId: number, language: string) =>
    request<FootprintPhotos>(
      conn,
      "GET",
      `/api/v1/mapweb/layers/footprints/${pointId}/photos${toSearchParams({ language })}`,
    ),

  mapWebTracks: (conn: BackendConnection) =>
    request<LayerTrack[]>(conn, "GET", "/api/v1/mapweb/layers/tracks"),

  mapWebPlans: (conn: BackendConnection) =>
    request<LayerPlanSummary[]>(conn, "GET", "/api/v1/mapweb/layers/plans"),

  mapWebPlan: (conn: BackendConnection, planId: number) =>
    request<LayerPlan>(conn, "GET", `/api/v1/mapweb/layers/plans/${planId}`),

  getMapWebSync: (conn: BackendConnection) =>
    request<{ on_map: number; outdated: number; features: string[] }>(
      conn,
      "GET",
      "/api/v1/mapweb/sync",
    ),

  syncMapWeb: (conn: BackendConnection) => request<Task>(conn, "POST", "/api/v1/mapweb/sync"),

  updateOnMapWeb: (conn: BackendConnection, assetIds: number[] | null) =>
    request<Task>(conn, "POST", "/api/v1/mapweb/update", { asset_ids: assetIds }),

  openFootprint: (conn: BackendConnection, pointId: number) =>
    request<void>(conn, "POST", `/api/v1/mapweb/open-point/${pointId}`),

  openOnMapWeb: (conn: BackendConnection, assetId: number) =>
    request<void>(conn, "POST", `/api/v1/mapweb/open/${assetId}`),

  getPlaybackState: (conn: BackendConnection, assetId: number, start: boolean) =>
    request<{ needed: boolean; ready: boolean; task_id: number | null }>(
      conn,
      "GET",
      `/api/v1/assets/${assetId}/playback/state${toSearchParams({ start })}`,
    ),

  getTask: (conn: BackendConnection, id: number) =>
    request<Task>(conn, "GET", `/api/v1/tasks/${id}`),

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

  writeCollectionStory: (
    conn: BackendConnection,
    id: number,
    body: { language: string; writer: StoryWriter; notes_from?: number | null },
  ) => request<{ task_id: number }>(conn, "POST", `/api/v1/collections/${id}/story`, body),

  writeCollectionStoryInCloud: (conn: BackendConnection, id: number, analysisId: number) =>
    request<AnalysisResult>(
      conn,
      "POST",
      `/api/v1/collections/${id}/stories/${analysisId}/cloud`,
      { confirmed: true },
    ),

  draftCollectionCaptions: (
    conn: BackendConnection,
    id: number,
    body: { asset_ids: number[] | null; language: string },
  ) =>
    request<{ task_id: number }>(conn, "POST", `/api/v1/collections/${id}/caption-drafts`, body),

  settleCaptionDrafts: (
    conn: BackendConnection,
    id: number,
    assetIds: number[] | null,
    accept: boolean,
  ) =>
    request<{ changed: number }>(
      conn,
      "POST",
      `/api/v1/collections/${id}/caption-drafts/${accept ? "accept" : "discard"}`,
      { asset_ids: assetIds },
    ),

  getCollectionDiary: (conn: BackendConnection, id: number) =>
    request<Diary>(conn, "GET", `/api/v1/collections/${id}/diary`),

  writeCollectionDiary: (
    conn: BackendConnection,
    id: number,
    body: { day: string; after_asset_id: number | null; text: string },
  ) => request<void>(conn, "PUT", `/api/v1/collections/${id}/diary`, body),

  importDiaryNotes: (conn: BackendConnection, id: number, analysisId: number) =>
    request<{ changed: number }>(conn, "POST", `/api/v1/collections/${id}/diary/import-notes`, {
      analysis_id: analysisId,
    }),

  askLibrary: (conn: BackendConnection, question: string, language: string) =>
    request<AskAnswer>(conn, "POST", "/api/v1/ask", { question, language }),

  listQuestions: (conn: BackendConnection) =>
    request<{ items: AskAnswer[] }>(conn, "GET", "/api/v1/ask"),

  getQuestion: (conn: BackendConnection, id: number) =>
    request<AskAnswer>(conn, "GET", `/api/v1/ask/${id}`),

  deleteQuestion: (conn: BackendConnection, id: number) =>
    request<void>(conn, "DELETE", `/api/v1/ask/${id}`),

  listCollectionStories: (conn: BackendConnection, id: number) =>
    request<AnalysisResult[]>(conn, "GET", `/api/v1/collections/${id}/stories`),

  getCollectionRoute: (conn: BackendConnection, id: number) =>
    request<CollectionRoute>(conn, "GET", `/api/v1/collections/${id}/route`),

  /** Puts photos at a place (stored in LUMEN only; exports write it into new files). */
  setLocation: (conn: BackendConnection, assetIds: number[], latitude: number, longitude: number) =>
    request<{ changed: number }>(conn, "POST", "/api/v1/assets/location", {
      asset_ids: assetIds,
      latitude,
      longitude,
    }),

  restoreLocation: (conn: BackendConnection, assetIds: number[]) =>
    request<{ changed: number }>(conn, "POST", "/api/v1/assets/location/restore", {
      asset_ids: assetIds,
    }),

  /** Each photo gets the location of the photo taken closest in time (``apply`` false: a preview). */
  locateByTime: (conn: BackendConnection, assetIds: number[], maxHours: number, apply: boolean) =>
    request<NearbyResult>(conn, "POST", "/api/v1/assets/location/nearby", {
      asset_ids: assetIds,
      max_hours: maxHours,
      apply,
    }),

  shiftTime: (conn: BackendConnection, assetIds: number[], seconds: number) =>
    request<{ changed: number }>(conn, "POST", "/api/v1/assets/time-shift", {
      asset_ids: assetIds,
      seconds,
    }),

  setTime: (
    conn: BackendConnection,
    assetIds: number[],
    time: string,
    keepSpacing: boolean,
  ) =>
    request<{ changed: number }>(conn, "POST", "/api/v1/assets/time-set", {
      asset_ids: assetIds,
      time,
      keep_spacing: keepSpacing,
    }),

  timeRange: (conn: BackendConnection, assetIds: number[]) =>
    request<{ first: string | null; first_asset_id: number | null; last: string | null }>(
      conn,
      "POST",
      "/api/v1/assets/time-range",
      { asset_ids: assetIds },
    ),

  restoreTime: (conn: BackendConnection, assetIds: number[]) =>
    request<{ changed: number }>(conn, "POST", "/api/v1/assets/time-shift/restore", {
      asset_ids: assetIds,
    }),

  /** Towns by name, offline. */
  searchPlaces: (conn: BackendConnection, query: string) =>
    request<PlaceMatch[]>(conn, "GET", `/api/v1/places/search${toSearchParams({ q: query })}`),

  /** Checks an address answers like MapWeb (the user's map on their Raspberry Pi). */
  testMapWeb: (conn: BackendConnection, url: string) =>
    request<MapWebStatus>(conn, "POST", "/api/v1/mapweb/test", { url }),

  /** Where photos would go on the map (asks MapWeb for its footprints). */
  planMapWebSend: (conn: BackendConnection, assetIds: number[], language: string) =>
    request<MapWebPlan>(conn, "POST", "/api/v1/mapweb/plan", { asset_ids: assetIds, language }),

  sendToMapWeb: (conn: BackendConnection, body: MapWebSendRequest) =>
    request<Task>(conn, "POST", "/api/v1/mapweb/send", body),

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

  listSimilarGroups: (
    conn: BackendConnection,
    params: { window_minutes: number; similarity: number; pending_only: boolean; limit: number },
  ) => request<SimilarGroups>(conn, "GET", `/api/v1/cull/similar${toSearchParams(params)}`),

  listSuspects: (conn: BackendConnection, pendingOnly: boolean) =>
    request<Suspects>(
      conn,
      "GET",
      `/api/v1/cull/suspects${toSearchParams({ pending_only: pendingOnly })}`,
    ),

  listDuplicates: (conn: BackendConnection, kind: DuplicateKind = "identical") =>
    request<DuplicateReport>(conn, "GET", `/api/v1/duplicates${toSearchParams({ kind })}`),

  /** Merges every group into its suggested copy, as a background task. */
  mergeAllDuplicates: (conn: BackendConnection, kind: DuplicateKind = "identical") =>
    request<Task>(conn, "POST", `/api/v1/duplicates/merge-all${toSearchParams({ kind })}`),

  mergeDuplicates: (conn: BackendConnection, body: MergeRequest) =>
    request<MergeResult>(conn, "POST", "/api/v1/duplicates/merge", body),

  rejectedFiles: (conn: BackendConnection) =>
    request<RejectedFiles>(conn, "GET", "/api/v1/cull/rejected-files"),

  /** Opens Google Maps at the asset's location in the default browser. */
  openAssetMap: (conn: BackendConnection, assetId: number) =>
    request<void>(conn, "POST", `/api/v1/assets/${assetId}/open-map`),

  revealFile: (conn: BackendConnection, fileId: number) =>
    request<void>(conn, "POST", `/api/v1/files/${fileId}/reveal`),

  listBackups: (conn: BackendConnection) => request<BackupList>(conn, "GET", "/api/v1/backups"),

  createBackup: (conn: BackendConnection) =>
    request<BackupInfo>(conn, "POST", "/api/v1/backups"),

  restoreBackup: (conn: BackendConnection, body: RestoreRequest) =>
    request<RestoreResult>(conn, "POST", "/api/v1/backups/restore", body),

  revealBackup: (conn: BackendConnection, name: string) =>
    request<void>(conn, "POST", "/api/v1/backups/reveal", { name }),

  getCacheStatus: (conn: BackendConnection) =>
    request<CacheStatus>(conn, "GET", "/api/v1/cache"),

  /** Move thumbnails and previews to another folder (a background task). */
  moveCache: (conn: BackendConnection, folder: string) =>
    request<Task>(conn, "POST", "/api/v1/cache/move", { folder }),

  getAiStatus: (conn: BackendConnection) => request<AIStatus>(conn, "GET", "/api/v1/ai/status"),

  downloadAiModel: (conn: BackendConnection) =>
    request<Task>(conn, "POST", "/api/v1/ai/model/download", {}),

  indexAi: (conn: BackendConnection) => request<Task>(conn, "POST", "/api/v1/ai/index"),

  /** Load the model in the background so the first search does not wait for it. */
  warmUpAi: (conn: BackendConnection) => request<void>(conn, "POST", "/api/v1/ai/warm-up"),

  aiSearch: (conn: BackendConnection, text: string, query: AssetQuery, limit = 200) =>
    request<SemanticPage>(
      conn,
      "GET",
      `/api/v1/ai/search${toSearchParams({ ...filters(query), text, limit })}`,
    ),

  /** Live Photos whose scene (water, traffic at night...) suits a long exposure. */
  longExposureCandidates: (conn: BackendConnection, limit = 120) =>
    request<SemanticPage>(conn, "GET", `/api/v1/ai/long-exposure${toSearchParams({ limit })}`),

  /** Phones connected by cable (iPhone). */
  listPhones: (conn: BackendConnection) => request<PhoneList>(conn, "GET", "/api/v1/phones"),

  /** What an import would copy (reads the phone's list of files: can take a while). */
  getPhoneSummary: (conn: BackendConnection, id: string) =>
    request<PhoneSummary>(conn, "GET", `/api/v1/phones/${id}/summary`),

  importFromPhone: (conn: BackendConnection, id: string, body: PhoneImport) =>
    request<Task>(conn, "POST", `/api/v1/phones/${id}/import`, body),

  listLuts: (conn: BackendConnection) =>
    request<{ items: Lut[] }>(conn, "GET", "/api/v1/luts"),

  /** Copy .cube files (or every .cube in folders) into the LUT library. */
  importLuts: (conn: BackendConnection, paths: string[], colorSpace: LutSpace) =>
    request<LutImportResult>(conn, "POST", "/api/v1/luts/import", {
      paths,
      color_space: colorSpace,
    }),

  updateLut: (conn: BackendConnection, id: string, body: LutUpdate) =>
    request<Lut>(conn, "PATCH", `/api/v1/luts/${id}`, body),

  /** Deleted, or hidden when an edit uses it. */
  deleteLut: (conn: BackendConnection, id: string) =>
    request<void>(conn, "DELETE", `/api/v1/luts/${id}`),

  /** The local vision-language model: files present, photos read and still to read. */
  getVlmStatus: (conn: BackendConnection) =>
    request<VlmStatus>(conn, "GET", "/api/v1/vlm/status"),

  /** Read these photos first; `fine` uses the slower, more careful model. */
  describeAssets: (conn: BackendConnection, assetIds: number[], fine: boolean) =>
    request<{ queued: number; task_id: number }>(conn, "POST", "/api/v1/vlm/describe", {
      asset_ids: assetIds,
      fine,
    }),

  downloadVlm: (conn: BackendConnection, model: string) =>
    request<Task>(conn, "POST", "/api/v1/vlm/download", { model }),

  /** A Live Photo's frames, the still's position and the sharpest frame. */
  getLiveInfo: (conn: BackendConnection, id: number) =>
    request<LiveInfo>(conn, "GET", `/api/v1/assets/${id}/live`),

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

/**
 * The part of a rendition version that follows the file's content only: an edit adds
 * "-<hash>" to it. URLs of the original file and of Live Photo clips use this part, so
 * saving an edit does not make the webview download a (large) video again.
 */
export function contentVersion(version: string): string {
  return version.split("-")[0] ?? "";
}

/**
 * A Live Photo's motion clip: as shot, or rendered as a loop / bounce with the photo's
 * adjustments (then the whole rendition version, edit included, keys the cache).
 */
export function motionUrl(
  conn: BackendConnection,
  assetId: number,
  version: string,
  effect: MotionEffect = "live",
): string {
  return `${conn.baseUrl}/api/v1/assets/${assetId}/motion${toSearchParams({
    ...(effect === "live" ? { v: contentVersion(version) } : { effect, v: version }),
    token: conn.token,
  })}`;
}

/** How a Live Photo's clip plays, from its effect. */
export function motionEffectOf(effect: string | null | undefined): MotionEffect {
  return effect === "loop" || effect === "bounce" ? effect : "live";
}

/** A small picture of the photo (with its saved edit) graded by a LUT. */
export function lutPreviewUrl(
  conn: BackendConnection,
  assetId: number,
  version: string,
  lutRef: string,
): string {
  return `${conn.baseUrl}/api/v1/assets/${assetId}/lut-preview${toSearchParams({
    lut: lutRef,
    v: version,
    token: conn.token,
  })}`;
}

/** A frame of a video as its saved edit shows it (turned, LUT applied). */
export function videoPreviewUrl(
  conn: BackendConnection,
  assetId: number,
  version: string,
  timeMs: number,
): string {
  return `${conn.baseUrl}/api/v1/assets/${assetId}/video-preview${toSearchParams({
    time_ms: Math.max(0, Math.round(timeMs)),
    v: version,
    token: conn.token,
  })}`;
}

/** The Live Photo's frames side by side (the frame picker's background). */
export function liveStripUrl(conn: BackendConnection, assetId: number, version: string): string {
  return `${conn.baseUrl}/api/v1/assets/${assetId}/live/strip${toSearchParams({
    v: contentVersion(version),
    token: conn.token,
  })}`;
}

/** A MapWeb footprint's thumbnail, through LUMEN (MapWeb itself is not reachable from here). */
export function mapWebThumbUrl(conn: BackendConnection, path: string): string {
  return `${conn.baseUrl}/api/v1/mapweb/layers/thumb${toSearchParams({ path, token: conn.token })}`;
}

/** The converted copy of a video the web view cannot play (AVI, MTS...); supports Range. */
export function playbackUrl(conn: BackendConnection, assetId: number, version: string): string {
  return `${conn.baseUrl}/api/v1/assets/${assetId}/playback${toSearchParams({
    v: contentVersion(version),
    token: conn.token,
  })}`;
}

/** The original file (video playback, 1:1 viewing). Read-only; supports HTTP Range. */
export function originalUrl(conn: BackendConnection, assetId: number, version: string): string {
  return `${conn.baseUrl}/api/v1/assets/${assetId}/original${toSearchParams({
    v: contentVersion(version),
    token: conn.token,
  })}`;
}
