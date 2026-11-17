import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Loader2, RefreshCw, Upload } from "lucide-react";
import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";

import { api } from "@/api/client";
import { useConnection, useSettings, useTask, useUpdateSettings } from "@/api/hooks";
import { Button } from "@/components/ui/button";
import { mapWebError } from "@/components/settings/MapWebSettings";
import { confirmAction } from "@/lib/dialogs";

/**
 * Keeping the library and MapWeb in step: which photos are on the map, updating the ones
 * edited since, and automatic sending (off unless turned on).
 */
export function MapWebSync() {
  const { t } = useTranslation();
  const conn = useConnection();
  const queryClient = useQueryClient();
  const settings = useSettings();
  const update = useUpdateSettings();
  const [taskId, setTaskId] = useState<number | null>(null);
  const [error, setError] = useState<unknown>(null);
  const task = useTask(taskId);
  const sync = useQuery({
    queryKey: ["mapweb", "sync"],
    queryFn: () => api.getMapWebSync(conn!),
    enabled: !!conn && !!settings.data?.mapweb_url,
  });
  const status = task.data?.status;
  const running = taskId !== null && status !== "succeeded" && status !== "failed";
  useEffect(() => {
    if (status === "succeeded" || status === "failed") {
      void queryClient.invalidateQueries({ queryKey: ["mapweb", "sync"] });
      void queryClient.invalidateQueries({ queryKey: ["library"] });
    }
    if (status === "failed") setError(new Error(task.data?.error ?? ""));
  }, [status, queryClient, task.data?.error]);

  if (!settings.data?.mapweb_url || !sync.data) return null;
  const features = sync.data.features;
  const run = (start: () => Promise<{ id: number }>) => {
    setError(null);
    start()
      .then((started) => setTaskId(started.id))
      .catch(setError);
  };
  const app = settings.data;

  return (
    <section aria-label={t("mapweb.syncTitle")} className="max-w-xl space-y-3 pt-2">
      <h3 className="text-[13px] font-medium">{t("mapweb.syncTitle")}</h3>
      <p role="status" className="text-xs text-muted-foreground">
        {t("mapweb.syncStatus", { count: sync.data.on_map })}
        {sync.data.outdated > 0 && ` · ${t("mapweb.syncOutdated", { count: sync.data.outdated })}`}
      </p>
      {features.length === 0 ? (
        <p className="text-xs leading-relaxed text-warning">{t("mapweb.oldVersion")}</p>
      ) : (
        <div className="flex flex-wrap gap-2">
          <Button
            size="sm"
            variant="secondary"
            disabled={running || !features.includes("photo-lookup")}
            onClick={() => run(() => api.syncMapWeb(conn!))}
          >
            {running ? <Loader2 className="animate-spin" /> : <RefreshCw />}
            {t("mapweb.syncCheck")}
          </Button>
          <Button
            size="sm"
            variant="secondary"
            disabled={running || sync.data.outdated === 0 || !features.includes("photo-replace")}
            onClick={() => run(() => api.updateOnMapWeb(conn!, null))}
          >
            <Upload /> {t("mapweb.syncUpdate", { count: sync.data.outdated })}
          </Button>
        </div>
      )}
      {running && task.data?.progress_total ? (
        <p className="text-xs text-muted-foreground">
          {t("mapweb.syncProgress", {
            done: task.data.progress_current,
            total: task.data.progress_total,
          })}
        </p>
      ) : null}
      {error ? (
        <p role="alert" className="select-text text-xs text-destructive">
          {mapWebError(error, t)}
        </p>
      ) : null}

      <div className="space-y-2 rounded-md border border-white/10 p-3">
        <label className="flex items-start gap-2 text-[12.5px]">
          <input
            type="checkbox"
            className="mt-0.5"
            checked={app.mapweb_auto_send}
            onChange={(event) => {
              const on = event.target.checked;
              if (!on) return update.mutate({ mapweb_auto_send: false });
              void confirmAction(t("mapweb.autoConfirm"), {
                title: t("mapweb.autoTitle"),
                okLabel: t("mapweb.autoTurnOn"),
                cancelLabel: t("export.cancel"),
              }).then((ok) => ok && update.mutate({ mapweb_auto_send: true }));
            }}
          />
          <span>
            <span className="block">{t("mapweb.autoTitle")}</span>
            <span className="block text-[11.5px] leading-relaxed text-muted-foreground">
              {t("mapweb.autoHint")}
            </span>
          </span>
        </label>
        {app.mapweb_auto_send && (
          <div className="flex flex-wrap items-center gap-2 pl-6 text-[12px]">
            <span className="text-muted-foreground">{t("mapweb.autoRule")}</span>
            <select
              aria-label={t("mapweb.autoMinRating")}
              value={app.mapweb_auto_min_rating}
              onChange={(event) =>
                update.mutate({ mapweb_auto_min_rating: Number(event.target.value) })
              }
              className="h-7 rounded-md border border-input bg-background/60 px-1.5"
            >
              {[5, 4, 3, 2, 1].map((n) => (
                <option key={n} value={n}>
                  {t("filters.ratingAtLeast", { count: n })}
                </option>
              ))}
            </select>
            <label className="flex items-center gap-1.5">
              <input
                type="checkbox"
                checked={app.mapweb_auto_favorites}
                onChange={(event) =>
                  update.mutate({ mapweb_auto_favorites: event.target.checked })
                }
              />
              {t("mapweb.autoFavorites")}
            </label>
          </div>
        )}
      </div>
    </section>
  );
}
