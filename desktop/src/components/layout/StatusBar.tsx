import { Loader2 } from "lucide-react";
import { useTranslation } from "react-i18next";

import { useBackendStatus } from "@/api/backend-context";
import { useActiveTasks, useHealth, useStorageRoots } from "@/api/hooks";
import { LANGUAGES } from "@/i18n";
import { cn } from "@/lib/utils";

export function StatusBar() {
  const { t, i18n } = useTranslation();
  const backend = useBackendStatus();
  const health = useHealth();
  const roots = useStorageRoots();
  const tasks = useActiveTasks();
  const running = tasks.data?.find((task) => task.status === "running") ?? tasks.data?.[0];
  const rootName = roots.data?.find((root) => root.id === running?.storage_root_id)?.display_name;
  let taskLabel: string | null = null;
  if (running?.kind === "ai_download_model") {
    taskLabel = t("status.taskAiDownload", {
      done: (running.progress_current / 1024 ** 3).toFixed(1),
      total: ((running.progress_total ?? 0) / 1024 ** 3).toFixed(1),
    });
  } else if (running?.kind === "export_assets") {
    taskLabel = t("status.taskExport", {
      current: running.progress_current,
      total: running.progress_total ?? 0,
    });
  } else if (running?.kind === "ai_index_assets") {
    taskLabel = t("status.taskAiIndex", {
      current: running.progress_current,
      total: running.progress_total ?? 0,
    });
  } else if (running && rootName) {
    if (running.status === "pending") taskLabel = t("status.taskQueued", { name: rootName });
    else if (running.kind === "scan_storage_root")
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
