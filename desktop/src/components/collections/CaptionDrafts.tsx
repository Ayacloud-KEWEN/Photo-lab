import { Check, Loader2, Sparkles, X } from "lucide-react";
import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";

import { api } from "@/api/client";
import { useConnection, useTask } from "@/api/hooks";
import type { CollectionItem } from "@/api/types";
import { Button } from "@/components/ui/button";

/** Caption drafts of a collection: ask the local model, then accept or discard them. */
export function useCaptionDrafts(collectionId: number, refresh: () => unknown) {
  const { i18n } = useTranslation();
  const conn = useConnection();
  const [taskId, setTaskId] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);
  const task = useTask(taskId);
  const status = task.data?.status;
  const running =
    taskId !== null && status !== "succeeded" && status !== "failed" && status !== "cancelled";

  useEffect(() => {
    if (status === "succeeded") void refresh();
    if (status === "failed") setError(task.data?.error ?? null);
    // refresh changes identity on every render; the status is what matters.
  }, [status, task.data?.error]);

  const fail = (reason: unknown) =>
    setError(reason instanceof Error ? reason.message : String(reason));
  return {
    running,
    error,
    progress: task.data,
    start: (assetIds: number[] | null) => {
      if (!conn) return;
      setError(null);
      api
        .draftCollectionCaptions(conn, collectionId, {
          asset_ids: assetIds,
          language: i18n.language,
        })
        .then((started) => setTaskId(started.task_id))
        .catch(fail);
    },
    settle: (assetIds: number[] | null, accept: boolean) => {
      if (!conn) return;
      void api
        .settleCaptionDrafts(conn, collectionId, assetIds, accept)
        .then(() => refresh())
        .catch(fail);
    },
  };
}

export type CaptionDrafts = ReturnType<typeof useCaptionDrafts>;

/** The toolbar part: draft the missing captions, or accept / discard all drafts. */
export function DraftBar({ items, drafts }: { items: CollectionItem[]; drafts: CaptionDrafts }) {
  const { t } = useTranslation();
  const waiting = items.filter((item) => item.caption_draft).length;
  const missing = items.filter(
    (item) => !item.caption && !item.caption_draft && item.asset.media_type === "photo",
  ).length;
  const progress = drafts.progress;
  return (
    <>
      <Button
        variant="ghost"
        size="sm"
        disabled={drafts.running || missing === 0}
        title={t("collections.draftHint")}
        onClick={() => drafts.start(null)}
      >
        {drafts.running ? <Loader2 className="animate-spin" /> : <Sparkles />}
        {drafts.running
          ? t("collections.drafting", {
              done: progress?.progress_current ?? 0,
              total: progress?.progress_total ?? 0,
            })
          : t("collections.draftMissing", { count: missing })}
      </Button>
      {waiting > 0 && !drafts.running && (
        <>
          <Button variant="secondary" size="sm" onClick={() => drafts.settle(null, true)}>
            <Check /> {t("collections.draftAcceptAll", { count: waiting })}
          </Button>
          <Button variant="ghost" size="sm" onClick={() => drafts.settle(null, false)}>
            {t("collections.draftDiscardAll")}
          </Button>
        </>
      )}
      {drafts.error && (
        <span role="alert" className="text-destructive">
          {drafts.error}
        </span>
      )}
    </>
  );
}

/** Under a caption: the suggested one, to accept or discard. */
export function DraftLine({
  draft,
  name,
  onAccept,
  onDiscard,
}: {
  draft: string;
  name: string;
  onAccept: () => void;
  onDiscard: () => void;
}) {
  const { t } = useTranslation();
  return (
    <div className="flex items-start gap-1.5 border-t border-dashed border-white/10 bg-white/[0.03] px-2.5 py-1.5 text-[11.5px]">
      <Sparkles className="mt-0.5 size-3 shrink-0 text-highlight" />
      <span className="min-w-0 flex-1 italic text-muted-foreground">{draft}</span>
      <button
        type="button"
        aria-label={t("collections.draftAccept", { name })}
        title={t("collections.draftAcceptShort")}
        onClick={onAccept}
        className="rounded p-0.5 text-muted-foreground hover:bg-white/10 hover:text-foreground"
      >
        <Check className="size-3.5" />
      </button>
      <button
        type="button"
        aria-label={t("collections.draftDiscard", { name })}
        title={t("collections.draftDiscardShort")}
        onClick={onDiscard}
        className="rounded p-0.5 text-muted-foreground hover:bg-white/10 hover:text-foreground"
      >
        <X className="size-3.5" />
      </button>
    </div>
  );
}
