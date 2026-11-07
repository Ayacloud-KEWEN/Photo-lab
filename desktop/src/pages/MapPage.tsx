import { Loader2, MapPinOff } from "lucide-react";
import { lazy, Suspense } from "react";
import { useTranslation } from "react-i18next";

import { useMapPoints, useSettings } from "@/api/hooks";
import { FilterBar } from "@/components/library/FilterBar";
import { useLibraryState } from "@/library/state";

// MapLibre is large: load it with the first map.
const PhotoMap = lazy(() => import("@/components/map/PhotoMap"));

export function MapPage() {
  const { t } = useTranslation();
  const { query, setQuery } = useLibraryState();
  const settings = useSettings();
  const points = useMapPoints(query);
  const online = settings.data?.map_online_tiles ?? false;
  const empty = points.data && points.data.points.length === 0;

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
        <Suspense fallback={<MapLoading />}>
          <PhotoMap points={points.data?.points ?? []} places={points.data?.places ?? []}>
            {empty && (
              <div className="pointer-events-none absolute inset-x-0 top-8 flex justify-center">
                <span className="flex items-center gap-2 rounded-md bg-background/80 px-3 py-2 text-xs text-muted-foreground">
                  <MapPinOff className="size-3.5" />
                  {t("map.empty")}
                </span>
              </div>
            )}
          </PhotoMap>
        </Suspense>
      </div>
    </div>
  );
}

export function MapLoading() {
  return (
    <div className="flex h-full items-center justify-center">
      <Loader2 className="size-5 animate-spin text-muted-foreground" />
    </div>
  );
}
