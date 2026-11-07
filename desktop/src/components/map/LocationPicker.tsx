import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";

import { useSettings } from "@/api/hooks";
import { basemapFor, maplibregl, resolveStyle } from "@/components/map/maplibre";

export interface PickedPoint {
  lat: number;
  lon: number;
  /** Changes when the point is set from outside (search, coordinates): the map flies there. */
  nonce?: number;
}

/** A map to pick one point: click or drag the pin. */
export default function LocationPicker({
  value,
  onPick,
}: {
  value: PickedPoint | null;
  onPick: (lat: number, lon: number) => void;
}) {
  const { t } = useTranslation();
  const settings = useSettings();
  const containerRef = useRef<HTMLDivElement>(null);
  const mapRef = useRef<maplibregl.Map | null>(null);
  const markerRef = useRef<maplibregl.Marker | null>(null);
  const pickRef = useRef(onPick);
  pickRef.current = onPick;
  const [ready, setReady] = useState(false);
  const online = settings.data?.map_online_tiles ?? false;
  const basemap = basemapFor(online, settings.data?.map_style ?? "dark");

  useEffect(() => {
    if (!containerRef.current || settings.isPending) return;
    let cancelled = false;
    void (async () => {
      const style = await resolveStyle(basemap, t("map.attributionOffline"));
      if (cancelled || !containerRef.current) return;
      if (mapRef.current) {
        mapRef.current.setStyle(style);
        return;
      }
      const map = new maplibregl.Map({
        container: containerRef.current,
        style,
        center: value ? [value.lon, value.lat] : [15, 35],
        zoom: value ? 11 : 1.6,
        attributionControl: { compact: true },
        renderWorldCopies: false,
      });
      map.addControl(new maplibregl.NavigationControl({ showCompass: false }), "top-left");
      map.on("click", (event) => pickRef.current(event.lngLat.lat, event.lngLat.lng));
      map.on("load", () => setReady(true));
      mapRef.current = map;
    })();
    return () => {
      cancelled = true;
    };
    // The initial view only (value is read once); later values move the pin, below.
  }, [basemap, settings.isPending, t]);

  useEffect(
    () => () => {
      markerRef.current?.remove();
      mapRef.current?.remove();
      mapRef.current = null;
    },
    [],
  );

  // The pin: placed, moved or dragged.
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !ready) return;
    if (!value) {
      markerRef.current?.remove();
      markerRef.current = null;
      return;
    }
    if (!markerRef.current) {
      markerRef.current = new maplibregl.Marker({ draggable: true, color: "#f5a524" })
        .setLngLat([value.lon, value.lat])
        .addTo(map);
      markerRef.current.on("dragend", () => {
        const at = markerRef.current!.getLngLat();
        pickRef.current(at.lat, at.lng);
      });
    } else {
      markerRef.current.setLngLat([value.lon, value.lat]);
    }
  }, [value, ready]);

  // Set from outside: look there.
  const nonce = value?.nonce;
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !ready || nonce === undefined || !value) return;
    map.flyTo({ center: [value.lon, value.lat], zoom: Math.max(map.getZoom(), 11) });
  }, [nonce, ready]);

  return <div ref={containerRef} className="h-full w-full" data-testid="location-picker" />;
}
