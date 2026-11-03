import { useCallback, useEffect, useMemo, useRef, useState, type KeyboardEvent } from "react";

import { useAssets, useBatchUpdate, useSelectAll } from "@/api/hooks";
import type { AssetQuery } from "@/api/query";
import type { AssetSummary } from "@/api/types";

import {
  emptySelection,
  pruneSelection,
  selectAll,
  selectItem,
  type Modifiers,
  type SelectionState,
} from "./selection";
import { useLibraryState } from "./state";

/**
 * Everything a photo wall page needs: paged assets, multi-selection, opening the
 * viewer, and keyboard shortcuts (0–5 rate, F favorite, Ctrl+A, Esc).
 */
export function useWall(query: AssetQuery, onFocus: (id: number | null) => void) {
  const assets = useAssets(query);
  const items = useMemo<AssetSummary[]>(
    () => assets.data?.pages.flatMap((page) => page.items) ?? [],
    [assets.data],
  );
  const order = useMemo(() => items.map((item) => item.id), [items]);
  const orderRef = useRef(order);
  orderRef.current = order;

  const [selection, setSelection] = useState<SelectionState>(emptySelection);
  const [error, setError] = useState<unknown>(null);
  const { openViewer } = useLibraryState();
  const batch = useBatchUpdate();
  const fetchAllIds = useSelectAll();

  // A new query starts with an empty selection.
  const queryKey = JSON.stringify(query);
  useEffect(() => setSelection(emptySelection), [queryKey]);

  // Items can disappear after edits (e.g. un-favoriting under a favorites filter).
  const loadedAll = !assets.hasNextPage;
  useEffect(() => {
    if (loadedAll) setSelection((state) => pruneSelection(state, new Set(order)));
  }, [order, loadedAll]);

  useEffect(() => onFocus(selection.focused), [selection.focused, onFocus]);

  const select = useCallback(
    (id: number, modifiers: Modifiers) =>
      setSelection((state) => selectItem(state, id, orderRef.current, modifiers)),
    [],
  );
  const open = useCallback((id: number) => openViewer(orderRef.current, id), [openViewer]);
  const clearSelection = useCallback(() => setSelection(emptySelection), []);

  const { hasNextPage, isFetchingNextPage, fetchNextPage } = assets;
  const loadMore = useCallback(() => {
    if (hasNextPage && !isFetchingNextPage) void fetchNextPage();
  }, [hasNextPage, isFetchingNextPage, fetchNextPage]);

  const targets = (): number[] => {
    if (selection.selected.size > 0) return [...selection.selected];
    return selection.focused !== null ? [selection.focused] : [];
  };

  const onKeyDown = (event: KeyboardEvent<HTMLDivElement>) => {
    if (event.altKey) return;
    const key = event.key.toLowerCase();
    if ((event.ctrlKey || event.metaKey) && key === "a") {
      event.preventDefault();
      fetchAllIds(query)
        .then((ids) => setSelection(selectAll(ids, selection.focused)))
        .catch(setError);
      return;
    }
    if (event.ctrlKey || event.metaKey) return;
    if (key === "escape") {
      clearSelection();
      return;
    }
    const ids = targets();
    if (ids.length === 0) return;
    if (/^[0-5]$/.test(key)) {
      event.preventDefault();
      batch.mutateAsync({ asset_ids: ids, rating: Number(key) }).catch(setError);
    } else if (key === "f") {
      event.preventDefault();
      const byId = new Map(items.map((item) => [item.id, item]));
      const allFavorite = ids.every((id) => byId.get(id)?.is_favorite);
      batch.mutateAsync({ asset_ids: ids, is_favorite: !allFavorite }).catch(setError);
    }
  };

  return {
    assets,
    items,
    selection,
    selectedIds: [...selection.selected],
    select,
    open,
    clearSelection,
    loadMore,
    onKeyDown,
    error,
    setError,
  };
}
