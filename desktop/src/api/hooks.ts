import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { useBackendStatus } from "./backend-context";
import { api, type BackendConnection } from "./client";
import type { StorageRootCreate } from "./types";

export const queryKeys = {
  health: ["health"] as const,
  storageRoots: ["storage-roots"] as const,
};

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
  });
}

export function useCreateStorageRoot() {
  const conn = useConnection();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: StorageRootCreate) => api.createStorageRoot(requireConnection(conn), body),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: queryKeys.storageRoots }),
  });
}

export function useDeleteStorageRoot() {
  const conn = useConnection();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (id: number) => api.deleteStorageRoot(requireConnection(conn), id),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: queryKeys.storageRoots }),
  });
}
