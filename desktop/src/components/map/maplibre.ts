import "maplibre-gl/dist/maplibre-gl.css";

import type { FeatureCollection, Geometry } from "geojson";
import * as maplibregl from "maplibre-gl";
import type { StyleSpecification } from "maplibre-gl";
// MapLibre looks for its worker next to its own module, which breaks once Vite bundles
// it, and Vite's dev server rewrites worker files in a way that stalls them. Load the
// untouched worker source as text and start it from a blob: URL (allowed by worker-src).
import workerSource from "maplibre-gl/dist/maplibre-gl-worker.mjs?raw";
import { feature } from "topojson-client";
import type { GeometryCollection, Topology } from "topojson-specification";

import { offlinePalette, type MapStyle } from "@/components/map/BasemapPicker";

maplibregl.setWorkerUrl(URL.createObjectURL(new Blob([workerSource], { type: "text/javascript" })));

export { maplibregl };

const OFFLINE_COLORS = {
  dark: { ocean: "#0e1114", land: "#1d2024", borders: "#353a40" },
  light: { ocean: "#d4dde2", land: "#f5f4f0", borders: "#b9c0c6" },
};

/** What a map draws: an online style URL, or the dark / light offline map. */
export function basemapFor(online: boolean, style: MapStyle): string {
  return online ? `https://tiles.openfreemap.org/styles/${style}` : offlinePalette(style);
}

/** The style for ``basemapFor``'s value (the offline map is built on demand). */
export async function resolveStyle(
  basemap: string,
  offlineAttribution: string,
): Promise<StyleSpecification | string> {
  return basemap === "dark" || basemap === "light"
    ? offlineStyle(basemap, offlineAttribution)
    : basemap;
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
