import "maplibre-gl/dist/maplibre-gl.css";

import type { Feature, FeatureCollection, Geometry, LineString, Point } from "geojson";
import * as maplibregl from "maplibre-gl";
import type { GeoJSONSource, StyleSpecification } from "maplibre-gl";
// MapLibre looks for its worker next to its own module, which breaks once Vite bundles
// it, and Vite's dev server rewrites worker files in a way that stalls them. Load the
// untouched worker source as text and start it from a blob: URL (allowed by worker-src).
import workerSource from "maplibre-gl/dist/maplibre-gl-worker.mjs?raw";
import { X } from "lucide-react";
import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { useTranslation } from "react-i18next";
import Supercluster from "supercluster";
import { feature } from "topojson-client";
import type { GeometryCollection, Topology } from "topojson-specification";

import { thumbnailUrl, type BackendConnection } from "@/api/client";
import { useConnection, useSettings } from "@/api/hooks";
import type { MapPoint, NamedPlace, RouteStop } from "@/api/types";
import { BasemapPicker, offlinePalette, type MapStyle } from "@/components/map/BasemapPicker";
import { Button } from "@/components/ui/button";
import { useLibraryState } from "@/library/state";
import { dayColor, stopsLabel } from "@/lib/route";
import { placeName } from "@/lib/places";

maplibregl.setWorkerUrl(URL.createObjectURL(new Blob([workerSource], { type: "text/javascript" })));

const onlineStyle = (style: MapStyle) => `https://tiles.openfreemap.org/styles/${style}`;
const MAX_MARKERS = 300;
/** Arrows are drawn on route segments at least this long on screen (px). */
const ARROW_MIN_PX = 70;

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

interface StopProps {
  /** Position in the route, from 0. */
  i: number;
}

/** Where to look, and which photos to list; a new `nonce` moves the map again. */
export interface MapFocus {
  lat: number;
  lon: number;
  ids?: number[];
  nonce: number;
}

export interface PhotoMapProps {
  points: MapPoint[];
  places: NamedPlace[];
  /** Draw a route through these stops (in order) instead of clustering the photos. */
  stops?: RouteStop[] | undefined;
  focus?: MapFocus | null | undefined;
  children?: ReactNode;
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
      {
        id: "ocean",
        type: "background",
        paint: { "background-color": colors.ocean },
      },
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

/** The route as one line per segment, coloured by the day it arrives on. */
function routeLines(stops: RouteStop[]): FeatureCollection<LineString> {
  const features: Feature<LineString>[] = stops.slice(1).map((stop, index) => {
    const from = stops[index]!;
    return {
      type: "Feature",
      properties: { color: dayColor(stop.day) },
      geometry: {
        type: "LineString",
        coordinates: [
          [from.lon, from.lat],
          [stop.lon, stop.lat],
        ],
      },
    };
  });
  return { type: "FeatureCollection", features };
}

/**
 * A map of photos: thumbnails clustered by place, or (with `stops`) a numbered route.
 * Clicking a group lists its photos on the right; the basemap follows the settings.
 */
export default function PhotoMap({ points, places, stops, focus, children }: PhotoMapProps) {
  const { t, i18n } = useTranslation();
  const conn = useConnection();
  const { openViewer } = useLibraryState();
  const settings = useSettings();
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
  const route = stops !== undefined;

  const byId = useMemo(() => new Map(points.map((point) => [point.id, point])), [points]);

  const photoIndex = useMemo(() => {
    const cluster = new Supercluster<PointProps>({ radius: 70, maxZoom: 17 });
    cluster.load(
      points.map((point) => ({
        type: "Feature",
        geometry: { type: "Point", coordinates: [point.lon, point.lat] },
        properties: { id: point.id, v: point.v, p: point.p },
      })),
    );
    return cluster;
  }, [points]);

  const stopIndex = useMemo(() => {
    const cluster = new Supercluster<StopProps>({ radius: 50, maxZoom: 17 });
    cluster.load(
      (stops ?? []).map((stop, i) => ({
        type: "Feature",
        geometry: { type: "Point", coordinates: [stop.lon, stop.lat] },
        properties: { i },
      })),
    );
    return cluster;
  }, [stops]);

  // Remove the map when leaving.
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
        online
          ? { compact: true, customAttribution: t("map.attributionOnline") }
          : { compact: true },
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
    if (!map || !ready || points.length === 0 || fittedRef.current) return;
    fittedRef.current = true;
    const bounds = new maplibregl.LngLatBounds();
    points.forEach((point) => bounds.extend([point.lon, point.lat]));
    map.fitBounds(bounds, { padding: 80, maxZoom: 12, duration: 0 });
  }, [points, ready]);

  // Look at a place (e.g. a stop picked in a list) and list its photos.
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !ready || !focus) return;
    map.flyTo({
      center: [focus.lon, focus.lat],
      zoom: Math.max(map.getZoom(), 13),
    });
    if (focus.ids) {
      setPicked(
        focus.ids.flatMap((id) => {
          const point = byId.get(id);
          return point ? [{ id, v: point.v, p: point.p }] : [];
        }),
      );
    }
  }, [focus, ready, byId]);

  // The route line: a style layer, so added again whenever the basemap changes.
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !ready || !stops) return;
    const data = routeLines(stops);
    const sync = () => {
      if (!map.isStyleLoaded()) return;
      const source = map.getSource<GeoJSONSource>("route");
      if (source) {
        source.setData(data);
        return;
      }
      map.addSource("route", { type: "geojson", data });
      const line = { "line-cap": "round", "line-join": "round" } as const;
      map.addLayer({
        id: "route-casing",
        type: "line",
        source: "route",
        layout: line,
        paint: {
          "line-color": "#000000",
          "line-opacity": 0.35,
          "line-width": 6,
        },
      });
      map.addLayer({
        id: "route-line",
        type: "line",
        source: "route",
        layout: line,
        paint: { "line-color": ["get", "color"], "line-width": 3 },
      });
    };
    sync();
    map.on("styledata", sync);
    map.on("idle", sync);
    return () => {
      map.off("styledata", sync);
      map.off("idle", sync);
      if (map.getStyle()) {
        if (map.getLayer("route-line")) map.removeLayer("route-line");
        if (map.getLayer("route-casing")) map.removeLayer("route-casing");
        if (map.getSource("route")) map.removeSource("route");
      }
    };
  }, [stops, ready]);

  // Markers (HTML elements with a thumbnail): photo clusters, or numbered stops with
  // direction arrows. Drawn again after every move.
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !ready || !conn) return;
    const render = () => {
      markersRef.current.forEach((marker) => marker.remove());
      const bounds = map.getBounds();
      const box: [number, number, number, number] = [
        bounds.getWest(),
        bounds.getSouth(),
        bounds.getEast(),
        bounds.getNorth(),
      ];
      const zoom = Math.round(map.getZoom());
      if (stops) {
        markersRef.current = [
          ...arrowMarkers(map, stops),
          ...stopIndex
            .getClusters(box, zoom)
            .slice(0, MAX_MARKERS)
            .map((item) => {
              const [lon, lat] = (item.geometry as Point).coordinates as [number, number];
              const props = item.properties as StopProps & {
                cluster?: boolean;
                cluster_id?: number;
              };
              const members = props.cluster
                ? stopIndex
                    .getLeaves(props.cluster_id!, Infinity)
                    .map((leaf) => leaf.properties.i)
                    .sort((a, b) => a - b)
                : [props.i];
              const first = stops[members[0]!]!;
              const label = stopsLabel(members);
              const element = markerElement(conn, first.cover, label, dayColor(first.day));
              element.setAttribute("aria-label", t("collections.stopLabel", { label }));
              element.addEventListener("click", (event) => {
                event.stopPropagation();
                if (props.cluster) {
                  const expansion = stopIndex.getClusterExpansionZoom(props.cluster_id!);
                  map.easeTo({
                    center: [lon, lat],
                    zoom: Math.min(expansion, 18),
                  });
                  return;
                }
                setPicked(
                  first.asset_ids.flatMap((id) => {
                    const point = byId.get(id);
                    return point ? [{ id, v: point.v, p: point.p }] : [];
                  }),
                );
              });
              return new maplibregl.Marker({ element }).setLngLat([lon, lat]).addTo(map);
            }),
        ];
        return;
      }
      markersRef.current = photoIndex
        .getClusters(box, zoom)
        .slice(0, MAX_MARKERS)
        .map((item) => {
          const [lon, lat] = (item.geometry as Point).coordinates as [number, number];
          const props = item.properties as PointProps & {
            cluster?: boolean;
            cluster_id?: number;
            point_count?: number;
          };
          const leaves: PointProps[] = props.cluster
            ? photoIndex.getLeaves(props.cluster_id!, 500).map((leaf) => leaf.properties)
            : [{ id: props.id, v: props.v, p: props.p }];
          const count = props.point_count ?? 1;
          const element = markerElement(
            conn,
            leaves[0]!,
            count > 1 ? (count > 999 ? "999+" : String(count)) : null,
          );
          element.addEventListener("click", (event) => {
            event.stopPropagation();
            if (leaves.length === 1) {
              openViewer([leaves[0]!.id], leaves[0]!.id);
              return;
            }
            setPicked(leaves);
            const expansion = photoIndex.getClusterExpansionZoom(props.cluster_id!);
            map.easeTo({ center: [lon, lat], zoom: Math.min(expansion, 18) });
          });
          return new maplibregl.Marker({ element }).setLngLat([lon, lat]).addTo(map);
        });
    };
    render();
    map.on("moveend", render);
    return () => {
      map.off("moveend", render);
    };
  }, [photoIndex, stopIndex, stops, byId, ready, conn, openViewer, t]);

  // The town most of the listed photos were taken in.
  const pickedPlace = useMemo(() => {
    const counts = new Map<number, number>();
    picked?.forEach((point) => {
      if (point.p) counts.set(point.p, (counts.get(point.p) ?? 0) + 1);
    });
    const [best] = [...counts.entries()].sort((a, b) => b[1] - a[1]);
    const place = best && places.find((item) => item.place_id === best[0]);
    return place ? placeName(place.name, i18n.language) : null;
  }, [picked, places, i18n.language]);

  return (
    <div className="relative h-full min-h-0 w-full">
      {/* maplibre's CSS makes the container position:relative, so size it explicitly. */}
      <div
        ref={containerRef}
        className="h-full w-full"
        data-testid={route ? "route-map" : "photo-map"}
      />
      <div className="absolute bottom-3 left-3 rounded-lg border bg-panel/95 p-0.5 shadow-lg">
        <BasemapPicker compact />
      </div>
      {children}
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
          {/* The grid scrolls inside its own box: as the scroll box itself its rows would shrink. */}
          <div className="min-h-0 flex-1 overflow-y-auto p-2">
            <div className="grid grid-cols-3 gap-1">
              {picked.map((point) => (
                <button
                  key={point.id}
                  type="button"
                  onClick={() =>
                    openViewer(
                      picked.map((p) => p.id),
                      point.id,
                    )
                  }
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
          </div>
        </aside>
      )}
    </div>
  );
}

/**
 * Arrows half-way along the route's segments that are long enough on screen, pointing
 * the way the trip went. They turn with the map (rotation is in map coordinates).
 */
function arrowMarkers(map: maplibregl.Map, stops: RouteStop[]): maplibregl.Marker[] {
  const markers: maplibregl.Marker[] = [];
  for (let index = 1; index < stops.length; index++) {
    const from = stops[index - 1]!;
    const to = stops[index]!;
    const a = map.project([from.lon, from.lat]);
    const b = map.project([to.lon, to.lat]);
    if (Math.hypot(b.x - a.x, b.y - a.y) < ARROW_MIN_PX) continue;
    const start = maplibregl.MercatorCoordinate.fromLngLat([from.lon, from.lat]);
    const end = maplibregl.MercatorCoordinate.fromLngLat([to.lon, to.lat]);
    const angle = (Math.atan2(end.y - start.y, end.x - start.x) * 180) / Math.PI;
    const middle = new maplibregl.MercatorCoordinate(
      (start.x + end.x) / 2,
      (start.y + end.y) / 2,
    ).toLngLat();
    const element = document.createElement("span");
    element.className = "pointer-events-none block size-4";
    element.innerHTML =
      '<svg viewBox="0 0 16 16" width="16" height="16"><path d="M4 2 L12 8 L4 14 Z" fill="' +
      dayColor(to.day) +
      '" stroke="rgba(0,0,0,0.55)" stroke-width="1.2" stroke-linejoin="round"/></svg>';
    markers.push(
      new maplibregl.Marker({
        element,
        rotation: angle,
        rotationAlignment: "map",
      })
        .setLngLat(middle)
        .addTo(map),
    );
  }
  return markers;
}

/**
 * A marker: MapLibre places the outer element with an inline `transform`, so it must not
 * be scaled itself. (Tailwind's `scale-*` uses the separate CSS `scale` property, which
 * applies on top of that transform and would scale the offset too, pushing the marker
 * out from under the pointer on hover.) The hover zoom is on the inner tile.
 */
function markerElement(
  conn: BackendConnection,
  cover: { id: number; v: string },
  badge: string | null,
  accent?: string,
): HTMLElement {
  const element = document.createElement("button");
  element.type = "button";
  element.className = "group size-11 cursor-pointer";
  const tile = document.createElement("span");
  tile.className =
    "relative block size-full rounded-md border-2 border-white/90 bg-card bg-cover bg-center shadow-lg transition-transform group-hover:scale-110";
  tile.style.backgroundImage = `url("${thumbnailUrl(conn, cover.id, cover.v)}")`;
  if (accent) tile.style.borderColor = accent;
  element.append(tile);
  if (badge) {
    const label = document.createElement("span");
    label.className =
      "absolute -right-2 -top-2 min-w-5 whitespace-nowrap rounded-full bg-highlight px-1 text-center text-[10.5px] font-semibold leading-5 text-background";
    if (accent) label.style.backgroundColor = accent;
    label.textContent = badge;
    tile.append(label);
  }
  return element;
}
