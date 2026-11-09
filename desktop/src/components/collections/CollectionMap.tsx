import { Loader2, MapPinOff, PanelLeft, Route } from "lucide-react";
import { lazy, Suspense, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";

import { thumbnailUrl } from "@/api/client";
import { useCollectionRoute, useConnection } from "@/api/hooks";
import type { CollectionRoute, RouteStop } from "@/api/types";
import type { MapFocus } from "@/components/map/PhotoMap";
import { formatNumber } from "@/lib/format";
import { placeName } from "@/lib/places";
import { dayColor, routeDays } from "@/lib/route";
import { cn } from "@/lib/utils";

// MapLibre is large: load it with the first map.
const PhotoMap = lazy(() => import("@/components/map/PhotoMap"));

const PREF = "lumen.collections.mapRoute";

function readFlag(key: string, fallback: boolean) {
  try {
    const value = localStorage.getItem(key);
    return value === null ? fallback : value === "1";
  } catch {
    return fallback;
  }
}
function writeFlag(key: string, value: boolean) {
  try {
    localStorage.setItem(key, value ? "1" : "0");
  } catch {
    // Not remembered: fine.
  }
}

/**
 * A collection's photos on the map. With two stops or more it also draws the route from
 * stop to stop and lists them by day; both can be hidden (remembered).
 */
export function CollectionMap({ id }: { id: number }) {
  const { t } = useTranslation();
  const route = useCollectionRoute(id);
  const [focus, setFocus] = useState<MapFocus | null>(null);
  const [selected, setSelected] = useState<number | null>(null);
  const [showRoute, setShowRoute] = useState(() =>
    readFlag(`${PREF}.line`, true),
  );
  const [showList, setShowList] = useState(() =>
    readFlag(`${PREF}.list`, true),
  );
  const data = route.data;

  if (!data) {
    return (
      <div className="flex min-h-0 flex-1 items-center justify-center">
        <Loader2 className="size-5 animate-spin text-muted-foreground" />
      </div>
    );
  }
  const empty = data.points.length === 0;
  const hasRoute = data.stops.length >= 2;
  const pick = (stop: RouteStop, index: number) => {
    setSelected(index);
    setFocus({
      lat: stop.lat,
      lon: stop.lon,
      ids: stop.asset_ids,
      nonce: Date.now(),
    });
  };
  const toggle = (
    value: boolean,
    set: (next: boolean) => void,
    key: string,
  ) => {
    set(!value);
    writeFlag(`${PREF}.${key}`, !value);
  };
  const chip = (on: boolean) =>
    cn(
      "pointer-events-auto flex h-7 items-center gap-1.5 rounded-md border border-white/10 bg-background/85 px-2.5 text-[12px] text-muted-foreground shadow hover:text-foreground",
      on && "text-foreground",
    );

  return (
    <div className="flex min-h-0 flex-1">
      {hasRoute && showList && (
        <RouteList route={data} selected={selected} onPick={pick} />
      )}
      <div className="relative min-h-0 min-w-0 flex-1">
        <Suspense
          fallback={
            <div className="flex h-full items-center justify-center">
              <Loader2 className="size-5 animate-spin text-muted-foreground" />
            </div>
          }
        >
          <PhotoMap
            key={hasRoute && showRoute ? "route" : "map"}
            points={data.points}
            places={data.places}
            stops={hasRoute && showRoute ? data.stops : undefined}
            focus={focus}
          >
            {(empty || data.unlocated > 0) && (
              <div className="pointer-events-none absolute inset-x-0 top-3 flex justify-center">
                <span className="flex items-center gap-2 rounded-md bg-background/85 px-3 py-2 text-xs text-muted-foreground shadow">
                  <MapPinOff className="size-3.5" />
                  {empty
                    ? t("collections.mapEmpty")
                    : t("collections.unlocated", { count: data.unlocated })}
                </span>
              </div>
            )}
          </PhotoMap>
        </Suspense>
        {hasRoute && (
          <div className="pointer-events-none absolute left-3 top-3 flex gap-1.5">
            <button
              type="button"
              aria-pressed={showList}
              onClick={() => toggle(showList, setShowList, "list")}
              className={chip(showList)}
            >
              <PanelLeft className="size-3.5" />
              {t("collections.showStops")}
            </button>
            <button
              type="button"
              aria-pressed={showRoute}
              onClick={() => toggle(showRoute, setShowRoute, "line")}
              className={chip(showRoute)}
            >
              <Route className="size-3.5" />
              {t("collections.showRoute")}
            </button>
          </div>
        )}
      </div>
    </div>
  );
}

function RouteList({
  route,
  selected,
  onPick,
}: {
  route: CollectionRoute;
  selected: number | null;
  onPick: (stop: RouteStop, index: number) => void;
}) {
  const { t, i18n } = useTranslation();
  const conn = useConnection();
  const days = useMemo(() => routeDays(route.stops), [route.stops]);
  const locale = i18n.language;
  const date = (value: string) =>
    new Intl.DateTimeFormat(locale, {
      month: "short",
      day: "numeric",
      weekday: "short",
    }).format(new Date(`${value}T12:00:00`));
  const time = (value: string, withDate = false) =>
    new Intl.DateTimeFormat(locale, {
      ...(withDate ? { month: "numeric", day: "numeric" } : {}),
      hour: "2-digit",
      minute: "2-digit",
    }).format(new Date(value));
  const summary = [
    t("collections.routeStops", { count: route.stops.length }),
    t("collections.routeDays", { count: route.days }),
    t("collections.routeDistance", {
      distance: formatNumber(Math.round(route.distance_km), locale),
    }),
  ].join(" · ");

  return (
    <aside
      aria-label={t("collections.viewRoute")}
      className="flex w-72 shrink-0 flex-col border-r border-white/10"
    >
      <div className="shrink-0 space-y-1 border-b border-white/10 px-4 py-3">
        <p className="text-[12.5px] font-medium">{summary}</p>
        <p className="text-[11px] leading-relaxed text-subtle-foreground">
          {t("collections.routeNote")}
        </p>
      </div>
      <div className="min-h-0 flex-1 overflow-y-auto py-2">
        {days.map((day) => (
          <section
            key={day.day}
            aria-label={t("collections.routeDay", { day: day.day })}
          >
            <h3 className="flex items-center gap-2 px-4 pb-1 pt-3 text-[11.5px] text-muted-foreground">
              <span
                className="size-2 rounded-full"
                style={{ backgroundColor: dayColor(day.day) }}
              />
              <span className="font-medium text-foreground">
                {t("collections.routeDay", { day: day.day })}
              </span>
              {date(day.date)}
            </h3>
            <ol>
              {day.stops.map(({ stop, index }) => {
                const start = time(stop.start);
                // A stop over several days (a stay) shows the date it ends on.
                const end = time(
                  stop.end,
                  stop.end.slice(0, 10) !== stop.start.slice(0, 10),
                );
                return (
                  <li key={index}>
                    <button
                      type="button"
                      onClick={() => onPick(stop, index)}
                      aria-current={selected === index || undefined}
                      className={cn(
                        "flex w-full items-center gap-2.5 px-4 py-1.5 text-left hover:bg-white/5",
                        selected === index && "bg-white/10",
                      )}
                    >
                      <span
                        className="flex size-5 shrink-0 items-center justify-center rounded-full text-[10.5px] font-semibold text-background"
                        style={{ backgroundColor: dayColor(stop.day) }}
                      >
                        {index + 1}
                      </span>
                      {conn && (
                        <img
                          src={thumbnailUrl(conn, stop.cover.id, stop.cover.v)}
                          alt=""
                          loading="lazy"
                          className="size-9 shrink-0 rounded-sm object-cover"
                        />
                      )}
                      <span className="min-w-0 flex-1">
                        <span className="block truncate text-[12.5px]">
                          {stop.place
                            ? placeName(stop.place, locale)
                            : t("collections.unknownPlace")}
                        </span>
                        <span className="block text-[11px] text-muted-foreground">
                          {start === end ? start : `${start}–${end}`} ·{" "}
                          {t("collections.count", {
                            count: stop.asset_ids.length,
                          })}
                        </span>
                      </span>
                    </button>
                  </li>
                );
              })}
            </ol>
          </section>
        ))}
      </div>
    </aside>
  );
}
