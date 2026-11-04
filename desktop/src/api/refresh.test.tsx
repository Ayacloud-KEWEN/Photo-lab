import { act, render } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { useAssets, useFacets, useLibraryRefresh } from "@/api/hooks";
import type { Task } from "@/api/types";
import { makeAsset, Providers, stubBackend } from "@/test/backend";

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

const ingest: Task = {
  id: 1, kind: "ingest_storage_root", status: "running", storage_root_id: 1,
  progress_current: 10, progress_total: 1000, attempts: 1, max_attempts: 3,
  cancel_requested: false, error: null, result: null, created_at: "2026-11-04T10:00:00Z",
  updated_at: "2026-11-04T10:00:00Z", started_at: "2026-11-04T10:00:00Z", finished_at: null,
}; // prettier-ignore

function Views() {
  useLibraryRefresh();
  useAssets({});
  useFacets();
  return null;
}

describe("useLibraryRefresh", () => {
  it("refreshes the grid every 15 s and heavier views every minute during an import", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    const { requests } = stubBackend({ assets: [makeAsset(1)], tasks: [ingest] });
    render(
      <Providers>
        <Views />
      </Providers>,
    );
    const count = (path: string) => requests.filter((r) => r.url.pathname === path).length;
    await act(() => vi.advanceTimersByTimeAsync(2_000));
    const assets = count("/api/v1/assets");
    const facets = count("/api/v1/assets/facets");
    const roots = count("/api/v1/storage-roots");

    await act(() => vi.advanceTimersByTimeAsync(30_000));
    expect(count("/api/v1/assets") - assets).toBe(2); // every 15 s, not every 4 s
    expect(count("/api/v1/assets/facets") - facets).toBe(0);
    expect(count("/api/v1/storage-roots") - roots).toBeLessThanOrEqual(7); // ~every 5 s

    await act(() => vi.advanceTimersByTimeAsync(30_000));
    expect(count("/api/v1/assets/facets") - facets).toBe(1); // once a minute
  });
});
