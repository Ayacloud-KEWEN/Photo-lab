import { AlertTriangle, FolderInput, Loader2 } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";

import { ApiError } from "@/api/client";
import { useActiveTasks, useCacheStatus, useMoveCache } from "@/api/hooks";
import type { Task } from "@/api/types";
import { Button } from "@/components/ui/button";
import { confirmAction, pickDirectory } from "@/lib/dialogs";
import { formatBytes } from "@/lib/format";
import { cn } from "@/lib/utils";

/** The folder the cache goes to: a drive root gets its own folder (as the backend does). */
export function cacheTarget(folder: string): string {
  return /^[A-Za-z]:[\\/]?$/.test(folder) ? `${folder.slice(0, 2)}\\LUMEN Studio\\cache` : folder;
}

/** Progress of a cache move: every file counts twice (copied, then deleted). */
export function percent(task: Task): number {
  const total = task.progress_total ?? 0;
  return total > 0 ? Math.floor((task.progress_current * 100) / total) : 0;
}

export function CacheSettings() {
  const { t, i18n } = useTranslation();
  const status = useCacheStatus();
  const tasks = useActiveTasks();
  const move = useMoveCache();
  const [error, setError] = useState<string | null>(null);
  const moving = tasks.data?.find((task) => task.kind === "move_cache");
  const wasMoving = useRef(false);

  // The move finished (or stopped): show the new folder and sizes.
  const refetch = status.refetch;
  useEffect(() => {
    if (wasMoving.current && !moving) void refetch();
    wasMoving.current = Boolean(moving);
  }, [moving, refetch]);

  const cache = status.data;
  if (!cache) return null;
  const size = (bytes: number) => formatBytes(bytes, i18n.language);

  const moveTo = async (folder: string) => {
    const target = cacheTarget(folder);
    const ok = await confirmAction(
      t("settings.cacheMoveConfirm", { size: size(cache.total_bytes), folder: target }),
      {
        title: t("settings.cacheMove"),
        okLabel: t("settings.cacheMove"),
        cancelLabel: t("settings.cancel"),
      },
    );
    if (!ok) return;
    setError(null);
    move.mutate(target, {
      onError: (failure) => {
        if (failure instanceof ApiError && failure.code === "cache_move_failed") {
          const { needed_bytes: needed, free_bytes: free } = failure.details;
          setError(
            t("settings.cacheNoSpace", { needed: size(Number(needed)), free: size(Number(free)) }),
          );
        } else {
          setError(failure instanceof ApiError ? failure.message : t("settings.backupFailed"));
        }
      },
    });
  };

  const choose = async () => {
    const folder = await pickDirectory(t("settings.cacheFolder"));
    if (folder) await moveTo(folder);
  };

  const busy = Boolean(moving) || move.isPending;
  const custom = cache.folder !== cache.default_folder;

  return (
    <div className="space-y-3">
      <p className="max-w-lg text-xs leading-relaxed text-subtle-foreground">
        {t("settings.cacheHint")}
      </p>
      <dl className="divide-y rounded-lg border bg-card text-[13px]">
        <Row label={t("settings.cacheFolder")}>
          <span className="flex min-w-0 items-center gap-2">
            <span
              className="truncate font-mono text-[11.5px] text-muted-foreground"
              title={cache.folder}
            >
              {cache.folder}
            </span>
            <Button size="sm" variant="secondary" disabled={busy} onClick={() => void choose()}>
              <FolderInput /> {t("settings.change")}
            </Button>
            {custom && (
              <Button
                size="sm"
                variant="ghost"
                disabled={busy}
                onClick={() => void moveTo(cache.default_folder)}
              >
                {t("settings.backupFolderDefault")}
              </Button>
            )}
          </span>
        </Row>
        <Row label={t("settings.cacheSize")}>
          <span className="text-right text-xs text-muted-foreground">
            <span className="block text-[13px] text-foreground">{size(cache.total_bytes)}</span>
            <span className="block">
              {t("settings.cacheParts", {
                previews: size(cache.previews.bytes),
                thumbs: size(cache.thumbs.bytes),
                full: size(cache.full.bytes),
              })}
            </span>
            {cache.free_bytes !== null && (
              <span className="block">{t("settings.cacheFree", { free: size(cache.free_bytes) })}</span>
            )}
          </span>
        </Row>
      </dl>

      {!cache.folder_available && cache.configured_folder && (
        <p className="flex max-w-xl items-start gap-1.5 text-xs leading-relaxed text-destructive">
          <AlertTriangle className="mt-px size-3.5 shrink-0" />
          {t("settings.cacheMissing", { folder: cache.configured_folder })}
        </p>
      )}
      {moving && (
        <p role="status" className="flex items-center gap-1.5 text-xs text-muted-foreground">
          <Loader2 className="size-3.5 animate-spin text-highlight" />
          {moving.status === "running"
            ? t("settings.cacheMoving", { percent: percent(moving) })
            : t("settings.cacheMoveQueued")}
        </p>
      )}
      {error && (
        <p role="alert" className={cn("max-w-xl select-text text-xs leading-relaxed text-destructive")}>
          {error}
        </p>
      )}
    </div>
  );
}

function Row({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex min-h-11 items-center justify-between gap-4 px-4 py-2">
      <dt className="shrink-0 text-muted-foreground">{label}</dt>
      <dd className="flex min-w-0 justify-end">{children}</dd>
    </div>
  );
}
