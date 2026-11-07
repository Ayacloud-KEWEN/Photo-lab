import { CalendarDays, Grid3x3, Heart, LayoutPanelTop, MapPin, X } from "lucide-react";
import type { ReactNode } from "react";
import { useTranslation } from "react-i18next";

import { useFacets, useStorageRoots } from "@/api/hooks";
import { countFilters, type AssetQuery, type QueryPatch } from "@/api/query";
import { Button } from "@/components/ui/button";
import { Tooltip } from "@/components/ui/tooltip";
import type { WallMode } from "@/library/layout";
import { cleanQuery } from "@/library/state";
import { placeName } from "@/lib/places";
import { cn } from "@/lib/utils";

interface FilterBarProps {
  query: AssetQuery;
  onChange: (query: AssetQuery) => void;
  mode?: WallMode;
  onModeChange?: (mode: WallMode) => void;
  /** Hide the sort control. */
  sortable?: boolean;
  /** Group the wall by day (with headings and a month bar); not offered when undefined. */
  grouped?: boolean;
  onGroupedChange?: (grouped: boolean) => void;
  trailing?: ReactNode;
}

export function FilterBar({
  query,
  onChange,
  mode,
  onModeChange,
  sortable = true,
  grouped,
  onGroupedChange,
  trailing,
}: FilterBarProps) {
  const { t, i18n } = useTranslation();
  const facets = useFacets();
  const roots = useStorageRoots();
  const set = (patch: QueryPatch) => onChange(cleanQuery({ ...query, ...patch }));
  const active = countFilters(query);

  return (
    <div className="flex flex-wrap items-center gap-1.5">
      <Segmented
        value={query.media_type ?? ""}
        onChange={(value) => set({ media_type: (value || undefined) as AssetQuery["media_type"] })}
        options={[
          ["", t("filters.all")],
          ["photo", t("filters.photos")],
          ["video", t("filters.videos")],
        ]}
      />

      <Select
        label={t("inspector.rating")}
        value={query.min_rating?.toString() ?? ""}
        onChange={(value) => set({ min_rating: value ? Number(value) : undefined })}
        options={[
          ["", t("filters.anyRating")],
          ...[5, 4, 3, 2, 1].map(
            (n) => [String(n), t("filters.ratingAtLeast", { count: n })] as const,
          ),
        ]}
      />

      <Toggle
        pressed={query.favorite === true}
        onChange={(on) => set({ favorite: on || undefined })}
        icon={<Heart className={cn("size-3.5", query.favorite && "fill-current")} />}
        label={t("filters.favorites")}
      />
      <Toggle
        pressed={query.has_location === true}
        onChange={(on) => set({ has_location: on || undefined })}
        icon={<MapPin className="size-3.5" />}
        label={t("filters.location")}
      />

      {(facets.data?.places.length ?? 0) > 0 && (
        <Select
          label={t("inspector.place")}
          value={query.place_id ? `p:${query.place_id}` : query.country ? `c:${query.country}` : ""}
          onChange={(value) =>
            set({
              country: value.startsWith("c:") ? value.slice(2) : undefined,
              place_id: value.startsWith("p:") ? Number(value.slice(2)) : undefined,
            })
          }
          options={[
            ["", t("filters.anyPlace")],
            ...(facets.data?.places.flatMap((country) => [
              [
                `c:${country.country_code}`,
                `${placeName(country.name, i18n.language)} (${country.count})`,
              ] as const,
              ...country.cities.map(
                (city) =>
                  [
                    `p:${city.place_id}`,
                    `   ${placeName(city.name, i18n.language)} (${city.count})`,
                  ] as const,
              ),
            ]) ?? []),
          ]}
        />
      )}
      <Select
        label={t("inspector.camera")}
        value={query.camera ?? ""}
        onChange={(value) => set({ camera: value || undefined })}
        options={[
          ["", t("filters.anyCamera")],
          ...(facets.data?.cameras.map((c) => [c.value, `${c.value} (${c.count})`] as const) ?? []),
        ]}
      />
      <Select
        label={t("inspector.lens")}
        value={query.lens ?? ""}
        onChange={(value) => set({ lens: value || undefined })}
        options={[
          ["", t("filters.anyLens")],
          ...(facets.data?.lenses.map((l) => [l.value, `${l.value} (${l.count})`] as const) ?? []),
        ]}
      />
      <Select
        label={t("filters.format")}
        value={query.format ?? ""}
        onChange={(value) => set({ format: value || undefined })}
        options={[
          ["", t("filters.anyFormat")],
          ...(facets.data?.formats.map((f) => [f.value, `${f.value} (${f.count})`] as const) ?? []),
        ]}
      />
      <Select
        label={t("inspector.tags")}
        value={query.tag_id?.[0]?.toString() ?? ""}
        onChange={(value) => set({ tag_id: value ? [Number(value)] : undefined })}
        options={[
          ["", t("filters.anyTag")],
          ...(facets.data?.tags
            .filter((tag) => tag.asset_count > 0)
            .map((tag) => [String(tag.id), `${tag.name} (${tag.asset_count})`] as const) ?? []),
        ]}
      />
      <Select
        label={t("filters.rejected")}
        value={query.rejected ?? ""}
        onChange={(value) => set({ rejected: (value || undefined) as AssetQuery["rejected"] })}
        options={[
          ["", t("filters.rejectedHide")],
          ["show", t("filters.rejectedShow")],
          ["only", t("filters.rejectedOnly")],
        ]}
      />
      {(roots.data?.length ?? 0) > 1 && (
        <Select
          label={t("library.sources")}
          value={query.storage_root_id?.toString() ?? ""}
          onChange={(value) => set({ storage_root_id: value ? Number(value) : undefined })}
          options={[
            ["", t("filters.anySource")],
            ...(roots.data?.map((root) => [String(root.id), root.display_name] as const) ?? []),
          ]}
        />
      )}

      {active > 0 && (
        <Button
          variant="ghost"
          size="sm"
          onClick={() => onChange(cleanQuery({ q: query.q, sort: query.sort }))}
        >
          <X className="size-3.5" />
          {t("filters.clear")}
        </Button>
      )}

      <div className="ml-auto flex items-center gap-1.5">
        {trailing}
        {sortable && (
          <Select
            label={t("filters.sort")}
            neutral
            value={query.sort ?? "capture_desc"}
            onChange={(value) =>
              set({ sort: value === "capture_desc" ? undefined : (value as AssetQuery["sort"]) })
            }
            options={[
              ["capture_desc", t("filters.sortNewest")],
              ["capture_asc", t("filters.sortOldest")],
              ["added_desc", t("filters.sortAdded")],
            ]}
          />
        )}
        {grouped !== undefined && onGroupedChange && (
          <Tooltip
            label={
              query.sort === "added_desc" ? t("filters.groupByDateOff") : t("filters.groupByDate")
            }
          >
            <Button
              variant="ghost"
              size="icon-sm"
              aria-pressed={grouped && query.sort !== "added_desc"}
              aria-label={t("filters.groupByDate")}
              disabled={query.sort === "added_desc"}
              className={cn(
                "border",
                grouped && query.sort !== "added_desc" && "bg-accent text-foreground",
              )}
              onClick={() => onGroupedChange(!grouped)}
            >
              <CalendarDays className="size-3.5" />
            </Button>
          </Tooltip>
        )}
        {mode && onModeChange && (
          <div className="flex rounded-md border">
            <Tooltip label={t("filters.layoutJustified")}>
              <Button
                variant="ghost"
                size="icon-sm"
                aria-pressed={mode === "justified"}
                aria-label={t("filters.layoutJustified")}
                className={cn(
                  "rounded-r-none",
                  mode === "justified" && "bg-accent text-foreground",
                )}
                onClick={() => onModeChange("justified")}
              >
                <LayoutPanelTop className="size-3.5" />
              </Button>
            </Tooltip>
            <Tooltip label={t("filters.layoutGrid")}>
              <Button
                variant="ghost"
                size="icon-sm"
                aria-pressed={mode === "grid"}
                aria-label={t("filters.layoutGrid")}
                className={cn("rounded-l-none", mode === "grid" && "bg-accent text-foreground")}
                onClick={() => onModeChange("grid")}
              >
                <Grid3x3 className="size-3.5" />
              </Button>
            </Tooltip>
          </div>
        )}
      </div>
    </div>
  );
}

function Select({
  label,
  value,
  onChange,
  options,
  neutral = false,
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
  options: readonly (readonly [string, string])[];
  /** Not a filter (e.g. sort order): never highlighted as active. */
  neutral?: boolean;
}) {
  return (
    <select
      aria-label={label}
      value={value}
      onChange={(event) => onChange(event.target.value)}
      className={cn(
        "h-7 max-w-44 truncate rounded-md border bg-background/60 px-2 text-xs outline-none focus-visible:border-ring/70",
        value && !neutral ? "border-highlight/60 text-foreground" : "text-muted-foreground",
      )}
    >
      {options.map(([optionValue, text]) => (
        <option key={optionValue} value={optionValue} className="bg-popover text-foreground">
          {text}
        </option>
      ))}
    </select>
  );
}

function Segmented({
  value,
  onChange,
  options,
}: {
  value: string;
  onChange: (value: string) => void;
  options: readonly (readonly [string, string])[];
}) {
  return (
    <div role="radiogroup" className="flex h-7 rounded-md border p-0.5">
      {options.map(([optionValue, text]) => (
        <button
          key={optionValue}
          type="button"
          role="radio"
          aria-checked={value === optionValue}
          onClick={() => onChange(optionValue)}
          className={cn(
            "rounded px-2 text-xs transition-colors",
            value === optionValue
              ? "bg-accent text-foreground"
              : "text-muted-foreground hover:text-foreground",
          )}
        >
          {text}
        </button>
      ))}
    </div>
  );
}

function Toggle({
  pressed,
  onChange,
  icon,
  label,
}: {
  pressed: boolean;
  onChange: (pressed: boolean) => void;
  icon: ReactNode;
  label: string;
}) {
  return (
    <button
      type="button"
      aria-pressed={pressed}
      onClick={() => onChange(!pressed)}
      className={cn(
        "flex h-7 items-center gap-1.5 rounded-md border px-2 text-xs transition-colors",
        pressed
          ? "border-highlight/60 text-foreground"
          : "text-muted-foreground hover:text-foreground",
      )}
    >
      {icon}
      {label}
    </button>
  );
}
