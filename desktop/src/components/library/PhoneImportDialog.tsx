import { FolderOpen, Loader2, Smartphone, X } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";

import { ApiError } from "@/api/client";
import {
  useCancelTask,
  useImportFromPhone,
  usePhoneSummary,
  usePhones,
  useTask,
} from "@/api/hooks";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { pickDirectory } from "@/lib/dialogs";
import { formatBytes } from "@/lib/format";

function message(error: unknown): string {
  if (error instanceof ApiError) return error.message;
  return error instanceof Error ? error.message : String(error);
}

/** Copy the new photos and videos of a phone connected by cable, then follow the task. */
export function PhoneImportDialog({ onClose }: { onClose: () => void }) {
  const { t, i18n } = useTranslation();
  const rootRef = useRef<HTMLDivElement>(null);
  const [taskId, setTaskId] = useState<number | null>(null);
  const phones = usePhones(taskId === null);
  const phone = phones.data?.items[0] ?? null;
  const ready = phone?.status === "ready" ? phone.id : null;
  const summary = usePhoneSummary(ready);
  const [folder, setFolder] = useState<string | null>(null);
  const [edited, setEdited] = useState<boolean | null>(null);
  const start = useImportFromPhone();
  const cancel = useCancelTask();
  const task = useTask(taskId).data;
  const finished = task && !["pending", "running"].includes(task.status);
  const result = task?.result as
    { copied: number; folder: string } | null | undefined;

  const shownFolder = folder ?? phones.data?.folder ?? "";
  const includeEdited = edited ?? phones.data?.include_edited ?? false;
  const size = (bytes: number) => formatBytes(bytes, i18n.language);

  useEffect(() => rootRef.current?.focus(), [taskId]);

  const browse = async () => {
    const chosen = await pickDirectory(t("phone.pickFolder"));
    if (chosen) setFolder(chosen);
  };
  const submit = () => {
    if (!ready) return;
    start.mutate(
      {
        id: ready,
        body: {
          folder: folder?.trim() || null,
          include_edited: edited,
        },
      },
      { onSuccess: (started) => setTaskId(started.id) },
    );
  };

  const counted = summary.data;
  const total = task?.progress_total ?? null;
  const done = task?.progress_current ?? 0;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-6">
      <div
        ref={rootRef}
        role="dialog"
        aria-modal
        aria-label={t("phone.title")}
        tabIndex={-1}
        onKeyDown={(event) => {
          if (event.key === "Escape") onClose();
          event.stopPropagation();
        }}
        className="w-[460px] max-w-full rounded-lg border bg-popover p-5 shadow-xl outline-none"
      >
        <div className="mb-4 flex items-center gap-2">
          <Smartphone className="size-4 text-muted-foreground" />
          <h2 className="text-[14px] font-medium">{t("phone.title")}</h2>
          {phone && (
            <span className="text-[12px] text-muted-foreground">
              {phone.name}
            </span>
          )}
          <Button
            variant="ghost"
            size="icon-sm"
            className="ml-auto"
            aria-label={t("phone.close")}
            onClick={onClose}
          >
            <X className="size-4" />
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
            <div aria-live="polite" className="space-y-1.5">
              {phones.data && !phones.data.available ? (
                <p className="text-destructive">{t("phone.unavailable")}</p>
              ) : !phone ? (
                <>
                  <p className="flex items-center gap-2">
                    <Loader2 className="size-4 animate-spin text-highlight" />
                    {t("phone.searching")}
                  </p>
                  <p className="text-[11.5px] text-subtle-foreground">
                    {t("phone.driverHint")}
                  </p>
                </>
              ) : phone.status === "locked" ? (
                <p className="text-highlight">{t("phone.locked")}</p>
              ) : summary.isPending ? (
                <>
                  <p className="flex items-center gap-2">
                    <Loader2 className="size-4 animate-spin text-highlight" />
                    {t("phone.counting")}
                  </p>
                  <p className="text-[11.5px] text-subtle-foreground">{t("phone.countingHint")}</p>
                </>
              ) : summary.error ? (
                <p className="text-destructive">
                  {t("phone.countError", { message: message(summary.error) })}
                </p>
              ) : counted && counted.new_count === 0 ? (
                <p>{t("phone.nothingNew", { total: counted.total })}</p>
              ) : counted ? (
                <p>
                  {t("phone.summary", {
                    total: counted.total,
                    count: counted.new_count,
                    size: size(counted.new_bytes),
                  })}
                </p>
              ) : null}
            </div>

            <label className="block space-y-1.5">
              <span className="text-muted-foreground">{t("phone.folder")}</span>
              <div className="flex gap-2">
                <Input
                  value={shownFolder}
                  onChange={(event) => setFolder(event.target.value)}
                />
                <Button
                  type="button"
                  variant="secondary"
                  onClick={() => void browse()}
                >
                  <FolderOpen className="size-3.5" />
                  {t("phone.browse")}
                </Button>
              </div>
              <span className="block text-[11.5px] text-subtle-foreground">
                {t("phone.layout")}
              </span>
            </label>

            <label className="flex items-center gap-2">
              <input
                type="checkbox"
                checked={includeEdited}
                onChange={(event) => setEdited(event.target.checked)}
              />
              {t("phone.edited")}
            </label>

            <div className="space-y-1 text-[11.5px] text-subtle-foreground">
              <p>{t("phone.original")}</p>
              <p>{t("phone.note")}</p>
            </div>
            {start.error && (
              <p className="text-[12px] text-destructive">
                {message(start.error)}
              </p>
            )}

            <div className="flex justify-end gap-2">
              <Button type="button" variant="ghost" onClick={onClose}>
                {t("phone.cancel")}
              </Button>
              <Button
                type="submit"
                disabled={
                  !ready ||
                  !counted ||
                  counted.new_count === 0 ||
                  !shownFolder.trim() ||
                  start.isPending
                }
              >
                {t("phone.start", { count: counted?.new_count ?? 0 })}
              </Button>
            </div>
          </form>
        ) : (
          <div className="space-y-3 text-[12.5px]" aria-live="polite">
            {!finished && (
              <>
                <div className="flex items-center gap-2">
                  <Loader2 className="size-4 animate-spin text-highlight" />
                  {total === null
                    ? t("phone.listing")
                    : t("phone.progress", {
                        done: size(done),
                        total: size(total),
                      })}
                </div>
                <div className="h-1.5 overflow-hidden rounded bg-white/10">
                  <div
                    className="h-full bg-highlight transition-[width]"
                    style={{
                      width: `${total ? (done / Math.max(1, total)) * 100 : 0}%`,
                    }}
                  />
                </div>
                <p className="text-[11.5px] text-subtle-foreground">
                  {t("phone.background")}
                </p>
              </>
            )}
            {task?.status === "succeeded" && result && (
              <p>
                {t("phone.done", {
                  count: result.copied,
                  folder: result.folder,
                })}
              </p>
            )}
            {task?.status === "failed" && (
              <p className="text-destructive">
                {t("phone.error", { message: task.error ?? "" })}
              </p>
            )}
            {task?.status === "cancelled" && <p>{t("phone.cancelled")}</p>}
            <div className="flex justify-end gap-2">
              {!finished && task && (
                <Button
                  variant="ghost"
                  disabled={task.cancel_requested || cancel.isPending}
                  onClick={() => cancel.mutate(task.id)}
                >
                  {t("phone.stop")}
                </Button>
              )}
              <Button
                variant={finished ? "default" : "secondary"}
                onClick={onClose}
              >
                {finished ? t("phone.close") : t("phone.hide")}
              </Button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
