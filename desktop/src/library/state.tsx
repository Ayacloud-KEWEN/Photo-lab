import { createContext, useCallback, useContext, useMemo, useState, type ReactNode } from "react";

import type { AssetQuery, QueryPatch } from "@/api/query";
import type { AnalysisKind } from "@/api/types";

/**
 * State shared across pages: filters (library, timeline, map, AI search), the
 * full-screen viewer, "find similar" and the cloud analysis dialog.
 */
interface LibraryState {
  query: AssetQuery;
  setQuery: (update: AssetQuery | ((current: AssetQuery) => AssetQuery)) => void;
  viewer: ViewerState | null;
  openViewer: (ids: readonly number[], id: number) => void;
  closeViewer: () => void;
  /** Asset whose look-alikes the AI search page shows (null: text search). */
  similarTo: SimilarRequest | null;
  findSimilar: (id: number | null) => void;
  cloudRequest: CloudDialogRequest | null;
  openCloud: (kind: AnalysisKind, assetIds: number[]) => void;
  closeCloud: () => void;
}

export interface ViewerState {
  ids: readonly number[];
  index: number;
  /** Changes on every open, so the viewer restarts even for the same photo. */
  nonce: number;
}

export interface SimilarRequest {
  id: number;
  /** Changes on every request, so the app navigates even for the same photo. */
  nonce: number;
}

export interface CloudDialogRequest {
  kind: AnalysisKind;
  assetIds: number[];
  nonce: number;
}

const LibraryContext = createContext<LibraryState | null>(null);

export function LibraryStateProvider({ children }: { children: ReactNode }) {
  const [query, setQuery] = useState<AssetQuery>({});
  const [viewer, setViewer] = useState<ViewerState | null>(null);
  const [similarTo, setSimilarTo] = useState<SimilarRequest | null>(null);
  const [cloudRequest, setCloudRequest] = useState<CloudDialogRequest | null>(null);

  const openViewer = useCallback((ids: readonly number[], id: number) => {
    const index = ids.indexOf(id);
    setViewer({ ids, index: index < 0 ? 0 : index, nonce: Date.now() });
  }, []);
  const closeViewer = useCallback(() => setViewer(null), []);
  const findSimilar = useCallback(
    (id: number | null) => setSimilarTo(id === null ? null : { id, nonce: Date.now() }),
    [],
  );
  const openCloud = useCallback(
    (kind: AnalysisKind, assetIds: number[]) =>
      setCloudRequest({ kind, assetIds, nonce: Date.now() }),
    [],
  );
  const closeCloud = useCallback(() => setCloudRequest(null), []);

  const value = useMemo(
    () => ({
      query,
      setQuery,
      viewer,
      openViewer,
      closeViewer,
      similarTo,
      findSimilar,
      cloudRequest,
      openCloud,
      closeCloud,
    }),
    [query, viewer, openViewer, closeViewer, similarTo, findSimilar, cloudRequest, openCloud, closeCloud],
  );
  return <LibraryContext.Provider value={value}>{children}</LibraryContext.Provider>;
}

export function useLibraryState(): LibraryState {
  const state = useContext(LibraryContext);
  if (!state) throw new Error("useLibraryState must be used inside LibraryStateProvider");
  return state;
}

/** Remove keys whose value is undefined/empty so query keys stay stable. */
export function cleanQuery(query: QueryPatch): AssetQuery {
  return Object.fromEntries(
    Object.entries(query).filter(
      ([, value]) =>
        value !== undefined && value !== "" && !(Array.isArray(value) && value.length === 0),
    ),
  ) as AssetQuery;
}
