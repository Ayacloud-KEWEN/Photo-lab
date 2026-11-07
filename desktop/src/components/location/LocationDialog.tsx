import { Clock, Loader2, MapPin, Search, X } from "lucide-react";
import { lazy, Suspense, useEffect, useRef, useState, type ReactNode } from "react";
import { useTranslation } from "react-i18next";

import { ApiError } from "@/api/client";
import { useLocationActions, usePlaceSearch } from "@/api/hooks";
import type { NearbyResult } from "@/api/types";
import type { PickedPoint } from "@/components/map/LocationPicker";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { useLibraryState, type AssetsRequest } from "@/library/state";
import { placeLine } from "@/lib/places";
import { cn } from "@/lib/utils";

// MapLibre is large: load it with the first map.
const LocationPicker = lazy(() => import("@/components/map/LocationPicker"));

const HOURS = [1, 2, 6, 12, 24] as const;

/** "48.8566, 2.3522" (as copied from a map) → the point, if it is one. */
export function parseCoordinates(text: string): { lat: number; lon: number } | null {
  const match = /^\s*(-?\d+(?:\.\d+)?)\s*[,，\s]\s*(-?\d+(?:\.\d+)?)\s*$/.exec(text);
  if (!match) return null;
  const lat = Number(match[1]);
  const lon = Number(match[2]);
  return Math.abs(lat) <= 90 && Math.abs(lon) <= 180 ? { lat, lon } : null;
}

/** Set where photos were taken: a place on the map, or borrowed by capture time. */
export function LocationDialog() {
  const { locationRequest, closeLocation } = useLibraryState();
  if (!locationRequest) return null;
  return <Body key={locationRequest.nonce} request={locationRequest} onClose={closeLocation} />;
}

function Body({ request, onClose }: { request: AssetsRequest; onClose: () => void }) {
  const { t } = useTranslation();
  const rootRef = useRef<HTMLDivElement>(null);
  const actions = useLocationActions();
  const [mode, setMode] = useState<"place" | "time">("place");
  const [error, setError] = useState<string | null>(null);
  const count = request.assetIds.length;
  useEffect(() => rootRef.current?.focus(), []);

  const fail = (failure: unknown) =>
    setError(failure instanceof ApiError ? failure.message : String(failure));
  const restore = () =>
    actions.restore.mutate(request.assetIds, { onSuccess: onClose, onError: fail });

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-6">
      <div
        ref={rootRef}
        role="dialog"
        aria-modal
        aria-label={t("location.title")}
        tabIndex={-1}
        onKeyDown={(event) => {
          if (event.key === "Escape") onClose();
          event.stopPropagation();
        }}
        className="flex max-h-full w-[680px] max-w-full flex-col rounded-lg border bg-popover shadow-xl outline-none"
      >
        <div className="flex shrink-0 items-center gap-2 border-b px-5 py-3">
          <MapPin className="size-4 text-muted-foreground" />
          <h2 className="text-[14px] font-medium">{t("location.title")}</h2>
          <span className="text-[12px] text-muted-foreground">
            {t("export.count", { count })}
          </span>
          <Button
            variant="ghost"
            size="icon-sm"
            className="ml-auto"
            aria-label={t("export.close")}
            onClick={onClose}
          >
            <X />
          </Button>
        </div>

        <div className="min-h-0 flex-1 space-y-3 overflow-y-auto px-5 py-4 text-[12.5px]">
          <div
            role="radiogroup"
            aria-label={t("location.mode")}
            className="inline-flex rounded-md border bg-background/40 p-0.5 text-[12px]"
          >
            <ModeButton active={mode === "place"} onClick={() => setMode("place")}>
              <MapPin className="size-3.5" /> {t("location.modePlace")}
            </ModeButton>
            <ModeButton active={mode === "time"} onClick={() => setMode("time")}>
              <Clock className="size-3.5" /> {t("location.modeTime")}
            </ModeButton>
          </div>
          {mode === "place" ? (
            <PlaceMode request={request} onDone={onClose} onError={fail} />
          ) : (
            <TimeMode request={request} onDone={onClose} onError={fail} />
          )}
          {error && (
            <p role="alert" className="select-text text-destructive">
              {error}
            </p>
          )}
          <p className="text-[11.5px] leading-relaxed text-subtle-foreground">
            {t("location.note")}
          </p>
        </div>

        <div className="flex shrink-0 items-center gap-2 border-t px-5 py-3">
          <Button variant="ghost" size="sm" disabled={actions.restore.isPending} onClick={restore}>
            {t("location.restore")}
          </Button>
          <span className="ml-auto" />
          <Button variant="ghost" size="sm" onClick={onClose}>
            {t("export.cancel")}
          </Button>
        </div>
      </div>
    </div>
  );
}

function ModeButton({
  active,
  onClick,
  children,
}: {
  active: boolean;
  onClick: () => void;
  children: ReactNode;
}) {
  return (
    <button
      type="button"
      role="radio"
      aria-checked={active}
      onClick={onClick}
      className={cn(
        "flex h-7 items-center gap-1.5 rounded px-3 text-muted-foreground hover:text-foreground",
        active && "bg-white/10 text-foreground",
      )}
    >
      {children}
    </button>
  );
}

function PlaceMode({
  request,
  onDone,
  onError,
}: {
  request: AssetsRequest;
  onDone: () => void;
  onError: (error: unknown) => void;
}) {
  const { t, i18n } = useTranslation();
  const actions = useLocationActions();
  const [point, setPoint] = useState<PickedPoint | null>(request.current);
  const [query, setQuery] = useState("");
  const [typed, setTyped] = useState("");
  const [coordinates, setCoordinates] = useState(
    request.current ? `${request.current.lat.toFixed(5)}, ${request.current.lon.toFixed(5)}` : "",
  );
  const results = usePlaceSearch(query);

  // Search as the user types, a moment after they stop.
  useEffect(() => {
    const timer = setTimeout(() => setQuery(typed), 250);
    return () => clearTimeout(timer);
  }, [typed]);

  const pick = (lat: number, lon: number, fly: boolean) => {
    setPoint(fly ? { lat, lon, nonce: Date.now() } : { lat, lon });
    setCoordinates(`${lat.toFixed(5)}, ${lon.toFixed(5)}`);
  };
  const save = () =>
    point &&
    actions.set.mutate(
      { assetIds: request.assetIds, latitude: point.lat, longitude: point.lon },
      { onSuccess: onDone, onError },
    );

  return (
    <div className="space-y-3">
      <div className="relative">
        <Search className="pointer-events-none absolute left-2.5 top-2 size-3.5 text-muted-foreground" />
        <Input
          aria-label={t("location.search")}
          placeholder={t("location.searchPlaceholder")}
          value={typed}
          onChange={(event) => setTyped(event.target.value)}
          className="h-8 pl-8"
        />
        {query && results.data && (
          <ul
            aria-label={t("location.results")}
            className="absolute inset-x-0 top-9 z-10 max-h-56 overflow-y-auto rounded-md border bg-popover shadow-lg"
          >
            {results.data.length === 0 && (
              <li className="px-3 py-2 text-muted-foreground">{t("location.noResults")}</li>
            )}
            {results.data.map((place) => (
              <li key={place.place_id}>
                <button
                  type="button"
                  onClick={() => {
                    pick(place.latitude, place.longitude, true);
                    setTyped("");
                    setQuery("");
                  }}
                  className="block w-full px-3 py-1.5 text-left hover:bg-accent"
                >
                  {placeLine([place.city, place.region, place.country], i18n.language)}
                </button>
              </li>
            ))}
          </ul>
        )}
      </div>
      <div className="h-[300px] overflow-hidden rounded-md border">
        <Suspense
          fallback={
            <div className="flex h-full items-center justify-center">
              <Loader2 className="size-5 animate-spin text-muted-foreground" />
            </div>
          }
        >
          <LocationPicker value={point} onPick={(lat, lon) => pick(lat, lon, false)} />
        </Suspense>
      </div>
      <div className="flex items-center gap-2">
        <label className="flex flex-1 items-center gap-2">
          <span className="shrink-0 text-muted-foreground">{t("location.coordinates")}</span>
          <Input
            aria-label={t("location.coordinates")}
            placeholder="48.85660, 2.35220"
            value={coordinates}
            onChange={(event) => {
              setCoordinates(event.target.value);
              const parsed = parseCoordinates(event.target.value);
              if (parsed) setPoint({ ...parsed, nonce: Date.now() });
            }}
            className="h-8 font-mono text-[12px]"
          />
        </label>
        <Button size="sm" disabled={!point || actions.set.isPending} onClick={save}>
          {t("location.save", { count: request.assetIds.length })}
        </Button>
      </div>
      {!point && <p className="text-muted-foreground">{t("location.pickHint")}</p>}
    </div>
  );
}

function TimeMode({
  request,
  onDone,
  onError,
}: {
  request: AssetsRequest;
  onDone: () => void;
  onError: (error: unknown) => void;
}) {
  const { t } = useTranslation();
  const actions = useLocationActions();
  const [hours, setHours] = useState<number>(2);
  const [preview, setPreview] = useState<NearbyResult | null>(null);
  const previewMutate = actions.byTime.mutate;

  useEffect(() => {
    setPreview(null);
    previewMutate(
      { assetIds: request.assetIds, maxHours: hours, apply: false },
      { onSuccess: setPreview, onError },
    );
    // A new preview when the window changes (onError only reports).
  }, [hours, request.assetIds, previewMutate]);

  const apply = () =>
    actions.byTime.mutate(
      { assetIds: request.assetIds, maxHours: hours, apply: true },
      { onSuccess: onDone, onError },
    );

  return (
    <div className="space-y-3">
      <p className="leading-relaxed text-muted-foreground">{t("location.timeHint")}</p>
      <label className="flex items-center gap-2">
        <span className="text-muted-foreground">{t("location.within")}</span>
        <select
          aria-label={t("location.within")}
          value={hours}
          onChange={(event) => setHours(Number(event.target.value))}
          className="h-8 rounded-md border border-input bg-background/60 px-2"
        >
          {HOURS.map((value) => (
            <option key={value} value={value}>
              {t("location.hours", { count: value })}
            </option>
          ))}
        </select>
      </label>
      {preview ? (
        <p role="status">
          {t("location.found", { count: preview.found })}
          {preview.missing > 0 && ` · ${t("location.notFound", { count: preview.missing })}`}
        </p>
      ) : (
        <p role="status" className="flex items-center gap-2 text-muted-foreground">
          <Loader2 className="size-3.5 animate-spin" />
          {t("location.looking")}
        </p>
      )}
      <div className="flex justify-end">
        <Button
          size="sm"
          disabled={!preview || preview.found === 0 || actions.byTime.isPending}
          onClick={apply}
        >
          {t("location.apply", { count: preview?.found ?? 0 })}
        </Button>
      </div>
    </div>
  );
}
