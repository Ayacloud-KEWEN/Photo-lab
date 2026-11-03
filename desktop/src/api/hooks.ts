import {
  useInfiniteQuery,
  useMutation,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query";
import { useEffect, useRef } from "react";

import { useBackendStatus } from "./backend-context";
import { api, type BackendConnection } from "./client";
import type { AssetQuery } from "./query";
import type {
  AppSettingsUpdate,
  AssetBatchUpdate,
  AssetDetail,
  AssetUpdate,
  StorageRootCreate,
  Task,
} from "./types";

/** Everything under `library` derives from assets and is refreshed together. */
export const queryKeys = {
  health: ["health"] as const,
  storageRoots: ["storage-roots"] as const,
  tasks: ["tasks", "active"] as const,
  settings: ["settings"] as const,
  library: ["library"] as const,
  assets: (query: AssetQuery) => ["library", "assets", query] as const,
  facets: ["library", "facets"] as const,
  tags: ["library", "tags"] as const,
  timeline: (query: AssetQuery, granularity: string) =>
    ["library", "timeline", granularity, query] as const,
  map: (query: AssetQuery) => ["library", "map", query] as const,
  asset: (id: number) => ["library", "asset", id] as const,
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

/**
 * Keeps library views fresh while background tasks run: root statistics follow
 * every poll, the photo grid refreshes every few seconds and once work finishes.
 */
export function useLibraryRefresh() {
  const queryClient = useQueryClient();
  const tasks = useActiveTasks();
  const roots = useStorageRoots();
  const lastGridRefresh = useRef(0);
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
    if (active || wasActive.current) {
      void queryClient.invalidateQueries({ queryKey: queryKeys.storageRoots });
    }
    if ((active && now - lastGridRefresh.current > 4000) || (!active && wasActive.current)) {
      lastGridRefresh.current = now;
      void queryClient.invalidateQueries({ queryKey: queryKeys.library });
    }
    wasActive.current = active;
  }, [tasks.data, active, queryClient]);
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
    onSuccess: (settings) => queryClient.setQueryData(queryKeys.settings, settings),
  });
}
