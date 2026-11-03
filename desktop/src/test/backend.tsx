import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";
import { vi } from "vitest";

import { StaticBackendProvider } from "@/api/backend-context";
import type {
  AssetDetail,
  AssetSummary,
  EditRecipe,
  EditState,
  StorageRoot,
  VideoRecipe,
} from "@/api/types";
import { DEFAULT_VIDEO_RECIPE } from "@/components/develop/VideoWorkspace";
import { DEFAULT_RECIPE, recipeKey } from "@/components/develop/recipe";
import { TooltipProvider } from "@/components/ui/tooltip";
import type { BackendStatus } from "@/lib/backend";
import { LibraryStateProvider } from "@/library/state";

export const ready: BackendStatus = { state: "ready", baseUrl: "http://127.0.0.1:1", token: "t" };

export const root: StorageRoot = {
  id: 7,
  path: "D:\\Photos",
  display_name: "Photos",
  status: "pending_scan",
  is_available: true,
  volume_serial: "1234ABCD",
  volume_label: "Data",
  last_scanned_at: null,
  created_at: "2026-11-03T08:00:00.000Z",
  updated_at: "2026-11-03T08:00:00.000Z",
  stats: { file_count: 0, asset_count: 0, pending_count: 0, error_count: 0, missing_count: 0 },
};

export function makeAsset(id: number, overrides: Partial<AssetSummary> = {}): AssetSummary {
  return {
    id,
    media_type: "photo",
    capture_time: `2024-06-${String(10 - (id % 9)).padStart(2, "0")}T09:30:00`,
    rating: 0,
    is_favorite: false,
    file_name: `IMG_${id}.JPG`,
    formats: ["JPG"],
    width: 600,
    height: 400,
    duration_ms: null,
    is_live: false,
    is_edited: false,
    cover_extension: "jpg",
    rendition_version: `v${id}`,
    ...overrides,
  };
}

export function makeDetail(summary: AssetSummary): AssetDetail {
  return {
    id: summary.id,
    uuid: `uuid-${summary.id}`,
    media_type: summary.media_type,
    capture_time: summary.capture_time,
    rating: summary.rating,
    is_favorite: summary.is_favorite,
    rating_source: null,
    notes: null,
    tags: [],
    cover_file_id: summary.id * 10,
    motion_file_id: summary.is_live ? summary.id * 10 + 1 : null,
    is_edited: summary.is_edited,
    rendition_version: summary.rendition_version,
    metadata: { width: summary.width, height: summary.height },
    location: null,
    files: [
      {
        id: summary.id * 10,
        storage_root_id: 7,
        role: "primary",
        path: `D:\\Photos\\${summary.file_name}`,
        relative_path: summary.file_name,
        size_bytes: 1000,
        status: "present",
        ingest_state: "done",
        ingest_error: null,
        fingerprint: "xxh128:abc",
      },
      ...(summary.is_live
        ? [
            {
              id: summary.id * 10 + 1,
              storage_root_id: 7,
              role: "companion" as const,
              path: `D:\\Photos\\IMG_${summary.id}.MOV`,
              relative_path: `IMG_${summary.id}.MOV`,
              size_bytes: 1000,
              status: "present" as const,
              ingest_state: "done" as const,
              ingest_error: null,
              fingerprint: "xxh128:def",
            },
          ]
        : []),
    ],
  };
}

export interface Request {
  method: string;
  url: URL;
  body: unknown;
}

/** In-memory fake of the backend endpoints the UI uses; records every request. */
export interface StubOptions {
  roots?: StorageRoot[];
  assets?: AssetSummary[];
  /** Local AI state reported by /ai/status. */
  ai?: { enabled?: boolean; downloaded?: boolean; installed?: boolean };
  /** Cloud behaviour: "ok" (default), "no_vision" or "not_configured". */
  cloud?: "ok" | "no_vision" | "not_configured";
  /** Saved video edits by asset id. */
  videoEdits?: Record<number, Partial<VideoRecipe>>;
}

export function stubBackend(options: StubOptions = {}) {
  let roots = [...(options.roots ?? [])];
  const assets = options.assets ?? [];
  const requests: Request[] = [];
  const json = (body: unknown, status = 200) => Promise.resolve(Response.json(body, { status }));
  let exportRequest: unknown = null;
  const videoEdits = new Map<number, VideoRecipe>(
    Object.entries(options.videoEdits ?? {}).map(([id, recipe]) => [
      Number(id),
      { ...DEFAULT_VIDEO_RECIPE, ...recipe },
    ]),
  );
  // Edit history per asset: saved recipes and the index in effect (-1: the original).
  const edits = new Map<number, { steps: EditRecipe[]; current: number }>();
  const editState = (id: number): EditState => {
    const history = edits.get(id) ?? { steps: [], current: -1 };
    const recipe = history.steps[history.current] ?? DEFAULT_RECIPE;
    return {
      asset_id: id,
      recipe,
      current_edit_id: history.current >= 0 ? history.current + 1 : null,
      steps: history.steps.map((step, index) => ({
        id: index + 1,
        created_at: "2026-11-03T08:00:00.000Z",
        changes: Object.keys(step).filter(
          (key) =>
            JSON.stringify(step[key as keyof EditRecipe]) !==
            JSON.stringify((history.steps[index - 1] ?? DEFAULT_RECIPE)[key as keyof EditRecipe]),
        ),
      })),
      can_undo: history.current >= 0,
      can_redo: history.current < history.steps.length - 1,
      is_edited: recipeKey(recipe) !== recipeKey(DEFAULT_RECIPE),
      source_format: "JPG",
      is_raw: false,
      rendition_version: `v${id}`,
    };
  };

  const fetch = vi.fn((input: string, init?: RequestInit) => {
    const url = new URL(input);
    const method = init?.method ?? "GET";
    const body = init?.body ? JSON.parse(String(init.body)) : undefined;
    requests.push({ method, url, body });
    const path = url.pathname;

    if (path.startsWith("/api/v1/tasks")) return json({ items: [] });
    if (path === "/api/v1/settings") {
      return json({
        map_online_tiles: false,
        ai_enabled: options.ai?.enabled ?? false,
        ai_model: "siglip2-so400m-patch14-384",
        cloud_enabled: options.cloud !== "not_configured",
        cloud_model: "deepseek-flash",
        cloud_base_url: "https://api.deepseek.com",
        cloud_include_location: false,
        ...((body as object | undefined) ?? {}),
      });
    }
    if (path === "/api/v1/ai/status") {
      return json({
        local: {
          installed: options.ai?.installed ?? true,
          device: "cuda",
          device_name: "NVIDIA GeForce RTX 4070 SUPER",
          memory_gb: 12,
          enabled: options.ai?.enabled ?? false,
          model_id: "siglip2-so400m-patch14-384",
          model_downloaded: options.ai?.downloaded ?? false,
          model_loaded: false,
          indexed: assets.length,
          total: assets.length,
          models: [
            {
              id: "siglip2-so400m-patch14-384", display_name: "SigLIP2 so400m/14 @384",
              backend: "siglip2", multilingual: true, approx_download_gb: 4.5,
              downloaded: options.ai?.downloaded ?? false,
            },
          ],
        },
        cloud: {
          enabled: options.cloud !== "not_configured", provider: "deepseek",
          model: "deepseek-flash", base_url: "https://api.deepseek.com",
          has_key: options.cloud !== "not_configured", include_location_default: false,
        },
      }); // prettier-ignore
    }
    if (path === "/api/v1/ai/search" || /\/similar$/.test(path)) {
      const ranked = [...assets].reverse();
      return json({
        items: ranked,
        scores: ranked.map((_, i) => 0.12 - i / 100),
        relevant_count: Math.min(2, ranked.length),
        model_id: "siglip2-so400m-patch14-384",
      });
    }
    if (path === "/api/v1/ai/cloud/preview" || path === "/api/v1/ai/cloud/analyze") {
      const request = body as { asset_ids: number[]; include_location: boolean; text_only: boolean; kind: string };
      if (options.cloud === "not_configured" && path.endsWith("analyze")) {
        return json({ error: { code: "cloud_not_configured", message: "off" } }, 409);
      }
      if (path.endsWith("preview")) {
        return json({
          provider: "deepseek", model: "deepseek-flash", host: "api.deepseek.com",
          image_max_edge: request.text_only ? null : 1024, cached: false,
          items: request.asset_ids.map((id) => ({
            asset_id: id, rendition_version: `v${id}`,
            fields: {
              camera: "Canon EOS R5",
              ...(request.include_location ? { location: "31.20000, 121.40000" } : {}),
            },
          })),
        }); // prettier-ignore
      }
      if (options.cloud === "no_vision" && !request.text_only) {
        return json({ error: { code: "vision_unsupported", message: "no images" } }, 422);
      }
      return json({
        id: 1, kind: request.kind, provider: "deepseek", model: "deepseek-flash",
        language: "zh-CN", vision: !request.text_only, cached: false,
        result: "## 点评\n构图**很好**。", data: null, asset_ids: request.asset_ids,
        input_tokens: 100, output_tokens: 50, created_at: "2026-11-03T08:00:00.000Z",
      }); // prettier-ignore
    }
    if (/\/analyses$/.test(path)) return json([]);
    const videoMatch = /^\/api\/v1\/assets\/(\d+)\/(video-edit|frame-export)$/.exec(path);
    if (videoMatch) {
      const id = Number(videoMatch[1]);
      if (assets.find((asset) => asset.id === id)?.media_type !== "video") {
        return json({ error: { code: "develop_unavailable", message: "not a video" } }, 409);
      }
      if (videoMatch[2] === "frame-export") {
        const { destination } = body as { destination: string };
        return json({ path: `${destination}\\IMG_${id}_00-00.jpg` });
      }
      if (method === "PUT") videoEdits.set(id, body as VideoRecipe);
      const recipe = videoEdits.get(id) ?? DEFAULT_VIDEO_RECIPE;
      return json({
        asset_id: id, recipe, duration_ms: 4000,
        is_edited: JSON.stringify(recipe) !== JSON.stringify(DEFAULT_VIDEO_RECIPE),
        rendition_version: `v${id}`,
      }); // prettier-ignore
    }
    if (path === "/api/v1/edits/batch") {
      const request = body as { asset_ids: number[]; recipe: EditRecipe; fields: (keyof EditRecipe)[] };
      let updated = 0;
      for (const id of request.asset_ids) {
        if (assets.find((asset) => asset.id === id)?.media_type !== "photo") continue;
        const history = edits.get(id) ?? { steps: [], current: -1 };
        const current = history.steps[history.current] ?? DEFAULT_RECIPE;
        const next = { ...current, ...Object.fromEntries(request.fields.map((f) => [f, request.recipe[f]])) };
        history.steps = [...history.steps.slice(0, history.current + 1), next];
        history.current = history.steps.length - 1;
        edits.set(id, history);
        updated += 1;
      }
      return json({ updated, skipped: request.asset_ids.length - updated });
    }
    if (path === "/api/v1/exports" || /^\/api\/v1\/exports\/\d+$/.test(path)) {
      const started = path === "/api/v1/exports";
      const request = (started ? body : exportRequest) as { asset_ids: number[]; destination: string };
      if (started) {
        if (!/^[A-Za-z]:\\/.test(request.destination)) {
          return json({ error: { code: "invalid_path", message: "The folder does not exist" } }, 422);
        }
        exportRequest = request;
      }
      const total = request.asset_ids.length;
      const task = {
        id: 99, kind: "export_assets", status: started ? "pending" : "succeeded",
        storage_root_id: null, progress_current: started ? 0 : total, progress_total: total,
        attempts: 1, max_attempts: 3, cancel_requested: false, error: null, result: null,
        created_at: "2026-11-03T08:00:00.000Z", updated_at: "2026-11-03T08:00:00.000Z",
        started_at: null, finished_at: null,
      }; // prettier-ignore
      const result = started
        ? null
        : { destination: request.destination, exported: total - 1, skipped: 1, failed: [] };
      return json({ task: { ...task, result }, result }, started ? 202 : 200);
    }
    const editMatch = /^\/api\/v1\/assets\/(\d+)\/(edit(?:\/undo|\/redo|\/select)?|develop\/preview)$/.exec(path);
    if (editMatch) {
      const id = Number(editMatch[1]);
      const action = editMatch[2];
      if (assets.find((asset) => asset.id === id)?.media_type !== "photo") {
        return json({ error: { code: "develop_unavailable", message: "not a photo" } }, 409);
      }
      if (action === "develop/preview") {
        const bins = Array.from({ length: 64 }, (_, i) => String(i)).join(",");
        return Promise.resolve(
          new Response(new Blob(["jpeg"], { type: "image/jpeg" }), {
            headers: { "Content-Type": "image/jpeg", "X-Histogram": [bins, bins, bins].join(";") },
          }),
        );
      }
      const history = edits.get(id) ?? { steps: [], current: -1 };
      edits.set(id, history);
      if (action === "edit" && method === "PUT") {
        history.steps = [...history.steps.slice(0, history.current + 1), body as EditRecipe];
        history.current = history.steps.length - 1;
      } else if (action === "edit/undo") {
        history.current = Math.max(-1, history.current - 1);
      } else if (action === "edit/redo") {
        history.current = Math.min(history.steps.length - 1, history.current + 1);
      } else if (action === "edit/select") {
        const editId = (body as { edit_id: number | null }).edit_id;
        history.current = editId === null ? -1 : editId - 1;
      }
      return json(editState(id));
    }
    if (path === "/api/v1/tags") return json([]);
    if (path === "/api/v1/timeline") {
      return json({ granularity: "year", buckets: [{ period: "2024", count: assets.length }] });
    }
    if (path === "/api/v1/assets/facets") {
      return json({
        total: assets.length, photos: assets.length, videos: 0, favorites: 0, with_location: 0,
        cameras: [], lenses: [], formats: [], years: [], tags: [],
      }); // prettier-ignore
    }
    if (path === "/api/v1/assets/ids") return json({ ids: assets.map((asset) => asset.id) });
    if (path === "/api/v1/assets/batch") return json({ updated: (body as { asset_ids: number[] }).asset_ids.length });
    if (path === "/api/v1/assets") return json({ items: assets, next_cursor: null });
    const assetMatch = /^\/api\/v1\/assets\/(\d+)$/.exec(path);
    if (assetMatch) {
      const asset = assets.find((item) => item.id === Number(assetMatch[1]));
      if (!asset) return json({ error: { code: "not_found", message: "nope" } }, 404);
      const detail = makeDetail(asset);
      return json(method === "PATCH" ? { ...detail, ...(body as object) } : detail);
    }
    if (path === "/api/v1/storage-roots") {
      if (method === "POST") {
        roots = [...roots, root];
        return json(root, 201);
      }
      return json({ items: roots });
    }
    if (path.startsWith("/api/v1/storage-roots/") && method === "DELETE") {
      roots = roots.filter((r) => !path.endsWith(`/${r.id}`));
      return Promise.resolve(new Response(null, { status: 204 }));
    }
    return json({ error: { code: "not_found", message: path } }, 404);
  });
  vi.stubGlobal("fetch", fetch);
  return { fetch, requests };
}

export function Providers({
  children,
  status = ready,
}: {
  children: ReactNode;
  status?: BackendStatus;
}) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return (
    <StaticBackendProvider value={status}>
      <QueryClientProvider client={queryClient}>
        <TooltipProvider>
          <LibraryStateProvider>{children}</LibraryStateProvider>
        </TooltipProvider>
      </QueryClientProvider>
    </StaticBackendProvider>
  );
}

/** jsdom does no layout; give elements a size so virtualized lists render rows. */
export function fakeViewport() {
  vi.spyOn(Element.prototype, "clientWidth", "get").mockReturnValue(1000);
  vi.spyOn(Element.prototype, "clientHeight", "get").mockReturnValue(800);
}
