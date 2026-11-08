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
  Task,
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
    cull_flag: "none",
    ...overrides,
  };
}

export function makeDetail(summary: AssetSummary): AssetDetail {
  return {
    id: summary.id,
    uuid: `uuid-${summary.id}`,
    media_type: summary.media_type,
    capture_time: summary.capture_time,
    time_shift_s: 0,
    rating: summary.rating,
    is_favorite: summary.is_favorite,
    rating_source: null,
    notes: null,
    tags: [],
    cover_file_id: summary.id * 10,
    motion_file_id: summary.is_live ? summary.id * 10 + 1 : null,
    live_effect: summary.is_live ? (summary.live_effect ?? "live") : null,
    is_edited: summary.is_edited,
    rendition_version: summary.rendition_version,
    metadata: { width: summary.width, height: summary.height },
    location: null,
    place: null,
    cull_flag: summary.cull_flag,
    quality: null,
    description: null,
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
  ai?: { enabled?: boolean; downloaded?: boolean; installed?: boolean; indexed?: number };
  /** The online map setting. */
  mapOnline?: boolean;
  /** Active background tasks reported by /tasks. */
  tasks?: Task[];
  /** One group of similar photos (asset ids; the second is recommended). */
  similar?: number[];
  /** Likely rejects (asset ids). */
  suspects?: number[];
  /** Groups of duplicate copies (asset ids; the first is the suggested keep). */
  duplicates?: number[][];
  /** Groups of copies in other quality (asset ids; the first is the best picture). */
  copies?: number[][];
  /** Cloud behaviour: "ok" (default), "no_vision" or "not_configured". */
  cloud?: "ok" | "no_vision" | "not_configured";
  /** Saved video edits by asset id. */
  videoEdits?: Record<number, Partial<VideoRecipe>>;
  /** Collections: name, kind and their asset ids (in order). */
  collections?: { name: string; kind?: "album" | "trip"; assetIds?: number[] }[];
  /** MapWeb: its address (none: not set) and whether it answers. */
  mapweb?: { url?: string; down?: boolean };
  /** Where assets were taken (asset id: [lat, lon]); a collection's route has a stop for each. */
  located?: Record<number, [number, number]>;
  /** Cache folder: moved to a custom folder, its drive missing at startup, or a full target. */
  cache?: { folder?: string; missing?: boolean; noSpace?: boolean };
  /** Trip suggestions: date ranges over asset ids. */
  trips?: { start: string; end: string; assetIds: number[]; cities?: string[] }[];
  /** Local vision model: files present, enabled, and what each asset was read as. */
  vlm?: {
    enabled?: boolean;
    installed?: boolean;
    descriptions?: Record<number, Partial<AssetDetail["description"]> & object>;
  };
}

export function stubBackend(options: StubOptions = {}) {
  let roots = [...(options.roots ?? [])];
  const assets = options.assets ?? [];
  const requests: Request[] = [];
  const json = (body: unknown, status = 200) => Promise.resolve(Response.json(body, { status }));
  let exportRequest: unknown = null;
  // Duplicate groups by kind, as the backend reports them (merged ones go away).
  const duplicateGroups: Record<string, number[][]> = {
    identical: [...(options.duplicates ?? [])],
    copies: [...(options.copies ?? [])],
  };
  // Collections, as the backend keeps them.
  const collections = new Map<number, CollectionState>(
    (options.collections ?? []).map((collection, index) => [
      index + 1,
      {
        id: index + 1, name: collection.name, kind: collection.kind ?? "album",
        description: null, place: null, start_date: null, end_date: null, cover: null,
        items: (collection.assetIds ?? []).map((id) => ({ id, caption: null })),
      },
    ]),
  ); // prettier-ignore
  const collectionJson = (state: CollectionState) => {
    const items = state.items
      .map((item) => ({ asset: assets.find((a) => a.id === item.id), caption: item.caption }))
      .filter((item) => item.asset);
    return {
      id: state.id, uuid: `c${state.id}`, name: state.name, kind: state.kind,
      description: state.description, place: state.place,
      start_date: state.start_date, end_date: state.end_date,
      item_count: state.items.length, cover_asset_id: state.cover,
      cover: items.find((i) => i.asset!.id === state.cover)?.asset ?? items[0]?.asset ?? null,
      first_capture: null, last_capture: null,
      created_at: "2026-11-03T08:00:00.000Z", updated_at: `2026-11-03T08:00:0${state.items.length % 10}.000Z`,
      items,
    }; // prettier-ignore
  };
  const collectionsApi = (path: string, method: string, body: unknown) => {
    if (path === "/api/v1/collections" && method === "GET") {
      return json({ items: [...collections.values()].map(collectionJson) });
    }
    if (path === "/api/v1/collections/suggestions") {
      return json({
        items: (options.trips ?? []).map((trip) => ({
          start_date: trip.start, end_date: trip.end, asset_count: trip.assetIds.length,
          asset_ids: trip.assetIds, latitude: 46, longitude: 7.7, distance_km: 514.2,
          samples: assets.filter((a) => trip.assetIds.includes(a.id)).slice(0, 4),
          cities: (trip.cities ?? []).map((zh) => ({ name: zh, zh, fr: zh })),
          countries: trip.cities ? [{ name: "Switzerland", zh: "瑞士", fr: "Suisse" }] : [],
        })),
      }); // prettier-ignore
    }
    if (path === "/api/v1/collections" && method === "POST") {
      const request = body as { name: string; kind?: "album" | "trip"; asset_ids?: number[] } & Record<string, unknown>;
      const id = collections.size + 1;
      collections.set(id, {
        id, name: request.name, kind: request.kind ?? "album", description: null,
        place: (request.place as string | null | undefined) ?? null,
        start_date: (request.start_date as string) ?? null, end_date: (request.end_date as string) ?? null,
        cover: null, items: (request.asset_ids ?? []).map((asset) => ({ id: asset, caption: null })),
      }); // prettier-ignore
      return json(collectionJson(collections.get(id)!), 201);
    }
    const match = /^\/api\/v1\/collections\/(\d+)(.*)$/.exec(path);
    const state = match ? collections.get(Number(match[1])) : undefined;
    if (!match || !state) return json({ error: { code: "not_found", message: path } }, 404);
    const rest = match[2] ?? "";
    const ids = (body as { asset_ids?: number[] } | undefined)?.asset_ids ?? [];
    if (rest === "" && method === "GET") return json(collectionJson(state));
    if (rest === "" && method === "PATCH") {
      const changes = body as Partial<CollectionState> & { cover_asset_id?: number };
      Object.assign(state, changes);
      if (changes.cover_asset_id !== undefined) state.cover = changes.cover_asset_id;
      return json(collectionJson(state));
    }
    if (rest === "" && method === "DELETE") {
      collections.delete(state.id);
      return Promise.resolve(new Response(null, { status: 204 }));
    }
    if (rest === "/items") {
      const fresh = ids.filter((id) => !state.items.some((item) => item.id === id));
      state.items.push(...fresh.map((id) => ({ id, caption: null })));
      return json({ changed: fresh.length });
    }
    if (rest === "/items/remove") {
      state.items = state.items.filter((item) => !ids.includes(item.id));
      return json({ changed: ids.length });
    }
    if (rest === "/route" && method === "GET") {
      const where = options.located ?? {};
      const points = state.items
        .filter((item) => where[item.id])
        .map((item) => ({ id: item.id, lat: where[item.id]![0], lon: where[item.id]![1], v: `v${item.id}`, p: null }));
      return json({
        points, places: [], distance_km: 1234.4, days: points.length,
        unlocated: state.items.length - points.length,
        stops: points.map((point, index) => ({
          lat: point.lat, lon: point.lon, start: `2025-03-0${index + 1}T09:00:00`,
          end: `2025-03-0${index + 1}T11:30:00`, day: index + 1, asset_ids: [point.id], cover: point,
          place: index === 0 ? { name: "Zermatt", zh: "采尔马特", fr: "Zermatt" } : null,
        })),
      }); // prettier-ignore
    }
    if (rest === "/order") {
      state.items = ids.map((id) => state.items.find((item) => item.id === id)!);
      return json({ changed: ids.length });
    }
    const caption = /^\/items\/(\d+)$/.exec(rest);
    if (caption) {
      const item = state.items.find((entry) => entry.id === Number(caption[1]));
      if (item) item.caption = (body as { caption: string | null }).caption;
      return Promise.resolve(new Response(null, { status: 204 }));
    }
    return json({ error: { code: "not_found", message: path } }, 404);
  };
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

    if (path.startsWith("/api/v1/tasks")) return json({ items: options.tasks ?? [] });
    if (path === "/api/v1/settings") {
      return json({
        map_online_tiles: options.mapOnline ?? false,
        map_style: "dark",
        ai_enabled: options.ai?.enabled ?? false,
        ai_model: "siglip2-so400m-patch14-384",
        cloud_enabled: options.cloud !== "not_configured",
        cloud_model: "deepseek-flash",
        cloud_base_url: "https://api.deepseek.com",
        cloud_include_location: false,
        backup_auto: true,
        backup_interval_days: 7,
        backup_keep: 10,
        backup_folder: null,
        mapweb_url: options.mapweb?.url ?? null,
        vlm_enabled: options.vlm?.enabled ?? false,
        vlm_scope: "priority",
        vlm_folder: null,
        ...((body as object | undefined) ?? {}),
      });
    }
    if (path === "/api/v1/vlm/status") {
      const installed = options.vlm?.installed ?? false;
      return json({
        enabled: options.vlm?.enabled ?? false, scope: "priority",
        folder: "C:\Users\me\AppData\Local\LUMEN Studio\vlm", runtime_installed: installed,
        models: [
          { id: "qwen3.6-35b-a3b", label: "Qwen3.6-35B-A3B (MoE, Q4_K_M)", role: "default",
            downloaded: installed, size_gb: 23.4, licence: "Apache-2.0", repo: "ggml-org/x" },
          { id: "qwen3.8-27b", label: "Qwen3.8-27B (dense, Q4_K_M)", role: "fine",
            downloaded: false, size_gb: 17.4, licence: "Apache-2.0", repo: "unsloth/x" },
        ],
        described: 120, requested: 0, to_read: options.vlm?.enabled ? 3400 : 0,
      }); // prettier-ignore
    }
    if (path === "/api/v1/vlm/describe") {
      return json({ queued: (body as { asset_ids: number[] }).asset_ids.length, task_id: 77 }, 202);
    }
    if (path === "/api/v1/vlm/download") {
      return json({ id: 78, kind: "vlm_download", status: "pending" }, 202);
    }
    if (path === "/api/v1/places/search") {
      const q = url.searchParams.get("q") ?? "";
      const places = [
        { place_id: 3191281, city: { name: "Sarajevo", zh: "塞拉耶佛", fr: "Sarajevo" },
          region: null, country: { name: "Bosnia and Herzegovina", zh: "波黑", fr: "Bosnie-Herzégovine" },
          latitude: 43.84864, longitude: 18.35644 },
      ]; // prettier-ignore
      return json(places.filter((place) => place.city.name.toLowerCase().includes(q.toLowerCase())));
    }
    if (path === "/api/v1/assets/location/nearby") {
      const { asset_ids: ids } = body as { asset_ids: number[] };
      return json({
        found: ids.length - 1, missing: 1,
        examples: ids.slice(1).map((id) => ({ asset_id: id, from_asset_id: 99, latitude: 42.4, longitude: 18.7, gap_s: 600 })),
      }); // prettier-ignore
    }
    if (path.startsWith("/api/v1/assets/location") || path.startsWith("/api/v1/assets/time-shift")) {
      return json({ changed: (body as { asset_ids: number[] }).asset_ids.length });
    }
    if (path.startsWith("/api/v1/mapweb/")) {
      const down = () =>
        json({ error: { code: "mapweb_failed", message: "MapWeb cannot be reached",
                        details: { url: "http://kevin:8788", reason: "timed out" } } }, 502); // prettier-ignore
      if (path === "/api/v1/mapweb/test") {
        return options.mapweb?.down ? down() : json({ url: (body as { url: string }).url, point_count: 310 });
      }
      if (!options.mapweb?.url) {
        return json({ error: { code: "mapweb_not_configured", message: "Set MapWeb's address", details: {} } }, 400);
      }
      if (options.mapweb.down) return down();
      if (path === "/api/v1/mapweb/plan") {
        const ids = (body as { asset_ids: number[] }).asset_ids;
        return json({
          url: options.mapweb.url, photo_count: ids.length, video_count: 1,
          attach: [{ point_id: 7, title: "Kotor 老城", visited_at: "2025-10-20T10:30:00Z", count: 2 }],
          groups: [{ title: "布德瓦 · 2025-10-21 13:39", lat: 42.29, lon: 18.84, start: "2025-10-21T11:39:00Z",
                     count: Math.max(ids.length - 3, 0) }],
          duplicate_count: 1, unplaced_count: 0,
        }); // prettier-ignore
      }
      if (path === "/api/v1/mapweb/send") {
        return json({
          id: 98, kind: "mapweb_send", status: "pending", storage_root_id: null,
          progress_current: 0, progress_total: null, attempts: 0, max_attempts: 3,
          cancel_requested: false, error: null, result: null, created_at: "2026-11-07T10:00:00Z",
          updated_at: "2026-11-07T10:00:00Z", started_at: null, finished_at: null,
        }, 202); // prettier-ignore
      }
    }
    if (path === "/api/v1/cull/similar") {
      const group = (options.similar ?? []).map((id) => ({ asset: assets.find((a) => a.id === id)!, quality: null }));
      return json({
        available: true, group_count: group.length ? 1 : 0, pending_count: group.length ? 1 : 0,
        groups: group.length ? [{ items: group, recommended_id: group[1]!.asset.id, pending: true }] : [],
      }); // prettier-ignore
    }
    if (path === "/api/v1/cull/suspects") {
      const items = (options.suspects ?? []).map((id) => ({
        asset: assets.find((a) => a.id === id)!,
        quality: { sharpness: 0.1, exposure: 1, score: 0.37, flags: ["blurry"] },
      }));
      return json({ items, total: items.length });
    }
    if (path === "/api/v1/duplicates") {
      const kind = url.searchParams.get("kind") ?? "identical";
      const groups = (duplicateGroups[kind] ?? []).map((ids) => ({
        keep_asset_id: ids[0]!, redundant_bytes: 2_000_000,
        assets: ids.map((id) => ({
          asset: assets.find((a) => a.id === id)!, tag_count: id === ids[0] ? 2 : 0, collection_count: 0,
          files: [{ file_id: id * 10, path: `D:\Photos\copy${id}\IMG.JPG`, folder: "Photos",
                    role: "primary", size_bytes: 2_000_000, modified_at: "2024-06-01T10:00:00" }],
        })),
      })); // prettier-ignore
      return json({ groups, group_count: groups.length, redundant_bytes: groups.length * 2_000_000 });
    }
    if (path === "/api/v1/duplicates/merge-all") {
      return json({
        id: 99, kind: "merge_duplicates", status: "pending", storage_root_id: null,
        progress_current: 0, progress_total: null, attempts: 0, max_attempts: 3,
        cancel_requested: false, error: null, result: null, created_at: "2026-11-05T10:00:00Z",
        updated_at: "2026-11-05T10:00:00Z", started_at: null, finished_at: null,
      }, 202); // prettier-ignore
    }
    if (path === "/api/v1/duplicates/merge") {
      const { groups, kind } = body as { groups: { asset_ids: number[] }[]; kind?: string };
      const merged = new Set(groups.flatMap((group) => group.asset_ids));
      const key = kind ?? "identical";
      duplicateGroups[key] = (duplicateGroups[key] ?? []).filter((ids) => !ids.some((id) => merged.has(id)));
      return json({ merged_groups: groups.length, removed_assets: groups.reduce((n, g) => n + g.asset_ids.length - 1, 0) });
    }
    if (/^\/api\/v1\/files\/\d+\/reveal$/.test(path)) return Promise.resolve(new Response(null, { status: 204 }));
    if (/^\/api\/v1\/assets\/\d+\/open-map$/.test(path)) return Promise.resolve(new Response(null, { status: 204 }));
    if (path === "/api/v1/cull/rejected-files") {
      return json({ asset_count: 1, paths: ["D:\Photos\IMG_1.JPG", "D:\Photos\IMG_1.MOV"] });
    }
    if (path.startsWith("/api/v1/backups")) {
      const folder = "C:\Users\me\AppData\Local\LUMEN Studio\backups";
      const backup = (name: string, kind: string, created: string) => ({
        name, path: `${folder}\${name}`, kind, created_at: created, size_bytes: 7_843_840,
        schema_version: 11, asset_count: 676,
      }); // prettier-ignore
      if (path === "/api/v1/backups" && method === "GET") {
        return json({
          folder, default_folder: folder, folder_available: true,
          last_auto_at: "2026-11-01T09:00:00",
          items: [
            backup("lumen-auto-20261101-090000-000.db", "auto", "2026-11-01T09:00:00"),
            backup("lumen-backup-20261020-180000-000.db", "manual", "2026-10-20T18:00:00"),
          ],
        }); // prettier-ignore
      }
      if (path === "/api/v1/backups" && method === "POST") {
        return json(backup("lumen-backup-20261104-120000-000.db", "manual", "2026-11-04T12:00:00"), 201);
      }
      if (path === "/api/v1/backups/restore") {
        return json({
          restored: backup("lumen-backup-20261020-180000-000.db", "manual", "2026-10-20T18:00:00"),
          safety_backup: backup("lumen-before-restore-20261104-120100-000.db", "pre_restore", "2026-11-04T12:01:00"),
          schema_version: 11,
        }); // prettier-ignore
      }
    }
    if (path === "/api/v1/cache" && method === "GET") {
      const fallback = String.raw`C:\Users\me\AppData\Local\LUMEN Studio\cache`;
      const usage = (count: number, bytes: number) => ({ count, bytes });
      return json({
        folder: options.cache?.missing ? fallback : (options.cache?.folder ?? fallback),
        default_folder: fallback,
        configured_folder: options.cache?.folder ?? null,
        folder_available: !options.cache?.missing,
        thumbs: usage(278_307, 7_194_000_000), previews: usage(278_307, 110_166_000_000),
        full: usage(4, 14_000_000), other: usage(0, 0),
        total_bytes: 117_374_000_000, free_bytes: 85_899_345_920,
      }); // prettier-ignore
    }
    if (path === "/api/v1/cache/move") {
      if (options.cache?.noSpace) {
        return json({
          error: {
            code: "cache_move_failed", message: "Not enough free space on the target drive",
            details: { needed_bytes: 122_742_000_000, free_bytes: 53_687_091_200 },
          },
        }, 400); // prettier-ignore
      }
      return json({ id: 99, kind: "move_cache", status: "pending" }, 202);
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
          indexed: options.ai?.indexed ?? assets.length,
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
    if (path.startsWith("/api/v1/collections")) {
      return collectionsApi(path, method, body);
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
    const liveMatch = /^\/api\/v1\/assets\/(\d+)\/live$/.exec(path);
    if (liveMatch) {
      const asset = assets.find((item) => item.id === Number(liveMatch[1]));
      if (!asset?.is_live) {
        return json({ error: { code: "develop_unavailable", message: "not live" } }, 409);
      }
      // 10 frames, 100 ms apart; the still at 500 ms, the sharpest at 700 ms.
      const frames = Array.from({ length: 10 }, (_, i) => ({ time_ms: i * 100, sharpness: i === 7 ? 1 : 0.5 }));
      return json({
        asset_id: asset.id, width: 1920, height: 1440, duration_ms: 1000, still_ms: 500,
        recommended_ms: 700, frames, strip_tiles: 10,
      }); // prettier-ignore
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
      const granularity = url.searchParams.get("granularity") ?? "year";
      const size = granularity === "year" ? 4 : granularity === "month" ? 7 : 10;
      const counts = new Map<string, number>();
      for (const asset of assets) {
        const period = (asset.capture_time ?? "").slice(0, size);
        counts.set(period, (counts.get(period) ?? 0) + 1);
      }
      const buckets = [...counts.entries()]
        .sort((a, b) => b[0].localeCompare(a[0]))
        .map(([period, count]) => ({ period, count }));
      return json({ granularity, buckets });
    }
    if (path === "/api/v1/assets/facets") {
      return json({
        total: assets.length, photos: assets.length, videos: 0, favorites: 0, with_location: 0,
        cameras: [], lenses: [], formats: [], years: [], tags: [], places: [],
      }); // prettier-ignore
    }
    if (path === "/api/v1/assets/ids") return json({ ids: assets.map((asset) => asset.id) });
    if (path === "/api/v1/assets/batch") return json({ updated: (body as { asset_ids: number[] }).asset_ids.length });
    if (path === "/api/v1/assets") return json({ items: assets, next_cursor: null });
    const assetMatch = /^\/api\/v1\/assets\/(\d+)$/.exec(path);
    if (assetMatch) {
      const asset = assets.find((item) => item.id === Number(assetMatch[1]));
      if (!asset) return json({ error: { code: "not_found", message: "nope" } }, 404);
      const read = options.vlm?.descriptions?.[asset.id];
      const detail = {
        ...makeDetail(asset),
        description: read
          ? { description: "", text: "", keywords: [], model: "qwen3.6-35b-a3b",
              model_label: "Qwen3.6-35B-A3B (MoE, Q4_K_M)", fine: false, truncated: false,
              created_at: "2026-11-08T10:00:00.000Z", ...read } // prettier-ignore
          : null,
      };
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

interface CollectionState {
  id: number;
  name: string;
  kind: "album" | "trip";
  description: string | null;
  place: string | null;
  start_date: string | null;
  end_date: string | null;
  cover: number | null;
  items: { id: number; caption: string | null }[];
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
