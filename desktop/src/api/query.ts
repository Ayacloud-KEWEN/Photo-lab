/** Mirrors `AssetQuery` in backend/lumen/schemas/assets.py (sent as query parameters). */
export interface AssetQuery {
  q?: string;
  media_type?: "photo" | "video";
  min_rating?: number;
  favorite?: boolean;
  camera?: string;
  lens?: string;
  format?: string;
  storage_root_id?: number;
  tag_id?: number[];
  date_from?: string;
  date_to?: string;
  has_location?: boolean;
  sort?: "capture_desc" | "capture_asc" | "added_desc";
}

/** A partial update; `undefined` removes that filter. */
export type QueryPatch = { [K in keyof AssetQuery]?: AssetQuery[K] | undefined };

export type QueryValue = string | number | boolean | number[] | null | undefined;

export function toSearchParams(params: Record<string, QueryValue>): string {
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value === undefined || value === null || value === "") continue;
    if (Array.isArray(value)) value.forEach((item) => search.append(key, String(item)));
    else search.append(key, String(value));
  }
  const text = search.toString();
  return text ? `?${text}` : "";
}

/** Number of active filters (search text and sort order excluded). */
export function countFilters(query: AssetQuery): number {
  const { q: _q, sort: _sort, tag_id, ...rest } = query;
  return (
    Object.values(rest).filter((value) => value !== undefined && value !== "").length +
    (tag_id?.length ?? 0)
  );
}
