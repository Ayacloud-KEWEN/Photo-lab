import { useQuery, useQueryClient } from "@tanstack/react-query";
import type { Feature, FeatureCollection, Geometry, LineString, Point } from "geojson";
import type { GeoJSONSource, LayerSpecification, MapLayerMouseEvent } from "maplibre-gl";
import { BoxSelect, ExternalLink, Footprints, Layers, Loader2, Route, Send, X } from "lucide-react";
import { useEffect, useMemo, useRef, useState, type PointerEvent as ReactPointerEvent } from "react";
import { useTranslation } from "react-i18next";

import { api, mapWebThumbUrl, thumbnailUrl } from "@/api/client";
import { useConnection, useSettings, useTask } from "@/api/hooks";
import type { LayerPlan, LayerTrack, MapPoint } from "@/api/types";
import { maplibregl } from "@/components/map/maplibre";
import { Button } from "@/components/ui/button";
import { cleanQuery, useLibraryState } from "@/library/state";
import { formatDateTime, formatNumber } from "@/lib/format";
import { dayColor } from "@/lib/route";
import { cn } from "@/lib/utils";

/** Periplus' own colours for its sports (public/js/tracks.js). */
const SPORT_COLORS: Record<string, string> = {
  running: "#c8893b",
  hiking: "#3f7d5a",
  walking: "#8a6bb1",
  cycling: "#3b6fa8",
  swimming: "#2a9d9f",
  other: "#7a6a5c",
};
const FOOTPRINT = "#e0a03a";
/** Photos taken during an activity: from half an hour before to half an hour after. */
const TRACK_MARGIN_MS = 30 * 60 * 1000;

type Selected =
  | { kind: "footprint"; id: number }
  | { kind: "track"; track: LayerTrack }
  | { kind: "stop"; day: LayerPlan["days"][number]; stop: LayerPlan["days"][number]["stops"][number] };

function readPrefs(): { footprints: boolean; tracks: boolean } {
  try {
    return { footprints: false, tracks: false, ...JSON.parse(localStorage.getItem("lumen.map.periplus") ?? "{}") };
  } catch {
    return { footprints: false, tracks: false };
  }
}

/** A local wall-clock time ("YYYY-MM-DDTHH:MM:SS") of an instant, as capture times are. */
function localTime(ms: number): string {
  const d = new Date(ms);
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`;
}

/** Keep a GeoJSON layer on the map: added again when the basemap changes. */
function useGeoLayer(
  map: maplibregl.Map | null,
  id: string,
  data: FeatureCollection | null,
  layers: LayerSpecification[],
  source: Record<string, unknown> = {},
  onClick?: (event: MapLayerMouseEvent) => void,
) {
  const clickRef = useRef(onClick);
  clickRef.current = onClick;
  const key = JSON.stringify(layers.map((layer) => layer.id));
  useEffect(() => {
    if (!map || !data) return;
    const sync = () => {
      if (!map.isStyleLoaded()) return;
      const existing = map.getSource<GeoJSONSource>(id);
      if (existing) {
        existing.setData(data);
        return;
      }
      map.addSource(id, { type: "geojson", data, ...source });
      for (const layer of layers) map.addLayer(layer);
    };
    const click = (event: MapLayerMouseEvent) => clickRef.current?.(event);
    const enter = () => (map.getCanvas().style.cursor = "pointer");
    const leave = () => (map.getCanvas().style.cursor = "");
    sync();
    map.on("styledata", sync);
    map.on("idle", sync);
    for (const layer of layers) {
      map.on("click", layer.id, click);
      map.on("mouseenter", layer.id, enter);
      map.on("mouseleave", layer.id, leave);
    }
    return () => {
      map.off("styledata", sync);
      map.off("idle", sync);
      for (const layer of layers) {
        map.off("click", layer.id, click);
        map.off("mouseenter", layer.id, enter);
        map.off("mouseleave", layer.id, leave);
      }
      if (map.getStyle()) {
        for (const layer of [...layers].reverse()) if (map.getLayer(layer.id)) map.removeLayer(layer.id);
        if (map.getSource(id)) map.removeSource(id);
      }
    };
    // The layers are fixed per id; `key` stands for them.
  }, [map, id, data, key]);
}

/**
 * What the user's Periplus holds, on LUMEN's map: footprints, tracks and a plan, plus
 * sending the photos in a box to the map. Hidden without a MapWeb address; layers that
 * cannot be read say so, and the photo map works as before.
 */
export function PeriplusLayers({ map, points }: { map: maplibregl.Map | null; points: MapPoint[] }) {
  const { t, i18n } = useTranslation();
  const conn = useConnection();
  const settings = useSettings();
  const { query, setQuery, openViewer, openMapSend } = useLibraryState();
  const [open, setOpen] = useState(false);
  const [show, setShow] = useState(readPrefs);
  const [planId, setPlanId] = useState<number | null>(null);
  const [selected, setSelected] = useState<Selected | null>(null);
  const [boxing, setBoxing] = useState(false);
  const configured = !!settings.data?.mapweb_url;
  const toggle = (key: "footprints" | "tracks") => {
    const next = { ...show, [key]: !show[key] };
    setShow(next);
    try {
      localStorage.setItem("lumen.map.periplus", JSON.stringify(next));
    } catch {
      // Not remembered: fine.
    }
  };

  const footprints = useQuery({
    queryKey: ["mapweb", "layers", "footprints"],
    queryFn: () => api.mapWebFootprints(conn!),
    enabled: !!conn && configured && show.footprints,
  });
  const tracks = useQuery({
    queryKey: ["mapweb", "layers", "tracks"],
    queryFn: () => api.mapWebTracks(conn!),
    enabled: !!conn && configured && show.tracks,
  });
  const plans = useQuery({
    queryKey: ["mapweb", "layers", "plans"],
    queryFn: () => api.mapWebPlans(conn!),
    enabled: !!conn && configured && open,
  });
  const plan = useQuery({
    queryKey: ["mapweb", "layers", "plan", planId],
    queryFn: () => api.mapWebPlan(conn!, planId!),
    enabled: !!conn && configured && planId !== null,
  });
  const failed = footprints.error ?? tracks.error ?? plans.error ?? plan.error;

  const footprintData = useMemo<FeatureCollection<Point> | null>(
    () =>
      show.footprints && footprints.data
        ? {
            type: "FeatureCollection",
            features: footprints.data.map((f) => ({
              type: "Feature",
              properties: { id: f.id },
              geometry: { type: "Point", coordinates: [f.lng, f.lat] },
            })),
          }
        : null,
    [show.footprints, footprints.data],
  );
  useGeoLayer(
    map,
    "periplus-footprints",
    footprintData,
    [
      {
        id: "periplus-footprint-clusters",
        type: "circle",
        source: "periplus-footprints",
        filter: ["has", "point_count"],
        paint: {
          "circle-color": FOOTPRINT,
          "circle-opacity": 0.85,
          "circle-radius": ["step", ["get", "point_count"], 9, 10, 12, 50, 16],
          "circle-stroke-color": "#ffffff",
          "circle-stroke-width": 1.5,
        },
      },
      {
        id: "periplus-footprint-points",
        type: "circle",
        source: "periplus-footprints",
        filter: ["!", ["has", "point_count"]],
        paint: {
          "circle-color": FOOTPRINT,
          "circle-radius": 6,
          "circle-stroke-color": "#ffffff",
          "circle-stroke-width": 2,
        },
      },
    ],
    { cluster: true, clusterRadius: 36, clusterMaxZoom: 14 },
    (event) => {
      const feature = event.features?.[0];
      if (!feature || !map) return;
      const props = feature.properties as { id?: number; cluster_id?: number };
      if (props.cluster_id !== undefined) {
        const source = map.getSource<GeoJSONSource>("periplus-footprints");
        void source?.getClusterExpansionZoom(props.cluster_id).then((zoom) =>
          map.easeTo({
            center: (feature.geometry as Point).coordinates as [number, number],
            zoom: Math.min(zoom, 18),
          }),
        );
        return;
      }
      if (props.id !== undefined) setSelected({ kind: "footprint", id: Number(props.id) });
    },
  );

  const trackData = useMemo<FeatureCollection | null>(
    () =>
      show.tracks && tracks.data
        ? {
            type: "FeatureCollection",
            features: tracks.data.map((track) => ({
              type: "Feature",
              properties: { id: track.id, color: SPORT_COLORS[track.sport] ?? SPORT_COLORS.other },
              geometry: track.geometry as unknown as Geometry,
            })),
          }
        : null,
    [show.tracks, tracks.data],
  );
  const line = { "line-cap": "round", "line-join": "round" } as const;
  useGeoLayer(
    map,
    "periplus-tracks",
    trackData,
    [
      {
        id: "periplus-track-lines",
        type: "line",
        source: "periplus-tracks",
        layout: line,
        paint: { "line-color": ["get", "color"], "line-width": 3, "line-opacity": 0.85 },
      },
    ],
    {},
    (event) => {
      const id = Number((event.features?.[0]?.properties as { id?: number } | undefined)?.id);
      const track = tracks.data?.find((item) => item.id === id);
      if (track) pickTrack(track);
    },
  );

  const planData = useMemo<FeatureCollection | null>(() => {
    if (!plan.data) return null;
    const features: Feature[] = [];
    for (const day of plan.data.days) {
      const color = dayColor(day.number);
      if (day.stops.length > 1) {
        features.push({
          type: "Feature",
          properties: { color },
          geometry: { type: "LineString", coordinates: day.stops.map((s) => [s.lng, s.lat]) } as LineString,
        });
      }
      day.stops.forEach((stop, index) =>
        features.push({
          type: "Feature",
          properties: { color, day: day.number, index, photos: stop.asset_ids.length > 0 ? 1 : 0 },
          geometry: { type: "Point", coordinates: [stop.lng, stop.lat] },
        }),
      );
    }
    return { type: "FeatureCollection", features };
  }, [plan.data]);
  useGeoLayer(
    map,
    "periplus-plan",
    planData,
    [
      {
        id: "periplus-plan-lines",
        type: "line",
        source: "periplus-plan",
        filter: ["==", ["geometry-type"], "LineString"],
        layout: line,
        paint: { "line-color": ["get", "color"], "line-width": 2.5, "line-dasharray": [2, 1.5] },
      },
      {
        id: "periplus-plan-stops",
        type: "circle",
        source: "periplus-plan",
        filter: ["==", ["geometry-type"], "Point"],
        paint: {
          // A stop with photos that day is filled; one without is a ring.
          "circle-color": ["case", ["==", ["get", "photos"], 1], ["get", "color"], "#ffffff"],
          "circle-radius": 7,
          "circle-stroke-color": ["get", "color"],
          "circle-stroke-width": 3,
        },
      },
    ],
    {},
    (event) => {
      const props = event.features?.[0]?.properties as { day?: number; index?: number } | undefined;
      const day = plan.data?.days.find((d) => d.number === Number(props?.day));
      const stop = day?.stops[Number(props?.index)];
      if (day && stop) setSelected({ kind: "stop", day, stop });
    },
  );

  // A plan picked: show all of it.
  useEffect(() => {
    if (!map || !plan.data) return;
    const bounds = new maplibregl.LngLatBounds();
    plan.data.days.forEach((day) => day.stops.forEach((s) => bounds.extend([s.lng, s.lat])));
    if (!bounds.isEmpty()) map.fitBounds(bounds, { padding: 80, maxZoom: 12 });
  }, [map, plan.data]);

  const pickTrack = (track: LayerTrack) => {
    setSelected({ kind: "track", track });
    if (!map) return;
    const bounds = new maplibregl.LngLatBounds();
    const walk = (coords: unknown): void => {
      if (Array.isArray(coords) && typeof coords[0] === "number") bounds.extend(coords as [number, number]);
      else if (Array.isArray(coords)) coords.forEach(walk);
    };
    walk((track.geometry as { coordinates?: unknown }).coordinates);
    if (!bounds.isEmpty()) map.fitBounds(bounds, { padding: 80, maxZoom: 15 });
  };
  const trackFilter = (track: LayerTrack) => {
    if (!track.started_at) return;
    const start = Date.parse(track.started_at) - TRACK_MARGIN_MS;
    const end = Date.parse(track.ended_at ?? track.started_at) + TRACK_MARGIN_MS;
    setQuery((current) => cleanQuery({ ...current, date_from: localTime(start), date_to: localTime(end) }));
  };

  if (!configured || !conn) return null;
  const onlyNew = query.on_map === "no";

  return (
    <>
      <div className="absolute right-3 top-3 z-10 flex flex-col items-end gap-2">
        <div className="flex gap-1">
          <Button
            variant="secondary"
            size="sm"
            aria-pressed={boxing}
            title={t("mapLayers.boxHint")}
            onClick={() => setBoxing(!boxing)}
            className={cn("shadow", boxing && "ring-2 ring-highlight")}
          >
            <BoxSelect /> {t("mapLayers.box")}
          </Button>
          <Button
            variant="secondary"
            size="sm"
            aria-expanded={open}
            onClick={() => setOpen(!open)}
            className="shadow"
          >
            <Layers /> Periplus
          </Button>
        </div>
        {open && (
          <div
            role="group"
            aria-label={t("mapLayers.title")}
            className="w-60 space-y-2 rounded-lg border bg-panel/95 p-3 text-[12.5px] shadow-xl"
          >
            <label className="flex items-center gap-2">
              <input type="checkbox" checked={show.footprints} onChange={() => toggle("footprints")} />
              <Footprints className="size-3.5" style={{ color: FOOTPRINT }} />
              {t("mapLayers.footprints")}
              {footprints.isFetching && <Loader2 className="ml-auto size-3 animate-spin" />}
            </label>
            <label className="flex items-center gap-2">
              <input type="checkbox" checked={show.tracks} onChange={() => toggle("tracks")} />
              <Route className="size-3.5" />
              {t("mapLayers.tracks")}
              {tracks.isFetching && <Loader2 className="ml-auto size-3 animate-spin" />}
            </label>
            <select
              aria-label={t("mapLayers.plan")}
              value={planId ?? ""}
              onChange={(event) => setPlanId(event.target.value ? Number(event.target.value) : null)}
              className="h-7 w-full rounded-md border border-input bg-background/60 px-1.5"
            >
              <option value="">{t("mapLayers.noPlan")}</option>
              {plans.data?.map((item) => (
                <option key={item.id} value={item.id}>
                  {item.title}
                  {item.start_date ? ` · ${item.start_date}` : ""}
                </option>
              ))}
            </select>
            <label className="flex items-center gap-2 border-t border-white/10 pt-2">
              <input
                type="checkbox"
                checked={onlyNew}
                onChange={() =>
                  setQuery((current) =>
                    cleanQuery({ ...current, on_map: onlyNew ? undefined : "no" }),
                  )
                }
              />
              {t("mapLayers.onlyNew")}
            </label>
            {failed && (
              <p role="alert" className="text-[11.5px] leading-relaxed text-warning">
                {t("mapLayers.unreachable")}
              </p>
            )}
          </div>
        )}
      </div>

      {boxing && map && (
        <BoxSelector
          map={map}
          onDone={(bounds) => {
            setBoxing(false);
            if (!bounds) return;
            const ids = points
              .filter((p) => bounds.contains([p.lon, p.lat]))
              .map((p) => p.id);
            if (ids.length) openMapSend(ids);
          }}
        />
      )}

      {selected && (
        <aside
          aria-label={t("mapLayers.card")}
          className="absolute bottom-3 right-3 z-10 flex max-h-[70%] w-72 flex-col overflow-hidden rounded-lg border bg-panel/95 shadow-xl"
        >
          <div className="flex shrink-0 items-start gap-2 border-b px-3 py-2">
            <div className="min-w-0 flex-1 text-[12.5px]">{cardTitle(selected)}</div>
            <Button
              variant="ghost"
              size="icon-sm"
              aria-label={t("export.close")}
              onClick={() => setSelected(null)}
            >
              <X className="size-3.5" />
            </Button>
          </div>
          <div className="min-h-0 flex-1 overflow-y-auto p-3 text-[12px]">
            {selected.kind === "footprint" && (
              <FootprintCard
                footprint={footprints.data?.find((f) => f.id === selected.id)}
                pointId={selected.id}
              />
            )}
            {selected.kind === "track" && (
              <div className="space-y-2">
                <p className="text-muted-foreground">
                  {selected.track.started_at &&
                    formatDateTime(localTime(Date.parse(selected.track.started_at)), i18n.language)}
                  {" · "}
                  {formatNumber(Math.round(selected.track.distance_m / 100) / 10, i18n.language)} km
                  {" · ↑"}
                  {formatNumber(Math.round(selected.track.ascent_m), i18n.language)} m
                </p>
                <Button size="sm" variant="secondary" onClick={() => trackFilter(selected.track)}>
                  {t("mapLayers.trackPhotos")}
                </Button>
              </div>
            )}
            {selected.kind === "stop" && (
              <StopPhotos
                ids={selected.stop.asset_ids}
                points={points}
                onOpen={(id) => openViewer(selected.stop.asset_ids, id)}
              />
            )}
          </div>
        </aside>
      )}
    </>
  );

  function cardTitle(item: Selected) {
    if (item.kind === "footprint") {
      const f = footprints.data?.find((x) => x.id === item.id);
      return (
        <span className="font-medium">
          {f?.emoji} {f?.title || t("mapLayers.untitled")}
        </span>
      );
    }
    if (item.kind === "track") {
      return <span className="font-medium">{item.track.name || t("mapLayers.tracks")}</span>;
    }
    return (
      <span>
        <span className="font-medium">{item.stop.name}</span>
        <span className="block text-[11px] text-muted-foreground">
          {t("collections.routeDay", { day: item.day.number })}
          {item.day.date && ` · ${item.day.date}`}
          {item.day.title && ` · ${item.day.title}`}
        </span>
      </span>
    );
  }
}

/** Drag a box on the map; the photos in it are offered for sending. */
function BoxSelector({
  map,
  onDone,
}: {
  map: maplibregl.Map;
  onDone: (bounds: maplibregl.LngLatBounds | null) => void;
}) {
  const { t } = useTranslation();
  const [start, setStart] = useState<{ x: number; y: number } | null>(null);
  const [end, setEnd] = useState<{ x: number; y: number } | null>(null);
  const at = (event: ReactPointerEvent<HTMLDivElement>) => {
    const rect = event.currentTarget.getBoundingClientRect();
    return { x: event.clientX - rect.left, y: event.clientY - rect.top };
  };
  const rect =
    start && end
      ? {
          left: Math.min(start.x, end.x),
          top: Math.min(start.y, end.y),
          width: Math.abs(end.x - start.x),
          height: Math.abs(end.y - start.y),
        }
      : null;
  return (
    <div
      role="application"
      aria-label={t("mapLayers.boxArea")}
      className="absolute inset-0 z-[5] cursor-crosshair"
      onKeyDown={(event) => event.key === "Escape" && onDone(null)}
      onPointerDown={(event) => {
        event.currentTarget.setPointerCapture?.(event.pointerId);
        setStart(at(event));
        setEnd(at(event));
      }}
      onPointerMove={(event) => start && setEnd(at(event))}
      onPointerUp={(event) => {
        const last = at(event);
        if (!start || Math.abs(last.x - start.x) < 6 || Math.abs(last.y - start.y) < 6) {
          onDone(null);
          return;
        }
        const a = map.unproject([start.x, start.y]);
        const b = map.unproject([last.x, last.y]);
        onDone(new maplibregl.LngLatBounds(a, a).extend(b));
      }}
    >
      <p className="pointer-events-none absolute left-1/2 top-3 -translate-x-1/2 rounded-md bg-background/85 px-3 py-1.5 text-xs shadow">
        {t("mapLayers.boxHint")}
      </p>
      {rect && (
        <div
          className="pointer-events-none absolute border-2 border-highlight bg-highlight/15"
          style={rect}
        />
      )}
    </div>
  );
}

function StopPhotos({
  ids,
  points,
  onOpen,
}: {
  ids: number[];
  points: MapPoint[];
  onOpen: (id: number) => void;
}) {
  const { t } = useTranslation();
  const conn = useConnection();
  const shown = ids.flatMap((id) => {
    const point = points.find((p) => p.id === id);
    return point ? [point] : [];
  });
  if (!ids.length) return <p className="text-muted-foreground">{t("mapLayers.stopNoPhotos")}</p>;
  return (
    <div className="space-y-2">
      <p className="text-muted-foreground">{t("mapLayers.stopPhotos", { count: ids.length })}</p>
      <div className="grid grid-cols-3 gap-1">
        {conn &&
          shown.map((point) => (
            <button
              key={point.id}
              type="button"
              onClick={() => onOpen(point.id)}
              className="aspect-square overflow-hidden rounded-sm bg-card"
            >
              <img src={thumbnailUrl(conn, point.id, point.v)} alt="" loading="lazy" className="size-full object-cover" />
            </button>
          ))}
      </div>
    </div>
  );
}

function FootprintCard({
  footprint,
  pointId,
}: {
  footprint: { description: string; visited_at: string | null; photo_count: number; thumb: string | null } | undefined;
  pointId: number;
}) {
  const { t, i18n } = useTranslation();
  const conn = useConnection();
  const queryClient = useQueryClient();
  const { openViewer } = useLibraryState();
  const photos = useQuery({
    queryKey: ["mapweb", "layers", "footprint", pointId],
    queryFn: () => api.mapWebFootprintPhotos(conn!, pointId, i18n.language),
    enabled: !!conn,
  });
  const [chosen, setChosen] = useState<Set<number> | null>(null);
  const [taskId, setTaskId] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);
  const task = useTask(taskId);
  const status = task.data?.status;
  const sending = taskId !== null && status !== "succeeded" && status !== "failed";
  useEffect(() => {
    if (status === "succeeded" || status === "failed") {
      setChosen(null);
      void queryClient.invalidateQueries({ queryKey: ["mapweb"] });
      void queryClient.invalidateQueries({ queryKey: ["library"] });
    }
    if (status === "failed") setError(task.data?.error ?? "");
  }, [status, queryClient, task.data?.error]);

  const items = photos.data?.items ?? [];
  const placed = new Set([...(photos.data?.here ?? []), ...(photos.data?.elsewhere ?? [])]);
  // By default: the photos not on the map yet.
  const picked = chosen ?? new Set(items.filter((i) => !placed.has(i.id)).map((i) => i.id));
  const toggle = (id: number) => {
    const next = new Set(picked);
    if (!next.delete(id)) next.add(id);
    setChosen(next);
  };
  const send = () => {
    if (!conn || picked.size === 0) return;
    setError(null);
    api
      .sendToMapWeb(conn, { asset_ids: [...picked], point_id: pointId, language: i18n.language })
      .then((started) => setTaskId(started.id))
      .catch((reason: unknown) => setError(reason instanceof Error ? reason.message : String(reason)));
  };

  return (
    <div className="space-y-2">
      {conn && footprint?.thumb && (
        <img src={mapWebThumbUrl(conn, footprint.thumb)} alt="" className="max-h-32 w-full rounded object-cover" />
      )}
      <p className="text-muted-foreground">
        {footprint?.visited_at && formatDateTime(localTime(Date.parse(footprint.visited_at)), i18n.language)}
        {` · ${t("mapLayers.onMapCount", { count: footprint?.photo_count ?? 0 })}`}
      </p>
      {footprint?.description && <p className="whitespace-pre-line leading-relaxed">{footprint.description}</p>}
      <Button
        variant="ghost"
        size="sm"
        onClick={() => conn && void api.openFootprint(conn, pointId)}
      >
        <ExternalLink /> {t("mapLayers.openInPeriplus")}
      </Button>
      <h4 className="pt-1 font-medium">{t("mapLayers.lumenPhotos", { count: items.length })}</h4>
      {photos.isPending ? (
        <Loader2 className="size-4 animate-spin text-muted-foreground" />
      ) : items.length === 0 ? (
        <p className="text-muted-foreground">{t("mapLayers.noLumenPhotos")}</p>
      ) : (
        <>
          <div className="grid grid-cols-3 gap-1">
            {conn &&
              items.map((item) => (
                <div key={item.id} className="relative aspect-square overflow-hidden rounded-sm bg-card">
                  <button
                    type="button"
                    aria-label={item.file_name}
                    onClick={() => openViewer(items.map((i) => i.id), item.id)}
                    className="size-full"
                  >
                    <img
                      src={thumbnailUrl(conn, item.id, item.rendition_version)}
                      alt=""
                      loading="lazy"
                      className="size-full object-cover"
                    />
                  </button>
                  {placed.has(item.id) ? (
                    <span
                      className="absolute left-1 top-1 rounded bg-black/65 px-1 text-[10px] text-white"
                      title={photos.data?.here.includes(item.id) ? t("mapLayers.here") : t("mapLayers.elsewhere")}
                    >
                      ✓
                    </span>
                  ) : (
                    <input
                      type="checkbox"
                      aria-label={t("mapLayers.pick", { name: item.file_name })}
                      checked={picked.has(item.id)}
                      onChange={() => toggle(item.id)}
                      className="absolute left-1 top-1"
                    />
                  )}
                </div>
              ))}
          </div>
          <Button size="sm" disabled={sending || picked.size === 0} onClick={send}>
            {sending ? <Loader2 className="animate-spin" /> : <Send />}
            {t("mapLayers.sendHere", { count: picked.size })}
          </Button>
        </>
      )}
      {error && (
        <p role="alert" className="text-destructive">
          {error}
        </p>
      )}
    </div>
  );
}
