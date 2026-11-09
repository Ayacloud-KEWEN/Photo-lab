import { useQueryClient } from "@tanstack/react-query";
import { Cloud, Copy, Cpu, Feather, Loader2, Send, Sparkles, X } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import Markdown from "react-markdown";

import { api } from "@/api/client";
import { useCollectionStories, useConnection, useTask, useVlmStatus } from "@/api/hooks";
import type { AnalysisResult, StoryWriter } from "@/api/types";
import { Button } from "@/components/ui/button";
import { useLibraryState } from "@/library/state";
import { cn } from "@/lib/utils";

const FAST = "qwen3.6-35b-a3b";
const FINE = "qwen3.8-27b";
const WRITER_LABELS: Record<string, string> = {
  [FAST]: "Qwen3.6",
  [FINE]: "Qwen3.8",
  deepseek: "DeepSeek",
};

interface StoryData {
  stage?: "notes" | "story";
  writer?: string;
  days?: { number: number; date: string; places: string[]; text: string }[];
}
const dataOf = (entry: AnalysisResult | undefined) => (entry?.data ?? {}) as StoryData;

/**
 * A portfolio's travel story. The local model picks the photos that tell each day, writes
 * notes for each day, then the story is written from the notes: by either local model, or
 * by DeepSeek, which gets the notes only, once the user has seen them.
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
  const [writer, setWriter] = useState<StoryWriter>(FAST);
  const [taskId, setTaskId] = useState<number | null>(null);
  const [sending, setSending] = useState(false);
  const [confirming, setConfirming] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [shown, setShown] = useState(0);
  const [copied, setCopied] = useState(false);
  const task = useTask(taskId);
  const rootRef = useRef<HTMLDivElement>(null);
  useEffect(() => rootRef.current?.focus(), []);

  const downloaded = (role: string) =>
    !!vlm.data?.runtime_installed && vlm.data.models.some((m) => m.role === role && m.downloaded);
  const installed = downloaded("default");
  const fineInstalled = downloaded("fine");

  const status = task.data?.status;
  const running =
    sending ||
    (taskId !== null && status !== "succeeded" && status !== "failed" && status !== "cancelled");
  useEffect(() => {
    if (status === "succeeded") {
      setShown(0);
      void queryClient.invalidateQueries({
        queryKey: ["library", "collections", collectionId, "stories"],
      });
    }
    if (status === "failed") setError(task.data?.error ?? t("collections.storyFailed"));
  }, [status, collectionId, queryClient, task.data?.error, t]);

  const entry = stories.data?.[shown];
  const data = dataOf(entry);
  const notesWaiting = data.stage === "notes";
  const days = (data.days ?? []).filter((day) => day.text);
  // Notes waiting for DeepSeek are confirmed right away; a story's notes when asked.
  const reviewing = entry && (notesWaiting || confirming === entry.id) ? entry : null;

  const start = (notesFrom: number | null) => {
    if (!conn) return;
    setError(null);
    setConfirming(null);
    if (writer === "deepseek" && notesFrom !== null) {
      setConfirming(notesFrom);
      return;
    }
    api
      .writeCollectionStory(conn, collectionId, {
        language: i18n.language,
        writer,
        notes_from: notesFrom,
      })
      .then((started) => setTaskId(started.task_id))
      .catch((reason: unknown) =>
        setError(reason instanceof Error ? reason.message : String(reason)),
      );
  };
  const send = (analysisId: number) => {
    if (!conn) return;
    setError(null);
    setSending(true);
    api
      .writeCollectionStoryInCloud(conn, collectionId, analysisId)
      .then(async () => {
        setConfirming(null);
        await queryClient.invalidateQueries({
          queryKey: ["library", "collections", collectionId, "stories"],
        });
        setShown(0);
      })
      .catch((reason: unknown) =>
        setError(reason instanceof Error ? reason.message : String(reason)),
      )
      .finally(() => setSending(false));
  };
  const copy = () => {
    if (!entry) return;
    void navigator.clipboard?.writeText(entry.result).then(() => {
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    });
  };

  const progress = task.data?.progress_total
    ? Math.round((100 * task.data.progress_current) / task.data.progress_total)
    : 0;
  const writers = [
    { id: FAST, icon: Cpu, label: t("collections.storyFast"), hint: t("collections.storyFastHint"), ok: installed },
    {
      id: FINE,
      icon: Feather,
      label: t("collections.storyFine"),
      hint: fineInstalled ? t("collections.storyFineHint") : t("collections.storyFineMissing"),
      ok: installed && fineInstalled,
    },
    { id: "deepseek", icon: Cloud, label: t("collections.storyDeepseek"), hint: t("collections.storyDeepseekHint"), ok: installed },
  ] as const; // prettier-ignore

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
        className="flex max-h-full w-[760px] max-w-full flex-col rounded-lg border bg-popover shadow-xl outline-none"
      >
        <div className="flex shrink-0 items-center gap-2 border-b px-5 py-3">
          <h2 className="text-[14px] font-medium">{t("collections.storyTitle")}</h2>
          <span className="text-[12px] text-muted-foreground">{t("collections.storyHow")}</span>
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
            className="grid gap-2 sm:grid-cols-3"
          >
            {writers.map((option) => (
              <button
                key={option.id}
                type="button"
                role="radio"
                aria-checked={writer === option.id}
                disabled={running || !option.ok}
                onClick={() => {
                  setWriter(option.id);
                  setConfirming(null);
                }}
                className={cn(
                  "flex items-start gap-2.5 rounded-md border border-white/10 p-3 text-left hover:border-white/25 disabled:opacity-50",
                  writer === option.id && "border-highlight bg-white/5 hover:border-highlight",
                )}
              >
                <option.icon className="mt-0.5 size-4 shrink-0" />
                <span>
                  <span className="block text-[13px] font-medium">{option.label}</span>
                  <span className="block text-[11.5px] leading-relaxed text-muted-foreground">
                    {option.hint}
                  </span>
                </span>
              </button>
            ))}
          </div>
          {vlm.data && !installed && (
            <p className="text-[12px] text-warning">{t("collections.storyNotInstalled")}</p>
          )}
          <div className="flex flex-wrap items-center gap-2">
            <Button onClick={() => start(null)} disabled={running || !installed}>
              {running ? <Loader2 className="animate-spin" /> : <Sparkles />}
              {stories.data?.length ? t("collections.storyAgain") : t("collections.storyStart")}
            </Button>
            {entry && days.length > 0 && !notesWaiting && (
              <Button
                variant="secondary"
                onClick={() => start(entry.id)}
                disabled={running || !installed}
              >
                {writer === "deepseek"
                  ? t("collections.storyNotesToCloud")
                  : t("collections.storyRewrite")}
              </Button>
            )}
            <Button
              variant="ghost"
              size="sm"
              className="ml-auto"
              disabled={running || assetIds.length < 2}
              onClick={() => {
                onClose();
                openCloud("story", assetIds.slice(0, 30));
              }}
            >
              <Cloud /> {t("collections.storyCloudImages")}
            </Button>
          </div>
          {taskId !== null && running && !sending && (
            <div className="space-y-1">
              <p className="text-[12px] text-muted-foreground">
                {status === "pending"
                  ? t("collections.storyQueued")
                  : t("collections.storyProgress", {
                      done: task.data?.progress_current ?? 0,
                      total: task.data?.progress_total ?? 0,
                    })}
              </p>
              <div className="h-1 overflow-hidden rounded bg-white/10">
                <div
                  className="h-full bg-highlight transition-all"
                  style={{ width: `${progress}%` }}
                />
              </div>
            </div>
          )}
          {error && (
            <p role="alert" className="text-[12px] text-destructive">
              {error}
            </p>
          )}
        </div>

        <div className="min-h-0 flex-1 overflow-y-auto px-5 py-4">
          {reviewing ? (
            <section aria-label={t("collections.storyReview")} className="space-y-3">
              <p className="rounded-md border border-white/10 bg-white/5 p-3 text-[12px] leading-relaxed text-muted-foreground">
                {t("collections.storyReviewHint")}
              </p>
              <div className="prose-lumen select-text text-[13px] leading-relaxed">
                {(dataOf(reviewing).days ?? [])
                  .filter((day) => day.text)
                  .map((day) => (
                    <div key={day.number}>
                      <h4>
                        {t("collections.routeDay", { day: day.number })}
                        {day.date && ` · ${day.date}`}
                        {day.places.length > 0 && ` · ${day.places.join("、")}`}
                      </h4>
                      <p>{day.text}</p>
                    </div>
                  ))}
              </div>
              <div className="flex gap-2">
                <Button onClick={() => send(reviewing.id)} disabled={running}>
                  {sending ? <Loader2 className="animate-spin" /> : <Send />}
                  {t("collections.storySend")}
                </Button>
                {!notesWaiting && (
                  <Button variant="ghost" onClick={() => setConfirming(null)}>
                    {t("export.cancel")}
                  </Button>
                )}
              </div>
            </section>
          ) : entry ? (
            <article className="space-y-3">
              <div className="prose-lumen select-text text-[13.5px] leading-relaxed">
                <Markdown>{entry.result}</Markdown>
              </div>
              {days.length > 0 && (
                <details className="rounded-md border border-white/10 px-3 py-2 text-[12px]">
                  <summary className="cursor-pointer text-muted-foreground">
                    {t("collections.storyNotes", { count: days.length })}
                  </summary>
                  <div className="mt-2 space-y-2">
                    {days.map((day) => (
                      <p key={day.number}>
                        <span className="font-medium">
                          {t("collections.routeDay", { day: day.number })}
                          {day.places.length > 0 && ` · ${day.places.join("、")}`}
                        </span>
                        <br />
                        {day.text}
                      </p>
                    ))}
                  </div>
                </details>
              )}
              <div className="flex flex-wrap items-center gap-2 text-[11px] text-subtle-foreground">
                <span>
                  {t("collections.storyMeta", {
                    date: new Intl.DateTimeFormat(i18n.language, {
                      dateStyle: "medium",
                      timeStyle: "short",
                    }).format(new Date(entry.created_at)),
                    writer: WRITER_LABELS[data.writer ?? entry.model] ?? entry.model,
                    count: entry.asset_ids.length,
                  })}
                </span>
                {(stories.data?.length ?? 0) > 1 && (
                  <select
                    aria-label={t("collections.storyVersion")}
                    value={shown}
                    onChange={(event) => {
                      setShown(Number(event.target.value));
                      setConfirming(null);
                    }}
                    className="h-7 rounded-md border border-input bg-background/60 px-1.5 text-foreground"
                  >
                    {stories.data!.map((item, index) => (
                      <option key={item.id} value={index}>
                        {t(
                          dataOf(item).stage === "notes"
                            ? "collections.storyVersionNotes"
                            : "collections.storyVersionN",
                          {
                            n: stories.data!.length - index,
                            writer: WRITER_LABELS[dataOf(item).writer ?? item.model] ?? item.model,
                          },
                        )}
                      </option>
                    ))}
                  </select>
                )}
                <Button variant="ghost" size="sm" className="ml-auto" onClick={copy}>
                  <Copy /> {copied ? t("collections.storyCopied") : t("collections.storyCopy")}
                </Button>
              </div>
            </article>
          ) : (
            !running && (
              <p className="text-[12.5px] text-muted-foreground">{t("collections.storyEmpty")}</p>
            )
          )}
        </div>
      </div>
    </div>
  );
}
