import "maplibre-gl/dist/maplibre-gl.css";

import type { FeatureCollection, Geometry, Point } from "geojson";
import * as maplibregl from "maplibre-gl";
import type { StyleSpecification } from "maplibre-gl";
// MapLibre looks for its worker next to its own module, which breaks once Vite bundles
// it, and Vite's dev server rewrites worker files in a way that stalls them. Load the
// untouched worker source as text and start it from a blob: URL (allowed by worker-src).
import workerSource from "maplibre-gl/dist/maplibre-gl-worker.mjs?raw";
import { MapPinOff, X } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import Supercluster from "supercluster";
import { feature } from "topojson-client";
import type { GeometryCollection, Topology } from "topojson-specification";

import { thumbnailUrl, type BackendConnection } from "@/api/client";
import { useConnection, useMapPoints, useSettings } from "@/api/hooks";
import type { MapPoint } from "@/api/types";
import { FilterBar } from "@/components/library/FilterBar";
import { BasemapPicker, offlinePalette, type MapStyle } from "@/components/map/BasemapPicker";
import { Button } from "@/components/ui/button";
import { useLibraryState } from "@/library/state";
import { placeName } from "@/lib/places";

maplibregl.setWorkerUrl(
  URL.createObjectURL(new Blob([workerSource], { type: "text/javascript" })),
);

const onlineStyle = (style: MapStyle) => `https://tiles.openfreemap.org/styles/${style}`;
const MAX_MARKERS = 300;

const OFFLINE_COLORS = {
  dark: { ocean: "#0e1114", land: "#1d2024", borders: "#353a40" },
  light: { ocean: "#d4dde2", land: "#f5f4f0", borders: "#b9c0c6" },
};

interface PointProps {
  id: number;
  v: string;
  /** Town (GeoNames id), if named. */
  p: number | null;
}

/** Offline basemap: country shapes from Natural Earth (bundled, ~750 KB, loaded on demand). */
async function offlineStyle(
  palette: "dark" | "light",
  attribution: string,
): Promise<StyleSpecification> {
  const topology = (await import("world-atlas/countries-50m.json")).default as unknown as Topology<{
    countries: GeometryCollection;
  }>;
  const countries = feature(topology, topology.objects.countries) as FeatureCollection<Geometry>;
  const colors = OFFLINE_COLORS[palette];
  return {
    version: 8,
    sources: { countries: { type: "geojson", data: countries, attribution } },
    layers: [
      { id: "ocean", type: "background", paint: { "background-color": colors.ocean } },
      {
        id: "land",
        type: "fill",
        source: "countries",
        paint: { "fill-color": colors.land, "fill-antialias": true },
      },
      {
        id: "borders",
        type: "line",
        source: "countries",
        paint: { "line-color": colors.borders, "line-width": 0.6 },
      },
    ],
  };
}

export function MapPage() {
  const { t, i18n } = useTranslation();
  const conn = useConnection();
  const { query, setQuery, openViewer } = useLibraryState();
  const settings = useSettings();
  const points = useMapPoints(query);
  const containerRef = useRef<HTMLDivElement>(null);
  const mapRef = useRef<maplibregl.Map | null>(null);
  const markersRef = useRef<maplibregl.Marker[]>([]);
  const attributionRef = useRef<maplibregl.AttributionControl | null>(null);
  const fittedRef = useRef(false);
  const [ready, setReady] = useState(false);
  const [picked, setPicked] = useState<PointProps[] | null>(null);
  const online = settings.data?.map_online_tiles ?? false;
  const mapStyle = settings.data?.map_style ?? "dark";
  // What is drawn: an online style URL, or the dark / light offline map.
  const basemap = online ? onlineStyle(mapStyle) : offlinePalette(mapStyle);

  const index = useMemo(() => {
    const cluster = new Supercluster<PointProps>({ radius: 70, maxZoom: 17 });
    cluster.load(
      (points.data?.points ?? []).map((point: MapPoint) => ({
        type: "Feature",
        geometry: { type: "Point", coordinates: [point.lon, point.lat] },
        properties: { id: point.id, v: point.v, p: point.p },
      })),
    );
    return cluster;
  }, [points.data]);

  // Remove the map when leaving the page.
  useEffect(
    () => () => {
      markersRef.current.forEach((marker) => marker.remove());
      markersRef.current = [];
      mapRef.current?.remove();
      mapRef.current = null;
      attributionRef.current = null;
      fittedRef.current = false;
      setReady(false);
    },
    [],
  );

  // Create the map, or swap the basemap in place when it changes: the view and the photo
  // markers (HTML elements, not style layers) stay as they are.
  useEffect(() => {
    if (!containerRef.current || settings.isPending) return;
    let cancelled = false;
    void (async () => {
      const style =
        basemap === "dark" || basemap === "light"
          ? await offlineStyle(basemap, t("map.attributionOffline"))
          : basemap;
      if (cancelled || !containerRef.current) return;
      let map = mapRef.current;
      if (map) {
        map.setStyle(style);
        if (attributionRef.current) map.removeControl(attributionRef.current);
      } else {
        map = new maplibregl.Map({
          container: containerRef.current,
          style,
          center: [110, 30],
          zoom: 1.6,
          attributionControl: false,
          renderWorldCopies: false,
        });
        // Top left: the panel of a clicked cluster opens on the right.
        map.addControl(new maplibregl.NavigationControl({ showCompass: false }), "top-left");
        map.on("load", () => setReady(true));
        mapRef.current = map;
      }
      attributionRef.current = new maplibregl.AttributionControl(
        online ? { compact: true, customAttribution: t("map.attributionOnline") } : { compact: true },
      );
      map.addControl(attributionRef.current);
    })();
    return () => {
      cancelled = true;
    };
  }, [basemap, online, settings.isPending, t]);

  // Fit the view to the photos the first time they arrive.
  useEffect(() => {
    const map = mapRef.current;
    const list = points.data?.points;
    if (!map || !ready || !list || list.length === 0 || fittedRef.current) return;
    fittedRef.current = true;
    const bounds = new maplibregl.LngLatBounds();
    list.forEach((point) => bounds.extend([point.lon, point.lat]));
    map.fitBounds(bounds, { padding: 80, maxZoom: 12, duration: 0 });
  }, [points.data, ready]);

  // Draw clusters as HTML markers with a thumbnail; refresh on every move.
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !ready || !conn) return;
    const render = () => {
      markersRef.current.forEach((marker) => marker.remove());
      const bounds = map.getBounds();
      const features = index
        .getClusters(
          [bounds.getWest(), bounds.getSouth(), bounds.getEast(), bounds.getNorth()],
          Math.round(map.getZoom()),
        )
        .slice(0, MAX_MARKERS);
      markersRef.current = features.map((item) => {
        const [lon, lat] = (item.geometry as Point).coordinates as [number, number];
        const props = item.properties as PointProps & {
          cluster?: boolean;
          cluster_id?: number;
          point_count?: number;
        };
        const leaves: PointProps[] = props.cluster
          ? index.getLeaves(props.cluster_id!, 500).map((leaf) => leaf.properties)
          : [{ id: props.id, v: props.v, p: props.p }];
        const element = markerElement(conn, leaves[0]!, props.point_count ?? 1);
        element.addEventListener("click", (event) => {
          event.stopPropagation();
          if (leaves.length === 1) {
            openViewer([leaves[0]!.id], leaves[0]!.id);
            return;
          }
          setPicked(leaves);
          const zoom = index.getClusterExpansionZoom(props.cluster_id!);
          map.easeTo({ center: [lon, lat], zoom: Math.min(zoom, 18) });
        });
        return new maplibregl.Marker({ element }).setLngLat([lon, lat]).addTo(map);
      });
    };
    render();
    map.on("moveend", render);
    return () => {
      map.off("moveend", render);
    };
  }, [index, ready, conn, openViewer]);

  const empty = points.data && points.data.points.length === 0;
  // The town most of the clicked photos were taken in.
  const pickedPlace = useMemo(() => {
    const counts = new Map<number, number>();
    picked?.forEach((point) => {
      if (point.p) counts.set(point.p, (counts.get(point.p) ?? 0) + 1);
    });
    const [best] = [...counts.entries()].sort((a, b) => b[1] - a[1]);
    const place = best && points.data?.places.find((item) => item.place_id === best[0]);
    return place ? placeName(place.name, i18n.language) : null;
  }, [picked, points.data, i18n.language]);

  return (
    <div className="flex h-full flex-col">
      <div className="shrink-0 space-y-3 px-6 pb-3 pt-5">
        <div className="flex items-baseline gap-3">
          <h1 className="text-lg font-medium">{t("map.title")}</h1>
          <span className="text-xs text-muted-foreground">
            {online ? t("map.online") : t("map.offline")}
            {points.data ? ` · ${t("map.photosHere", { count: points.data.points.length })}` : ""}
          </span>
        </div>
        <FilterBar query={query} onChange={setQuery} sortable={false} />
      </div>
      <div className="relative min-h-0 flex-1 border-t">
        {/* maplibre's CSS makes the container position:relative, so size it explicitly. */}
        <div ref={containerRef} className="h-full w-full" />
        <div className="absolute bottom-3 left-3 rounded-lg border bg-panel/95 p-0.5 shadow-lg">
          <BasemapPicker compact />
        </div>
        {empty && (
          <div className="pointer-events-none absolute inset-x-0 top-8 flex justify-center">
            <span className="flex items-center gap-2 rounded-md bg-background/80 px-3 py-2 text-xs text-muted-foreground">
              <MapPinOff className="size-3.5" />
              {t("map.empty")}
            </span>
          </div>
        )}
        {picked && conn && (
          <aside className="absolute bottom-3 right-3 top-3 flex w-64 flex-col overflow-hidden rounded-lg border bg-panel/95 shadow-xl">
            <div className="flex h-9 shrink-0 items-center justify-between gap-2 border-b px-3 text-xs">
              <span className="truncate">
                {pickedPlace && <span className="font-medium">{pickedPlace} · </span>}
                {t("map.photosHere", { count: picked.length })}
              </span>
              <Button
                variant="ghost"
                size="icon-sm"
                aria-label={t("map.clearSelection")}
                onClick={() => setPicked(null)}
              >
                <X className="size-3.5" />
              </Button>
            </div>
            <div className="grid flex-1 grid-cols-3 content-start gap-1 overflow-y-auto p-2">
              {picked.map((point) => (
                <button
                  key={point.id}
                  type="button"
                  onClick={() => openViewer(picked.map((p) => p.id), point.id)}
                  className="aspect-square overflow-hidden rounded-sm bg-card"
                >
                  <img
                    src={thumbnailUrl(conn, point.id, point.v)}
                    alt=""
                    loading="lazy"
                    className="size-full object-cover"
                  />
                </button>
              ))}
            </div>
          </aside>
        )}
      </div>
    </div>
  );
}

/**
 * A marker: MapLibre places the outer element with an inline `transform`, so it must not
 * be scaled itself. (Tailwind's `scale-*` uses the separate CSS `scale` property, which
 * applies on top of that transform and would scale the offset too, pushing the marker
 * out from under the pointer on hover.) The hover zoom is on the inner tile.
 */
function markerElement(conn: BackendConnection, cover: PointProps, count: number): HTMLElement {
  const element = document.createElement("button");
  element.type = "button";
  element.className = "group size-11 cursor-pointer";
  const tile = document.createElement("span");
  tile.className =
    "relative block size-full rounded-md border-2 border-white/90 bg-card bg-cover bg-center shadow-lg transition-transform group-hover:scale-110";
  tile.style.backgroundImage = `url("${thumbnailUrl(conn, cover.id, cover.v)}")`;
  element.append(tile);
  if (count > 1) {
    const badge = document.createElement("span");
    badge.className =
      "absolute -right-2 -top-2 min-w-5 rounded-full bg-highlight px-1 text-center text-[10.5px] font-semibold leading-5 text-background";
    badge.textContent = count > 999 ? "999+" : String(count);
    tile.append(badge);
  }
  return element;
}
