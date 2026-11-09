import { useQueryClient } from "@tanstack/react-query";
import { Cloud, Copy, Cpu, Loader2, Sparkles, X } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import Markdown from "react-markdown";

import { api } from "@/api/client";
import {
  useCollectionStories,
  useConnection,
  useTask,
  useVlmStatus,
} from "@/api/hooks";
import { Button } from "@/components/ui/button";
import { useLibraryState } from "@/library/state";
import { cn } from "@/lib/utils";

type Source = "local" | "cloud";

/**
 * A portfolio's travel story: written on this computer by the local model (from what it
 * read in the photos, their times and places), or by the cloud service (it asks first).
 */
export function StoryDialog({
  collectionId,
  assetIds,
  onClose,
}: {
  collectionId: number;
  assetIds: number[];
  onClose: () => void;
}) {
  const { t, i18n } = useTranslation();
  const conn = useConnection();
  const queryClient = useQueryClient();
  const { openCloud } = useLibraryState();
  const vlm = useVlmStatus();
  const stories = useCollectionStories(collectionId);
  const [taskId, setTaskId] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [shown, setShown] = useState(0);
  const [copied, setCopied] = useState(false);
  const task = useTask(taskId);
  const rootRef = useRef<HTMLDivElement>(null);
  useEffect(() => rootRef.current?.focus(), []);

  const installed =
    !!vlm.data?.runtime_installed &&
    vlm.data.models.some((m) => m.role === "default" && m.downloaded);
  const [source, setSource] = useState<Source | null>(null);
  const chosen: Source = source ?? (vlm.data && !installed ? "cloud" : "local");

  const status = task.data?.status;
  const running =
    taskId !== null &&
    status !== "succeeded" &&
    status !== "failed" &&
    status !== "cancelled";
  useEffect(() => {
    if (status === "succeeded") {
      setShown(0);
      void queryClient.invalidateQueries({
        queryKey: ["library", "collections", collectionId, "stories"],
      });
    }
    if (status === "failed")
      setError(task.data?.error ?? t("collections.storyFailed"));
  }, [status, collectionId, queryClient, task.data?.error, t]);

  const start = () => {
    if (!conn) return;
    setError(null);
    if (chosen === "cloud") {
      onClose();
      openCloud("story", assetIds.slice(0, 30));
      return;
    }
    api
      .writeCollectionStory(conn, collectionId, i18n.language)
      .then((started) => setTaskId(started.task_id))
      .catch((reason: unknown) =>
        setError(reason instanceof Error ? reason.message : String(reason)),
      );
  };

  const story = stories.data?.[shown];
  const copy = () => {
    if (!story) return;
    void navigator.clipboard?.writeText(story.result).then(() => {
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    });
  };
  const progress = task.data?.progress_total
    ? Math.round((100 * task.data.progress_current) / task.data.progress_total)
    : 0;
  const reading =
    task.data?.progress_total &&
    task.data.progress_current < task.data.progress_total - 1;

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-6"
      onClick={onClose}
    >
      <div
        ref={rootRef}
        role="dialog"
        aria-modal
        aria-label={t("collections.storyTitle")}
        tabIndex={-1}
        onClick={(event) => event.stopPropagation()}
        onKeyDown={(event) => {
          if (event.key === "Escape") onClose();
          event.stopPropagation();
        }}
        className="flex max-h-full w-[720px] max-w-full flex-col rounded-lg border bg-popover shadow-xl outline-none"
      >
        <div className="flex shrink-0 items-center gap-2 border-b px-5 py-3">
          <h2 className="text-[14px] font-medium">
            {t("collections.storyTitle")}
          </h2>
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

        <div className="shrink-0 space-y-3 border-b px-5 py-4">
          <div
            role="radiogroup"
            aria-label={t("collections.storySource")}
            className="grid gap-2 sm:grid-cols-2"
          >
            {(
              [
                {
                  id: "local",
                  icon: Cpu,
                  label: t("collections.storyLocal"),
                  hint: t("collections.storyLocalHint"),
                },
                {
                  id: "cloud",
                  icon: Cloud,
                  label: t("collections.storyCloud"),
                  hint: t("collections.storyCloudHint"),
                },
              ] as const
            ).map((option) => (
              <button
                key={option.id}
                type="button"
                role="radio"
                aria-checked={chosen === option.id}
                disabled={running}
                onClick={() => setSource(option.id)}
                className={cn(
                  "flex items-start gap-2.5 rounded-md border border-white/10 p-3 text-left hover:border-white/25",
                  chosen === option.id &&
                    "border-highlight bg-white/5 hover:border-highlight",
                )}
              >
                <option.icon className="mt-0.5 size-4 shrink-0" />
                <span>
                  <span className="block text-[13px] font-medium">
                    {option.label}
                  </span>
                  <span className="block text-[11.5px] leading-relaxed text-muted-foreground">
                    {option.hint}
                  </span>
                </span>
              </button>
            ))}
          </div>
          {chosen === "local" && vlm.data && !installed && (
            <p className="text-[12px] text-warning">
              {t("collections.storyNotInstalled")}
            </p>
          )}
          <div className="flex items-center gap-3">
            <Button
              onClick={start}
              disabled={running || (chosen === "local" && !installed)}
            >
              {running ? <Loader2 className="animate-spin" /> : <Sparkles />}
              {chosen === "cloud"
                ? t("collections.storyCloudStart")
                : stories.data?.length
                  ? t("collections.storyAgain")
                  : t("collections.storyStart")}
            </Button>
            {running && (
              <div className="min-w-0 flex-1 space-y-1">
                <p className="text-[12px] text-muted-foreground">
                  {status === "pending"
                    ? t("collections.storyQueued")
                    : reading
                      ? t("collections.storyReading", {
                          done: task.data?.progress_current ?? 0,
                          total: (task.data?.progress_total ?? 1) - 1,
                        })
                      : t("collections.storyWriting")}
                </p>
                <div className="h-1 overflow-hidden rounded bg-white/10">
                  <div
                    className="h-full bg-highlight transition-all"
                    style={{ width: `${progress}%` }}
                  />
                </div>
              </div>
            )}
          </div>
          {error && (
            <p role="alert" className="text-[12px] text-destructive">
              {error}
            </p>
          )}
        </div>

        <div className="min-h-0 flex-1 overflow-y-auto px-5 py-4">
          {story ? (
            <article className="space-y-3">
              <div className="prose-lumen select-text text-[13.5px] leading-relaxed">
                <Markdown>{story.result}</Markdown>
              </div>
              <div className="flex flex-wrap items-center gap-2 text-[11px] text-subtle-foreground">
                <span>
                  {t("collections.storyMeta", {
                    date: new Intl.DateTimeFormat(i18n.language, {
                      dateStyle: "medium",
                      timeStyle: "short",
                    }).format(new Date(story.created_at)),
                    count: story.asset_ids.length,
                  })}
                </span>
                {(stories.data?.length ?? 0) > 1 && (
                  <select
                    aria-label={t("collections.storyVersion")}
                    value={shown}
                    onChange={(event) => setShown(Number(event.target.value))}
                    className="h-7 rounded-md border border-input bg-background/60 px-1.5 text-foreground"
                  >
                    {stories.data!.map((item, index) => (
                      <option key={item.id} value={index}>
                        {t("collections.storyVersionN", {
                          n: stories.data!.length - index,
                        })}
                      </option>
                    ))}
                  </select>
                )}
                <Button
                  variant="ghost"
                  size="sm"
                  className="ml-auto"
                  onClick={copy}
                >
                  <Copy />{" "}
                  {copied
                    ? t("collections.storyCopied")
                    : t("collections.storyCopy")}
                </Button>
              </div>
            </article>
          ) : (
            !running && (
              <p className="text-[12.5px] text-muted-foreground">
                {t("collections.storyEmpty")}
              </p>
            )
          )}
        </div>
      </div>
    </div>
  );
}
