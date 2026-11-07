import { Loader2 } from "lucide-react";
import { useTranslation } from "react-i18next";

import { useBackendStatus } from "@/api/backend-context";
import { useActiveTasks, useHealth, useStorageRoots } from "@/api/hooks";
import { percent } from "@/components/settings/CacheSettings";
import { LANGUAGES } from "@/i18n";
import type zhCN from "@/i18n/locales/zh-CN";
import { cn } from "@/lib/utils";

// Names of the tasks that do not belong to a folder, for "… queued".
const KIND_LABELS: Record<string, `status.kind.${keyof typeof zhCN.status.kind}` | undefined> = {
  ai_index_assets: "status.kind.aiIndex",
  ai_download_model: "status.kind.aiDownload",
  quality_score_assets: "status.kind.quality",
  geo_locate_assets: "status.kind.places",
  export_assets: "status.kind.export",
  merge_duplicates: "status.kind.merge",
  db_backup: "status.kind.backup",
  move_cache: "status.kind.cache",
  mapweb_send: "status.kind.mapweb",
  pair_live_photos: "status.kind.live",
};

export function StatusBar() {
  const { t, i18n } = useTranslation();
  const backend = useBackendStatus();
  const health = useHealth();
  const roots = useStorageRoots();
  const tasks = useActiveTasks();
  const running = tasks.data?.find((task) => task.status === "running") ?? tasks.data?.[0];
  const rootName = roots.data?.find((root) => root.id === running?.storage_root_id)?.display_name;
  let taskLabel: string | null = null;
  const kindKey = running ? KIND_LABELS[running.kind] : undefined;
  if (running?.status === "pending") {
    // Nothing is running yet: the next task waits (e.g. for a drive or a retry delay).
    const name = rootName ?? (kindKey ? t(kindKey) : null);
    if (name) taskLabel = t("status.taskQueued", { name });
  } else if (running?.kind === "quality_score_assets") {
    taskLabel = t("status.taskQuality", {
      current: running.progress_current,
      total: running.progress_total ?? 0,
    });
  } else if (running?.kind === "move_cache") {
    taskLabel = t("status.taskCache", { percent: percent(running) });
  } else if (running?.kind === "pair_live_photos") {
    taskLabel = t("status.taskLive", {
      current: running.progress_current,
      total: running.progress_total ?? 0,
    });
  } else if (running?.kind === "mapweb_send") {
    taskLabel = t("status.taskMapWeb", {
      current: running.progress_current,
      total: running.progress_total ?? 0,
    });
  } else if (running?.kind === "db_backup") {
    taskLabel = t("status.taskBackup");
  } else if (running?.kind === "ai_download_model") {
    taskLabel = t("status.taskAiDownload", {
      done: (running.progress_current / 1024 ** 3).toFixed(1),
      total: ((running.progress_total ?? 0) / 1024 ** 3).toFixed(1),
    });
  } else if (running?.kind === "export_assets") {
    taskLabel = t("status.taskExport", {
      current: running.progress_current,
      total: running.progress_total ?? 0,
    });
  } else if (running?.kind === "merge_duplicates") {
    taskLabel = t("status.taskMerge", {
      current: running.progress_current,
      total: running.progress_total ?? 0,
    });
  } else if (running?.kind === "geo_locate_assets") {
    taskLabel = t("status.taskPlaces", {
      current: running.progress_current,
      total: running.progress_total ?? 0,
    });
  } else if (running?.kind === "ai_index_assets") {
    taskLabel = t("status.taskAiIndex", {
      current: running.progress_current,
      total: running.progress_total ?? 0,
    });
  } else if (running && rootName) {
    if (running.kind === "scan_storage_root")
      taskLabel = t("status.taskScanning", { name: rootName, count: running.progress_current });
    else
      taskLabel = t("status.taskIngesting", {
        name: rootName,
        current: running.progress_current,
        total: running.progress_total ?? 0,
      });
  }

  let tone: "pending" | "ok" | "error";
  let label: string;
  if (backend.state === "failed") {
    tone = "error";
    label = t("status.failed");
  } else if (backend.state === "starting" || (health.isPending && !health.isError)) {
    tone = "pending";
    label = t("status.starting");
  } else if (health.isError) {
    tone = "error";
    label = t("status.disconnected");
  } else {
    tone = "ok";
    label = t("status.connected");
  }

  const language = LANGUAGES.find((item) => item.code === i18n.language)?.label;

  return (
    <footer className="flex h-6 shrink-0 items-center gap-4 border-t bg-surface px-3 text-[11px] text-muted-foreground">
      <span
        className="flex items-center gap-1.5"
        title={backend.state === "failed" ? backend.message : undefined}
      >
        <span
          className={cn(
            "size-1.5 rounded-full",
            tone === "ok" && "bg-success",
            tone === "pending" && "animate-pulse bg-warning",
            tone === "error" && "bg-destructive",
          )}
        />
        {label}
      </span>
      {health.data && (
        <span>{t("status.schema", { version: health.data.database.schema_version })}</span>
      )}
      {roots.data && <span>{t("status.roots", { count: roots.data.length })}</span>}
      {taskLabel && (
        <span className="flex min-w-0 items-center gap-1.5 text-foreground">
          <Loader2 className="size-3 shrink-0 animate-spin text-highlight" />
          <span className="truncate">{taskLabel}</span>
        </span>
      )}
      <span className="ml-auto">{language}</span>
      <span>LUMEN Studio {health.data?.app_version ?? ""}</span>
    </footer>
  );
}
