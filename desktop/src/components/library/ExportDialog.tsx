import { Download, FolderOpen, Loader2, X } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";

import { ApiError } from "@/api/client";
import { useCancelTask, useExportStatus, useStartExport } from "@/api/hooks";
import type { ExportRequest, VideoMode } from "@/api/types";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { useLibraryState, type ExportDialogRequest } from "@/library/state";
import { pickDirectory } from "@/lib/dialogs";

const SIZES = [null, 4096, 3840, 2560, 2048, 1600, 1080] as const;
const STORAGE_KEY = "lumen.export";

interface Remembered {
  destination: string;
  long_edge: number | null;
  quality: number;
  include_metadata: boolean;
  video_mode: VideoMode;
}

const DEFAULTS: Remembered = {
  destination: "",
  long_edge: null,
  quality: 90,
  include_metadata: true,
  video_mode: "copy",
};

/** The last choices (not the location setting: that is opted into for each export). */
function remembered(): Remembered {
  try {
    const stored = JSON.parse(localStorage.getItem(STORAGE_KEY) ?? "{}") as Partial<Remembered>;
    return { ...DEFAULTS, ...stored };
  } catch {
    return DEFAULTS;
  }
}

function remember(options: Remembered) {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(options));
  } catch {
    // Private mode or storage disabled: the defaults are fine next time.
  }
}

/** The folder of the last export (also used for saving video frames). */
export function rememberedExportFolder(): string {
  return remembered().destination;
}

export function rememberExportFolder(destination: string) {
  remember({ ...remembered(), destination });
}

/** Export photos (with their edits) as new JPEG files, then follow the background task. */
export function ExportDialog() {
  const { exportRequest, closeExport } = useLibraryState();
  if (!exportRequest) return null;
  return <ExportDialogBody key={exportRequest.nonce} request={exportRequest} onClose={closeExport} />;
}

function ExportDialogBody({
  request,
  onClose,
}: {
  request: ExportDialogRequest;
  onClose: () => void;
}) {
  const { t } = useTranslation();
  const rootRef = useRef<HTMLDivElement>(null);
  const [options, setOptions] = useState(remembered);
  const [includeLocation, setIncludeLocation] = useState(false);
  const [numbered, setNumbered] = useState(request.numbered);
  const start = useStartExport();
  const cancel = useCancelTask();
  const [taskId, setTaskId] = useState<number | null>(null);
  const status = useExportStatus(taskId);
  const task = status.data?.task;
  const result = status.data?.result;
  const finished = task && !["pending", "running"].includes(task.status);

  useEffect(() => rootRef.current?.focus(), []);

  const set = (patch: Partial<Remembered>) => setOptions((current) => ({ ...current, ...patch }));
  const browse = async () => {
    const folder = await pickDirectory(t("export.pickFolder"));
    if (folder) set({ destination: folder });
  };
  const submit = () => {
    const body: ExportRequest = {
      asset_ids: request.assetIds,
      destination: options.destination.trim(),
      long_edge: options.long_edge,
      quality: options.quality,
      include_metadata: options.include_metadata,
      include_location: options.include_metadata && includeLocation,
      video_mode: options.video_mode,
      numbered,
    };
    remember({ ...options, destination: body.destination });
    start.mutate(body, { onSuccess: (started) => setTaskId(started.task.id) });
  };
  const startError =
    start.error instanceof ApiError ? start.error.message : start.error ? String(start.error) : null;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-6">
      <div
        ref={rootRef}
        role="dialog"
        aria-modal
        aria-label={t("export.title")}
        tabIndex={-1}
        onKeyDown={(event) => {
          if (event.key === "Escape") onClose();
          event.stopPropagation();
        }}
        className="w-[440px] max-w-full rounded-lg border bg-popover p-5 shadow-xl outline-none"
      >
        <div className="mb-4 flex items-center gap-2">
          <Download className="size-4 text-muted-foreground" />
          <h2 className="text-[14px] font-medium">{t("export.title")}</h2>
          <span className="text-[12px] text-muted-foreground">
            {t("export.count", { count: request.assetIds.length })}
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

        {taskId === null ? (
          <form
            className="space-y-4 text-[12.5px]"
            onSubmit={(event) => {
              event.preventDefault();
              submit();
            }}
          >
            <label className="block space-y-1.5">
              <span className="text-muted-foreground">{t("export.folder")}</span>
              <div className="flex gap-2">
                <Input
                  value={options.destination}
                  onChange={(event) => set({ destination: event.target.value })}
                  placeholder="D:\Exports"
                  className="flex-1"
                />
                <Button type="button" variant="outline" onClick={() => void browse()}>
                  <FolderOpen /> {t("export.browse")}
                </Button>
              </div>
            </label>

            <label className="flex items-center justify-between gap-3">
              <span className="text-muted-foreground">{t("export.size")}</span>
              <select
                value={options.long_edge ?? ""}
                onChange={(event) =>
                  set({ long_edge: event.target.value ? Number(event.target.value) : null })
                }
                className="h-8 rounded-md border border-input bg-background/60 px-2"
              >
                {SIZES.map((size) => (
                  <option key={size ?? "full"} value={size ?? ""}>
                    {size === null ? t("export.fullSize") : t("export.longEdge", { size })}
                  </option>
                ))}
              </select>
            </label>

            <label className="block space-y-1">
              <span className="flex justify-between text-muted-foreground">
                {t("export.quality")}
                <span className="tabular-nums text-foreground">{options.quality}</span>
              </span>
              <input
                type="range"
                min={60}
                max={100}
                value={options.quality}
                onChange={(event) => set({ quality: Number(event.target.value) })}
                className="develop-slider w-full"
              />
            </label>

            <label className="flex items-center justify-between gap-3">
              <span className="text-muted-foreground">{t("export.videos")}</span>
              <select
                value={options.video_mode}
                onChange={(event) => set({ video_mode: event.target.value as VideoMode })}
                className="h-8 rounded-md border border-input bg-background/60 px-2"
              >
                <option value="copy">{t("export.videoCopy")}</option>
                <option value="h264">{t("export.videoH264")}</option>
              </select>
            </label>

            <div className="space-y-2">
              <label className="flex items-center gap-2">
                <input
                  type="checkbox"
                  checked={options.include_metadata}
                  onChange={(event) => set({ include_metadata: event.target.checked })}
                />
                {t("export.metadata")}
              </label>
              <label className="flex items-center gap-2 pl-5">
                <input
                  type="checkbox"
                  checked={options.include_metadata && includeLocation}
                  disabled={!options.include_metadata}
                  onChange={(event) => setIncludeLocation(event.target.checked)}
                />
                <span className={options.include_metadata ? "" : "opacity-50"}>
                  {t("export.location")}
                </span>
              </label>
            </div>

            <label className="flex items-center gap-2">
              <input
                type="checkbox"
                checked={numbered}
                onChange={(event) => setNumbered(event.target.checked)}
              />
              {t("export.numbered")}
            </label>

            <p className="text-[11.5px] text-subtle-foreground">{t("export.note")}</p>
            {startError && <p className="text-[12px] text-destructive">{startError}</p>}

            <div className="flex justify-end gap-2">
              <Button type="button" variant="ghost" onClick={onClose}>
                {t("export.cancel")}
              </Button>
              <Button type="submit" disabled={!options.destination.trim() || start.isPending}>
                {t("export.start", { count: request.assetIds.length })}
              </Button>
            </div>
          </form>
        ) : (
          <div className="space-y-3 text-[12.5px]" aria-live="polite">
            {!finished && (
              <>
                <div className="flex items-center gap-2">
                  <Loader2 className="size-4 animate-spin text-highlight" />
                  {t("export.progress", {
                    current: task?.progress_current ?? 0,
                    total: task?.progress_total ?? request.assetIds.length,
                  })}
                </div>
                <div className="h-1.5 overflow-hidden rounded bg-white/10">
                  <div
                    className="h-full bg-highlight transition-[width]"
                    style={{
                      width: `${((task?.progress_current ?? 0) / Math.max(1, task?.progress_total ?? request.assetIds.length)) * 100}%`,
                    }}
                  />
                </div>
                <p className="text-[11.5px] text-subtle-foreground">{t("export.background")}</p>
              </>
            )}
            {task?.status === "succeeded" && result && (
              <div className="space-y-1">
                <p>{t("export.done", { count: result.exported, folder: result.destination })}</p>
                {result.skipped > 0 && (
                  <p className="text-muted-foreground">
                    {t("export.skipped", { count: result.skipped })}
                  </p>
                )}
                {result.failed.length > 0 && (
                  <div className="text-destructive">
                    <p>{t("export.failed", { count: result.failed.length })}</p>
                    <ul className="mt-1 max-h-28 list-disc overflow-y-auto pl-5 text-[11.5px]">
                      {result.failed.map((failure) => (
                        <li key={failure.asset_id}>
                          {failure.file_name}: {failure.error}
                        </li>
                      ))}
                    </ul>
                  </div>
                )}
              </div>
            )}
            {task?.status === "failed" && (
              <p className="text-destructive">{t("export.error", { message: task.error ?? "" })}</p>
            )}
            {task?.status === "cancelled" && <p>{t("export.cancelled")}</p>}
            <div className="flex justify-end gap-2">
              {!finished && task && (
                <Button
                  variant="ghost"
                  disabled={task.cancel_requested || cancel.isPending}
                  onClick={() => cancel.mutate(task.id)}
                >
                  {t("export.stop")}
                </Button>
              )}
              <Button variant={finished ? "default" : "secondary"} onClick={onClose}>
                {finished ? t("export.close") : t("export.hide")}
              </Button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
