import { Check, Download, Loader2, Pause } from "lucide-react";
import { useState } from "react";
import { useTranslation } from "react-i18next";

import {
  useActiveTasks,
  useCancelTask,
  useSettings,
  useUpdateSettings,
  useVlmActions,
  useVlmStatus,
} from "@/api/hooks";
import type { VlmScope } from "@/api/types";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { cn } from "@/lib/utils";

const SCOPES: VlmScope[] = ["priority", "all"];

/**
 * The local vision-language model (Qwen through llama.cpp): it describes photos and reads
 * the text in them so both can be searched. Everything runs on this computer.
 */
export function VlmSettings() {
  const { t } = useTranslation();
  const settings = useSettings();
  const update = useUpdateSettings();
  const status = useVlmStatus();
  const { download } = useVlmActions();
  const tasks = useActiveTasks();
  const cancel = useCancelTask();
  const [folder, setFolder] = useState<string | null>(null);

  const data = status.data;
  const enabled = settings.data?.vlm_enabled ?? false;
  const reading = tasks.data?.find((task) => task.kind === "vlm_describe_assets");
  const downloading = tasks.data?.find((task) => task.kind === "vlm_download");
  const defaultModel = data?.models.find((model) => model.role === "default");
  const ready = !!data?.runtime_installed && !!defaultModel?.downloaded;
  const savedFolder = settings.data?.vlm_folder ?? "";
  const folderChanged = folder !== null && folder.trim() !== savedFolder;

  return (
    <div className="space-y-4">
      <label className="flex cursor-pointer items-start gap-3">
        <input
          type="checkbox"
          checked={enabled}
          disabled={!settings.data || update.isPending || (!ready && !enabled)}
          onChange={(event) => update.mutate({ vlm_enabled: event.target.checked })}
          className="mt-0.5 size-4 accent-[var(--highlight)]"
        />
        <span>
          <span className="block text-[13px]">{t("vlm.enable")}</span>
          <span className="mt-1 block max-w-lg text-xs leading-relaxed text-subtle-foreground">
            {t("vlm.hint")}
          </span>
        </span>
      </label>

      <div className="max-w-xl space-y-1.5">
        <span className="block text-[13px]">{t("vlm.folder")}</span>
        <div className="flex gap-2">
          <Input
            aria-label={t("vlm.folder")}
            placeholder={data?.folder ?? ""}
            value={folder ?? savedFolder}
            onChange={(event) => setFolder(event.target.value)}
            className="h-8 flex-1 font-mono text-[12px]"
          />
          <Button
            size="sm"
            disabled={!folderChanged || update.isPending}
            onClick={() =>
              update.mutate({ vlm_folder: folder!.trim() }, { onSuccess: () => setFolder(null) })
            }
          >
            {t("vlm.save")}
          </Button>
        </div>
        <p className="text-xs text-subtle-foreground">
          {data?.runtime_installed ? t("vlm.runtimeReady") : t("vlm.runtimeMissing")}
        </p>
      </div>

      <ul className="max-w-xl divide-y rounded-lg border bg-card">
        {data?.models.map((model) => (
          <li key={model.id} className="flex items-center gap-3 px-3 py-2 text-[12.5px]">
            <span className="min-w-0 flex-1">
              <span className="block truncate">{model.label}</span>
              <span className="block text-[11px] text-subtle-foreground">
                {t(`vlm.role_${model.role}`)} · {model.size_gb} GB · {model.licence}
              </span>
            </span>
            {model.downloaded && data.runtime_installed ? (
              <span className="flex items-center gap-1 text-xs text-muted-foreground">
                <Check className="size-3.5 text-success" />
                {t("vlm.downloaded")}
              </span>
            ) : (
              <Button
                size="sm"
                variant="secondary"
                disabled={!!downloading || download.isPending}
                onClick={() => download.mutate(model.id)}
              >
                <Download className="size-3.5" />
                {t("vlm.download")}
              </Button>
            )}
          </li>
        ))}
      </ul>
      {downloading && (
        <p role="status" className="flex items-center gap-2 text-xs text-muted-foreground">
          <Loader2 className="size-3.5 animate-spin" />
          {t("vlm.downloading", {
            done: (downloading.progress_current / 1000).toFixed(1),
            total: ((downloading.progress_total ?? 0) / 1000).toFixed(1),
          })}
        </p>
      )}

      <div role="radiogroup" aria-label={t("vlm.scope")} className="max-w-xl space-y-1.5">
        <span className="block text-[13px]">{t("vlm.scope")}</span>
        {SCOPES.map((scope) => (
          <label key={scope} className="flex cursor-pointer items-start gap-2 text-[12.5px]">
            <input
              type="radio"
              name="vlm-scope"
              checked={(settings.data?.vlm_scope ?? "priority") === scope}
              onChange={() => update.mutate({ vlm_scope: scope })}
              className="mt-0.5 accent-[var(--highlight)]"
            />
            <span>
              {t(`vlm.scope_${scope}`)}
              <span className="block text-[11.5px] text-subtle-foreground">
                {t(`vlm.scope_${scope}Hint`)}
              </span>
            </span>
          </label>
        ))}
      </div>

      {data && (
        <div className="flex flex-wrap items-center gap-3 text-xs text-muted-foreground">
          <span>{t("vlm.described", { count: data.described })}</span>
          {enabled && <span>{t("vlm.toRead", { count: data.to_read })}</span>}
          {data.requested > 0 && <span>{t("vlm.requested", { count: data.requested })}</span>}
          {reading && (
            <span className={cn("flex items-center gap-2", reading.status === "running" && "text-foreground")}>
              {reading.status === "running" && <Loader2 className="size-3.5 animate-spin" />}
              {t("status.taskVlm", {
                current: reading.progress_current,
                total: reading.progress_total ?? 0,
              })}
              <Button
                size="sm"
                variant="ghost"
                disabled={cancel.isPending}
                onClick={() => cancel.mutate(reading.id)}
              >
                <Pause className="size-3.5" />
                {t("vlm.pause")}
              </Button>
            </span>
          )}
        </div>
      )}
    </div>
  );
}
