import { useEffect, useRef, useState } from "react";

import { api, type BackendConnection } from "@/api/client";
import type { EditRecipe } from "@/api/types";

import { recipeKey } from "./recipe";

export interface DevelopPreviewState {
  /** Object URL of the latest render. */
  src: string | undefined;
  histogram: number[][] | null;
  failed: boolean;
}

/**
 * Renders ``recipe`` on the backend while sliders move. At most one request is in
 * flight; when it returns, the latest recipe is rendered next, so the image keeps up
 * with the slider without a queue of stale renders.
 */
export function useDevelopPreview(
  conn: BackendConnection | null,
  assetId: number,
  recipe: EditRecipe,
  edge: number,
): DevelopPreviewState {
  const [state, setState] = useState<DevelopPreviewState>({
    src: undefined,
    histogram: null,
    failed: false,
  });
  const wanted = useRef<{ key: string; recipe: EditRecipe }>({ key: "", recipe });
  const shown = useRef("");
  const busy = useRef(false);
  const controller = useRef<AbortController | null>(null);
  const pump = useRef<() => void>(() => undefined);

  pump.current = () => {
    if (!conn || busy.current) return;
    const job = wanted.current;
    if (job.key === shown.current) return;
    busy.current = true;
    const abort = new AbortController();
    controller.current = abort;
    api
      .renderDevelopPreview(conn, assetId, job.recipe, edge, abort.signal)
      .then((preview) => {
        shown.current = job.key;
        const src = URL.createObjectURL(preview.image);
        setState({ src, histogram: preview.histogram, failed: false });
      })
      .catch((error: unknown) => {
        if (abort.signal.aborted) return;
        shown.current = job.key; // do not retry the same recipe in a loop
        console.warn("develop preview failed", error);
        setState((previous) => ({ ...previous, failed: true }));
      })
      .finally(() => {
        if (controller.current !== abort) return; // superseded by a cleanup
        busy.current = false;
        pump.current();
      });
  };

  const key = `${edge}:${recipeKey(recipe)}`;
  const connected = conn !== null;
  useEffect(() => {
    wanted.current = { key, recipe };
    pump.current();
    // eslint-disable-next-line react-hooks/exhaustive-deps -- `recipe` is captured by `key`
  }, [key, connected]);

  useEffect(
    () => () => {
      // Also runs for React's development-mode remount: leave a clean slate.
      controller.current?.abort();
      controller.current = null;
      busy.current = false;
      shown.current = "";
    },
    [],
  );
  // Each render's object URL is released once a newer one replaced it (or on unmount).
  useEffect(() => {
    const src = state.src;
    return () => {
      if (src) URL.revokeObjectURL(src);
    };
  }, [state.src]);

  return state;
}
