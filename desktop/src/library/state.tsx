import { createContext, useCallback, useContext, useMemo, useState, type ReactNode } from "react";

import type { AssetQuery, QueryPatch } from "@/api/query";

/** Filters shared by the library, timeline and map, plus the full-screen viewer. */
interface LibraryState {
  query: AssetQuery;
  setQuery: (update: AssetQuery | ((current: AssetQuery) => AssetQuery)) => void;
  viewer: ViewerState | null;
  openViewer: (ids: readonly number[], id: number) => void;
  closeViewer: () => void;
}

export interface ViewerState {
  ids: readonly number[];
  index: number;
  /** Changes on every open, so the viewer restarts even for the same photo. */
  nonce: number;
}

const LibraryContext = createContext<LibraryState | null>(null);

export function LibraryStateProvider({ children }: { children: ReactNode }) {
  const [query, setQuery] = useState<AssetQuery>({});
  const [viewer, setViewer] = useState<ViewerState | null>(null);

  const openViewer = useCallback((ids: readonly number[], id: number) => {
    const index = ids.indexOf(id);
    setViewer({ ids, index: index < 0 ? 0 : index, nonce: Date.now() });
  }, []);
  const closeViewer = useCallback(() => setViewer(null), []);

  const value = useMemo(
    () => ({ query, setQuery, viewer, openViewer, closeViewer }),
    [query, viewer, openViewer, closeViewer],
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
