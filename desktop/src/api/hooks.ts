import {
  useInfiniteQuery,
  useMutation,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query";
import { useEffect, useMemo, useRef } from "react";

import { useBackendStatus } from "./backend-context";
import { api, type BackendConnection } from "./client";
import type { AssetQuery } from "./query";
import type {
  AnalysisResult,
  AppSettingsUpdate,
  AssetBatchUpdate,
  AssetDetail,
  AssetUpdate,
  CloudRequest,
  CollectionCreate,
  CollectionUpdate,
  EditBatch,
  EditRecipe,
  EditState,
  ExportRequest,
  DuplicateKind,
  DuplicateReport,
  MergeRequest,
  RestoreRequest,
  StorageRootCreate,
  VideoEditState,
  VideoRecipe,
  Task,
} from "./types";

/** Everything under `library` derives from assets and is refreshed together. */
export const queryKeys = {
  health: ["health"] as const,
  storageRoots: ["storage-roots"] as const,
  tasks: ["tasks", "active"] as const,
  settings: ["settings"] as const,
  backups: ["backups"] as const,
  cache: ["cache"] as const,
  library: ["library"] as const,
  assets: (query: AssetQuery) => ["library", "assets", query] as const,
  facets: ["library", "facets"] as const,
  tags: ["library", "tags"] as const,
  timeline: (query: AssetQuery, granularity: string) =>
    ["library", "timeline", granularity, query] as const,
  map: (query: AssetQuery) => ["library", "map", query] as const,
  asset: (id: number) => ["library", "asset", id] as const,
  aiStatus: ["ai", "status"] as const,
  aiSearch: (text: string, query: AssetQuery) => ["library", "ai-search", text, query] as const,
  similar: (id: number, query: AssetQuery) => ["library", "similar", id, query] as const,
  analyses: (id: number) => ["library", "analyses", id] as const,
  edit: (id: number) => ["library", "edit", id] as const,
  export: (taskId: number) => ["export", taskId] as const,
  videoEdit: (id: number) => ["library", "video-edit", id] as const,
  collections: ["library", "collections"] as const,
  collection: (id: number) => ["library", "collections", id] as const,
  collectionRoute: (id: number) => ["library", "collections", id, "route"] as const,
  tripSuggestions: ["library", "collections", "suggestions"] as const,
  // Under "library": flag changes (batch / asset updates) refresh them.
  similarGroups: (params: SimilarParams) => ["library", "cull", "similar", params] as const,
  suspects: (pendingOnly: boolean) => ["library", "cull", "suspects", pendingOnly] as const,
  duplicates: (kind: DuplicateKind) => ["library", "cull", "duplicates", kind] as const,
};

const ASSET_PAGE_SIZE = 300;

/** The live connection, or `null` while the backend is starting / unavailable. */
export function useConnection(): BackendConnection | null {
  const status = useBackendStatus();
  return status.state === "ready" ? { baseUrl: status.baseUrl, token: status.token } : null;
}

function requireConnection(conn: BackendConnection | null): BackendConnection {
  if (!conn) throw new Error("Backend is not connected");
  return conn;
}

export function useHealth() {
  const conn = useConnection();
  return useQuery({
    queryKey: queryKeys.health,
    queryFn: () => api.getHealth(requireConnection(conn)),
    enabled: conn !== null,
    refetchInterval: 15_000,
  });
}

export function useStorageRoots() {
  const conn = useConnection();
  return useQuery({
    queryKey: queryKeys.storageRoots,
    queryFn: () => api.listStorageRoots(requireConnection(conn)),
    enabled: conn !== null,
    select: (data) => data.items,
    // Also catches work that started and finished between two task polls.
    refetchInterval: 10_000,
  });
}

export function useCreateStorageRoot() {
  const conn = useConnection();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: StorageRootCreate) => api.createStorageRoot(requireConnection(conn), body),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.storageRoots });
      void queryClient.invalidateQueries({ queryKey: queryKeys.tasks });
    },
  });
}

export function useDeleteStorageRoot() {
  const conn = useConnection();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (id: number) => api.deleteStorageRoot(requireConnection(conn), id),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.storageRoots });
      void queryClient.invalidateQueries({ queryKey: queryKeys.tasks });
      void queryClient.invalidateQueries({ queryKey: queryKeys.library });
    },
  });
}

export function useScanStorageRoot() {
  const conn = useConnection();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (id: number) => api.scanStorageRoot(requireConnection(conn), id),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: queryKeys.tasks }),
  });
}

export function useCancelTask() {
  const conn = useConnection();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (id: number) => api.cancelTask(requireConnection(conn), id),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: queryKeys.tasks }),
  });
}

/** Pending and running tasks; polled quickly while anything is active. */
export function useActiveTasks() {
  const conn = useConnection();
  return useQuery({
    queryKey: queryKeys.tasks,
    queryFn: () => api.listTasks(requireConnection(conn), { active: true }),
    enabled: conn !== null,
    select: (data) => data.items,
    refetchInterval: (query) => ((query.state.data?.items.length ?? 0) > 0 ? 1000 : 5000),
  });
}

/** The running (or else first queued) task for each storage root. */
export function tasksByRoot(tasks: Task[] | undefined): Map<number, Task> {
  const map = new Map<number, Task>();
  for (const task of tasks ?? []) {
    if (task.storage_root_id === null) continue;
    const current = map.get(task.storage_root_id);
    if (!current || (task.status === "running" && current.status !== "running")) {
      map.set(task.storage_root_id, task);
    }
  }
  return map;
}

/** While tasks run: root statistics, the grid and timeline, then the heavier views. */
const ROOTS_REFRESH_MS = 5_000;
const GRID_REFRESH_MS = 15_000;
const VIEWS_REFRESH_MS = 60_000;
/** Cheap library queries refreshed on the grid's schedule; the rest (facets, map,
 * similar photos, trip suggestions…) wait for the slower one, then everything at the end. */
const GRID_QUERIES = new Set(["assets", "timeline", "asset"]);

/**
 * Keeps library views fresh while background tasks run, without competing with the
 * import: a 100 000-file import takes hours, and each refresh re-runs the visible
 * queries (facets alone take ~0.5 s on a large library). Everything reloads once
 * the work finishes.
 */
export function useLibraryRefresh() {
  const queryClient = useQueryClient();
  const tasks = useActiveTasks();
  const roots = useStorageRoots();
  const lastRootsRefresh = useRef(0);
  const lastGridRefresh = useRef(0);
  const lastViewsRefresh = useRef(0);
  const wasActive = useRef(false);
  const lastScans = useRef<string | null>(null);
  const active = (tasks.data?.length ?? 0) > 0;

  // A root finished processing (possibly between polls): reload the grid.
  const scans = roots.data?.map((root) => `${root.id}:${root.last_scanned_at}`).join("|");
  useEffect(() => {
    if (scans === undefined) return;
    if (lastScans.current !== null && lastScans.current !== scans) {
      void queryClient.invalidateQueries({ queryKey: queryKeys.library });
    }
    lastScans.current = scans;
  }, [scans, queryClient]);

  useEffect(() => {
    if (!tasks.data) return;
    const now = Date.now();
    const finished = !active && wasActive.current;
    wasActive.current = active;
    if (finished) {
      void queryClient.invalidateQueries({ queryKey: queryKeys.storageRoots });
      void queryClient.invalidateQueries({ queryKey: queryKeys.library });
      return;
    }
    if (!active) return;
    if (now - lastRootsRefresh.current >= ROOTS_REFRESH_MS) {
      lastRootsRefresh.current = now;
      void queryClient.invalidateQueries({ queryKey: queryKeys.storageRoots });
    }
    if (now - lastViewsRefresh.current >= VIEWS_REFRESH_MS) {
      lastViewsRefresh.current = lastGridRefresh.current = now;
      void queryClient.invalidateQueries({ queryKey: queryKeys.library });
    } else if (now - lastGridRefresh.current >= GRID_REFRESH_MS) {
      lastGridRefresh.current = now;
      void queryClient.invalidateQueries({
        queryKey: queryKeys.library,
        predicate: (query) => GRID_QUERIES.has(String(query.queryKey[1])),
      });
    }
  }, [tasks.dataUpdatedAt, tasks.data, active, queryClient]);
}

export function useAssets(query: AssetQuery) {
  const conn = useConnection();
  return useInfiniteQuery({
    queryKey: queryKeys.assets(query),
    queryFn: ({ pageParam }) =>
      api.listAssets(requireConnection(conn), query, { cursor: pageParam, limit: ASSET_PAGE_SIZE }),
    initialPageParam: null as string | null,
    getNextPageParam: (page) => page.next_cursor,
    enabled: conn !== null,
    placeholderData: (previous) => previous,
  });
}

export function useAsset(id: number | null) {
  const conn = useConnection();
  return useQuery({
    queryKey: queryKeys.asset(id ?? 0),
    queryFn: () => api.getAsset(requireConnection(conn), id!),
    enabled: conn !== null && id !== null,
  });
}

export function useFacets() {
  const conn = useConnection();
  return useQuery({
    queryKey: queryKeys.facets,
    queryFn: () => api.getFacets(requireConnection(conn)),
    enabled: conn !== null,
  });
}

export function useTimeline(query: AssetQuery, granularity: "year" | "month" | "day") {
  const conn = useConnection();
  return useQuery({
    queryKey: queryKeys.timeline(query, granularity),
    queryFn: () => api.getTimeline(requireConnection(conn), query, granularity),
    enabled: conn !== null,
  });
}

export function useMapPoints(query: AssetQuery) {
  const conn = useConnection();
  return useQuery({
    queryKey: queryKeys.map(query),
    queryFn: () => api.getMapPoints(requireConnection(conn), query),
    enabled: conn !== null,
  });
}

export function useTags() {
  const conn = useConnection();
  return useQuery({
    queryKey: queryKeys.tags,
    queryFn: () => api.listTags(requireConnection(conn)),
    enabled: conn !== null,
  });
}

/** Edit one asset; the detail view updates immediately, lists refresh afterwards. */
export function useUpdateAsset() {
  const conn = useConnection();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ id, changes }: { id: number; changes: AssetUpdate }) =>
      api.updateAsset(requireConnection(conn), id, changes),
    onSuccess: (detail: AssetDetail) => {
      queryClient.setQueryData(queryKeys.asset(detail.id), detail);
      void queryClient.invalidateQueries({
        queryKey: queryKeys.library,
        predicate: (query) => query.queryKey[1] !== "asset",
      });
    },
  });
}

export function useEditState(id: number | null) {
  const conn = useConnection();
  return useQuery({
    queryKey: queryKeys.edit(id ?? 0),
    queryFn: () => api.getEdit(requireConnection(conn), id!),
    enabled: conn !== null && id !== null,
    staleTime: Infinity, // only this session changes it
  });
}

/**
 * Saving, undoing and redoing edits. They resolve with the new state and keep the
 * cache current; they are plain functions, so a save still lands after its caller
 * unmounted (e.g. when moving to the next photo mid-edit).
 */
export function useEditActions() {
  const conn = useConnection();
  const queryClient = useQueryClient();
  return useMemo(() => {
    const settle = (state: EditState) => {
      queryClient.setQueryData(queryKeys.edit(state.asset_id), state);
      void queryClient.invalidateQueries({ queryKey: queryKeys.asset(state.asset_id) });
      return state;
    };
    const run = (call: (conn: BackendConnection) => Promise<EditState>) =>
      call(requireConnection(conn)).then(settle);
    return {
      save: (id: number, recipe: EditRecipe) => run((c) => api.saveEdit(c, id, recipe)),
      undo: (id: number) => run((c) => api.undoEdit(c, id)),
      redo: (id: number) => run((c) => api.redoEdit(c, id)),
      select: (id: number, editId: number | null) => run((c) => api.selectEdit(c, id, editId)),
    };
  }, [conn, queryClient]);
}

export function useVideoEdit(id: number | null, enabled = true) {
  const conn = useConnection();
  return useQuery({
    queryKey: queryKeys.videoEdit(id ?? 0),
    queryFn: () => api.getVideoEdit(requireConnection(conn), id!),
    enabled: enabled && conn !== null && id !== null,
    staleTime: Infinity, // only this session changes it
  });
}

/** Saves a video's edit; like photo edits, it still lands after the caller unmounted. */
export function useSaveVideoEdit() {
  const conn = useConnection();
  const queryClient = useQueryClient();
  return useMemo(
    () => (id: number, recipe: VideoRecipe) =>
      api.saveVideoEdit(requireConnection(conn), id, recipe).then((state: VideoEditState) => {
        queryClient.setQueryData(queryKeys.videoEdit(state.asset_id), state);
        void queryClient.invalidateQueries({ queryKey: queryKeys.asset(state.asset_id) });
        return state;
      }),
    [conn, queryClient],
  );
}

export function useCollections() {
  const conn = useConnection();
  return useQuery({
    queryKey: queryKeys.collections,
    queryFn: async () => (await api.listCollections(requireConnection(conn))).items,
    enabled: conn !== null,
  });
}

export function useTripSuggestions(enabled = true) {
  const conn = useConnection();
  return useQuery({
    queryKey: queryKeys.tripSuggestions,
    queryFn: async () => (await api.suggestTrips(requireConnection(conn))).items,
    enabled: enabled && conn !== null,
  });
}

export function useCollection(id: number | null) {
  const conn = useConnection();
  return useQuery({
    queryKey: queryKeys.collection(id ?? 0),
    queryFn: () => api.getCollection(requireConnection(conn), id!),
    enabled: conn !== null && id !== null,
  });
}

/** Where a collection's photos were taken, in capture order, grouped into stops. */
export function useCollectionRoute(id: number, enabled = true) {
  const conn = useConnection();
  return useQuery({
    queryKey: queryKeys.collectionRoute(id),
    queryFn: () => api.getCollectionRoute(requireConnection(conn), id),
    enabled: enabled && conn !== null,
  });
}

/**
 * Changes to collections. Each refreshes the collections (list, suggestions, the one
 * changed); they resolve with the API's answer.
 */
export function useCollectionActions() {
  const conn = useConnection();
  const queryClient = useQueryClient();
  return useMemo(() => {
    const refresh = <T,>(result: T) => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.collections });
      return result;
    };
    const c = () => requireConnection(conn);
    return {
      create: (body: CollectionCreate) => api.createCollection(c(), body).then(refresh),
      update: (id: number, body: CollectionUpdate) =>
        api.updateCollection(c(), id, body).then(refresh),
      remove: (id: number) => api.deleteCollection(c(), id).then(refresh),
      add: (id: number, assetIds: number[]) =>
        api.addToCollection(c(), id, assetIds).then(refresh),
      removeItems: (id: number, assetIds: number[]) =>
        api.removeFromCollection(c(), id, assetIds).then(refresh),
      reorder: (id: number, assetIds: number[]) =>
        api.reorderCollection(c(), id, assetIds).then(refresh),
      caption: (id: number, assetId: number, caption: string | null) =>
        api.setCaption(c(), id, assetId, caption).then(refresh),
    };
  }, [conn, queryClient]);
}

/** Settings applied to many photos: every view of them (and their edits) refreshes. */
export function useApplyEdits() {
  const conn = useConnection();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: EditBatch) => api.applyEdits(requireConnection(conn), body),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: queryKeys.library }),
  });
}

export function useStartExport() {
  const conn = useConnection();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: ExportRequest) => api.startExport(requireConnection(conn), body),
    onSuccess: (status) => {
      queryClient.setQueryData(queryKeys.export(status.task.id), status);
      void queryClient.invalidateQueries({ queryKey: queryKeys.tasks });
    },
  });
}

/** An export's progress, polled until it has finished. */
export function useExportStatus(taskId: number | null) {
  const conn = useConnection();
  return useQuery({
    queryKey: queryKeys.export(taskId ?? 0),
    queryFn: () => api.getExport(requireConnection(conn), taskId!),
    enabled: conn !== null && taskId !== null,
    refetchInterval: (query) => {
      const status = query.state.data?.task.status;
      return status === "pending" || status === "running" ? 500 : false;
    },
  });
}

/** Refresh lists, the timeline and the map (e.g. after edits changed thumbnails). */
export function useRefreshLibraryLists() {
  const queryClient = useQueryClient();
  return () =>
    queryClient.invalidateQueries({
      queryKey: queryKeys.library,
      predicate: (query) => !["asset", "edit", "video-edit"].includes(String(query.queryKey[1])),
    });
}

export function useBatchUpdate() {
  const conn = useConnection();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: AssetBatchUpdate) => api.batchUpdate(requireConnection(conn), body),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: queryKeys.library }),
  });
}

/** Ids of every asset matching a query (for "select all"). */
export function useSelectAll() {
  const conn = useConnection();
  return async (query: AssetQuery) => (await api.listAssetIds(requireConnection(conn), query)).ids;
}

export function useSettings() {
  const conn = useConnection();
  return useQuery({
    queryKey: queryKeys.settings,
    queryFn: () => api.getSettings(requireConnection(conn)),
    enabled: conn !== null,
  });
}

export function useUpdateSettings() {
  const conn = useConnection();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: AppSettingsUpdate) => api.updateSettings(requireConnection(conn), body),
    onSuccess: (settings) => {
      queryClient.setQueryData(queryKeys.settings, settings);
      // Enabling AI or changing the model starts background work.
      void queryClient.invalidateQueries({ queryKey: queryKeys.aiStatus });
      void queryClient.invalidateQueries({ queryKey: queryKeys.tasks });
    },
  });
}

export interface SimilarParams {
  window_minutes: number;
  similarity: number;
  pending_only: boolean;
  /** Groups to fetch (newest first). */
  limit: number;
}

export function useSimilarGroups(params: SimilarParams) {
  const conn = useConnection();
  return useQuery({
    queryKey: queryKeys.similarGroups(params),
    queryFn: () => api.listSimilarGroups(requireConnection(conn), params),
    enabled: conn !== null,
    placeholderData: (previous) => previous,
  });
}

export function useSuspects(pendingOnly: boolean) {
  const conn = useConnection();
  return useQuery({
    queryKey: queryKeys.suspects(pendingOnly),
    queryFn: () => api.listSuspects(requireConnection(conn), pendingOnly),
    enabled: conn !== null,
    placeholderData: (previous) => previous,
  });
}

/** Shell actions from the info panel: Google Maps at a location, a file in Explorer. */
export function useShellActions() {
  const conn = useConnection();
  return {
    openMap: useMutation({
      mutationFn: (assetId: number) => api.openAssetMap(requireConnection(conn), assetId),
    }),
    reveal: useMutation({
      mutationFn: (fileId: number) => api.revealFile(requireConnection(conn), fileId),
    }),
  };
}

export function useDuplicates(kind: DuplicateKind = "identical") {
  const conn = useConnection();
  return useQuery({
    queryKey: queryKeys.duplicates(kind),
    queryFn: () => api.listDuplicates(requireConnection(conn), kind),
    enabled: conn !== null,
  });
}

export function useDuplicateActions() {
  const conn = useConnection();
  const queryClient = useQueryClient();
  return {
    merge: useMutation({
      mutationFn: (body: MergeRequest) => api.mergeDuplicates(requireConnection(conn), body),
      onSuccess: (_result, body) => {
        // The merged groups go at once; the report is worked out again in the background
        // (finding copies takes seconds on a large library).
        const merged = new Set(body.groups.flatMap((group) => group.asset_ids));
        queryClient.setQueryData<DuplicateReport>(
          queryKeys.duplicates(body.kind ?? "identical"),
          (report) =>
            report && {
              ...report,
              groups: report.groups.filter(
                (group) => !group.assets.some((entry) => merged.has(entry.asset.id)),
              ),
              group_count: Math.max(0, report.group_count - body.groups.length),
            },
        );
        return queryClient.invalidateQueries({ queryKey: queryKeys.library });
      },
    }),
    mergeAll: useMutation({
      mutationFn: (kind: DuplicateKind = "identical") =>
        api.mergeAllDuplicates(requireConnection(conn), kind),
      // Progress shows in the status bar; views refresh when the task ends.
      onSuccess: () => queryClient.invalidateQueries({ queryKey: queryKeys.tasks }),
    }),
    reveal: useMutation({
      mutationFn: (fileId: number) => api.revealFile(requireConnection(conn), fileId),
    }),
  };
}

export function useBackups() {
  const conn = useConnection();
  return useQuery({
    queryKey: queryKeys.backups,
    queryFn: () => api.listBackups(requireConnection(conn)),
    enabled: conn !== null,
  });
}

export function useBackupActions() {
  const conn = useConnection();
  const queryClient = useQueryClient();
  const refresh = () => queryClient.invalidateQueries({ queryKey: queryKeys.backups });
  return {
    create: useMutation({
      mutationFn: () => api.createBackup(requireConnection(conn)),
      onSuccess: refresh,
    }),
    restore: useMutation({
      mutationFn: (body: RestoreRequest) => api.restoreBackup(requireConnection(conn), body),
      // Everything may have changed: refetch every query.
      onSuccess: () => queryClient.invalidateQueries(),
    }),
    reveal: useMutation({
      mutationFn: (name: string) => api.revealBackup(requireConnection(conn), name),
    }),
  };
}

/** Where thumbnails and previews are kept and how much space they take. */
export function useCacheStatus() {
  const conn = useConnection();
  return useQuery({
    queryKey: queryKeys.cache,
    queryFn: () => api.getCacheStatus(requireConnection(conn)),
    enabled: conn !== null,
  });
}

export function useMoveCache() {
  const conn = useConnection();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (folder: string) => api.moveCache(requireConnection(conn), folder),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: queryKeys.tasks }),
  });
}

/** Local AI and cloud configuration; polled quickly while AI work is running. */
export function useAiStatus() {
  const conn = useConnection();
  const tasks = useActiveTasks();
  const aiActive = tasks.data?.some((task) => task.kind.startsWith("ai_")) ?? false;
  return useQuery({
    queryKey: queryKeys.aiStatus,
    queryFn: () => api.getAiStatus(requireConnection(conn)),
    enabled: conn !== null,
    refetchInterval: aiActive ? 2000 : 15_000,
  });
}

export function useAiSearch(text: string, query: AssetQuery, enabled: boolean) {
  const conn = useConnection();
  return useQuery({
    queryKey: queryKeys.aiSearch(text, query),
    queryFn: () => api.aiSearch(requireConnection(conn), text, query),
    enabled: conn !== null && enabled && text.trim().length > 0,
    placeholderData: (previous) => previous,
    retry: false,
  });
}

export function useSimilar(id: number | null, query: AssetQuery) {
  const conn = useConnection();
  return useQuery({
    queryKey: queryKeys.similar(id ?? 0, query),
    queryFn: () => api.similarAssets(requireConnection(conn), id!, query),
    enabled: conn !== null && id !== null,
    retry: false,
  });
}

export function useAiActions() {
  const conn = useConnection();
  const queryClient = useQueryClient();
  const refresh = () => {
    void queryClient.invalidateQueries({ queryKey: queryKeys.aiStatus });
    void queryClient.invalidateQueries({ queryKey: queryKeys.tasks });
  };
  return {
    download: useMutation({
      mutationFn: () => api.downloadAiModel(requireConnection(conn)),
      onSuccess: refresh,
    }),
    index: useMutation({
      mutationFn: () => api.indexAi(requireConnection(conn)),
      onSuccess: refresh,
    }),
    saveKey: useMutation({
      mutationFn: (key: string) => api.saveCloudKey(requireConnection(conn), key),
      onSuccess: refresh,
    }),
    deleteKey: useMutation({
      mutationFn: () => api.deleteCloudKey(requireConnection(conn)),
      onSuccess: refresh,
    }),
    test: useMutation({ mutationFn: () => api.testCloud(requireConnection(conn)) }),
  };
}

export function useAnalyses(assetId: number | null) {
  const conn = useConnection();
  return useQuery({
    queryKey: queryKeys.analyses(assetId ?? 0),
    queryFn: () => api.listAnalyses(requireConnection(conn), assetId!),
    enabled: conn !== null && assetId !== null,
  });
}

export function useCloudPreview() {
  const conn = useConnection();
  return useMutation({
    mutationFn: (body: CloudRequest) => api.previewCloud(requireConnection(conn), body),
  });
}

export function useCloudAnalyze() {
  const conn = useConnection();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: CloudRequest) => api.analyzeCloud(requireConnection(conn), body),
    onSuccess: (result: AnalysisResult) => {
      for (const id of result.asset_ids) {
        void queryClient.invalidateQueries({ queryKey: queryKeys.analyses(id) });
      }
    },
  });
}
