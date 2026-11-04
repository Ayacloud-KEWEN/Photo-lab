import { Ban, Check, Copy, FolderOpen, Heart, Merge, SlidersHorizontal, Star } from "lucide-react";
import { useState } from "react";
import { useTranslation } from "react-i18next";

import { ApiError, thumbnailUrl } from "@/api/client";
import { useConnection, useDuplicateActions, useDuplicates } from "@/api/hooks";
import type { DuplicateAsset, DuplicateGroup } from "@/api/types";
import { Button } from "@/components/ui/button";
import { useLibraryState } from "@/library/state";
import { formatBytes, formatDateTime } from "@/lib/format";
import { cn } from "@/lib/utils";

const PAGE = 30;

/** Photos listed more than once because their files are identical copies. */
export function DuplicatesTab() {
  const { t, i18n } = useTranslation();
  const duplicates = useDuplicates();
  const actions = useDuplicateActions();
  const [shown, setShown] = useState(PAGE);
  const [message, setMessage] = useState<string | null>(null);
  const data = duplicates.data;

  const mergeAll = () => {
    if (!data) return;
    setMessage(null);
    actions.merge.mutate(
      { groups: data.groups.map((group) => ({ asset_ids: group.assets.map((a) => a.asset.id) })) },
      {
        onSuccess: (result) => setMessage(t("cull.merged", { count: result.merged_groups })),
        onError: (error) =>
          setMessage(error instanceof ApiError ? error.message : t("cull.mergeFailed")),
      },
    );
  };

  return (
    <section>
      <div className="mb-4 flex flex-wrap items-center gap-3 text-xs">
        {data && (
          <span className="text-muted-foreground">
            {t("cull.duplicateCount", {
              count: data.group_count,
              size: formatBytes(data.redundant_bytes, i18n.language),
            })}
          </span>
        )}
        {message && (
          <span role="status" className="text-muted-foreground">
            {message}
          </span>
        )}
        {data && data.groups.length > 1 && (
          <Button
            size="sm"
            className="ml-auto"
            disabled={actions.merge.isPending}
            onClick={mergeAll}
          >
            <Merge className="size-3.5" />
            {t("cull.mergeAll", { count: data.groups.length })}
          </Button>
        )}
      </div>
      <p className="mb-4 max-w-3xl text-[12px] leading-relaxed text-muted-foreground">
        {t("cull.duplicatesHint")}
      </p>
      {data && data.groups.length === 0 && (
        <p className="text-[13px] text-muted-foreground">{t("cull.noDuplicates")}</p>
      )}
      <div className="space-y-3">
        {data?.groups.slice(0, shown).map((group) => (
          <DuplicateCard
            key={group.assets.map((a) => a.asset.id).join("-")}
            group={group}
            onMessage={setMessage}
          />
        ))}
      </div>
      {data && data.groups.length > shown && (
        <Button className="mt-4" size="sm" variant="secondary" onClick={() => setShown(shown + PAGE)}>
          {t("cull.more", { count: data.groups.length - shown })}
        </Button>
      )}
    </section>
  );
}

function DuplicateCard({
  group,
  onMessage,
}: {
  group: DuplicateGroup;
  onMessage: (message: string | null) => void;
}) {
  const { t, i18n } = useTranslation();
  const conn = useConnection();
  const actions = useDuplicateActions();
  const { openViewer } = useLibraryState();
  const [keep, setKeep] = useState(group.keep_asset_id);
  const ids = group.assets.map((entry) => entry.asset.id);
  const cover = group.assets.find((entry) => entry.asset.id === keep)?.asset ?? group.assets[0]!.asset;

  return (
    <article
      aria-label={t("cull.copies", { count: group.assets.length })}
      className="flex gap-4 rounded-lg border bg-card p-3"
    >
      <button
        type="button"
        aria-label={cover.file_name}
        onClick={() => openViewer(ids, cover.id)}
        className="h-28 w-36 shrink-0 overflow-hidden rounded-md bg-black"
      >
        {conn && (
          <img
            src={thumbnailUrl(conn, cover.id, cover.rendition_version)}
            alt=""
            loading="lazy"
            className="size-full object-cover"
          />
        )}
      </button>
      <div className="min-w-0 flex-1">
        <header className="mb-2 flex flex-wrap items-center gap-2 text-[12px]">
          <Copy className="size-3.5 text-muted-foreground" />
          <span className="font-medium">{t("cull.copies", { count: group.assets.length })}</span>
          <span className="text-muted-foreground">
            {t("cull.redundant", { size: formatBytes(group.redundant_bytes, i18n.language) })}
          </span>
          <Button
            size="sm"
            className="ml-auto"
            disabled={actions.merge.isPending}
            onClick={() =>
              actions.merge.mutate(
                { groups: [{ asset_ids: ids, keep_asset_id: keep }] },
                {
                  onSuccess: () => onMessage(t("cull.merged", { count: 1 })),
                  onError: (error) =>
                    onMessage(error instanceof ApiError ? error.message : t("cull.mergeFailed")),
                },
              )
            }
          >
            <Merge className="size-3.5" />
            {t("cull.merge")}
          </Button>
        </header>
        <ul className="space-y-2">
          {group.assets.map((entry) => (
            <CopyRow
              key={entry.asset.id}
              entry={entry}
              kept={entry.asset.id === keep}
              onKeep={() => setKeep(entry.asset.id)}
              onReveal={(fileId) => actions.reveal.mutate(fileId)}
            />
          ))}
        </ul>
      </div>
    </article>
  );
}

function CopyRow({
  entry,
  kept,
  onKeep,
  onReveal,
}: {
  entry: DuplicateAsset;
  kept: boolean;
  onKeep: () => void;
  onReveal: (fileId: number) => void;
}) {
  const { t, i18n } = useTranslation();
  const { asset } = entry;
  const primary = entry.files.filter((file) => file.role !== "sidecar");

  return (
    <li
      className={cn(
        "rounded-md border px-3 py-2 text-[12px]",
        kept ? "border-highlight/60 bg-highlight/5" : "border-transparent bg-background/40",
      )}
    >
      <label className="mb-1 flex cursor-pointer items-center gap-2">
        <input
          type="radio"
          checked={kept}
          onChange={onKeep}
          className="size-3.5 accent-[var(--highlight)]"
        />
        <span>{kept ? t("cull.keepThis") : t("cull.useThis")}</span>
        <span className="flex items-center gap-1.5 text-muted-foreground">
          {asset.rating > 0 && (
            <span className="flex items-center gap-0.5">
              <Star className="size-3 fill-current" />
              {asset.rating}
            </span>
          )}
          {asset.is_favorite && <Heart className="size-3 fill-current text-destructive" />}
          {asset.is_edited && <SlidersHorizontal className="size-3" aria-label={t("develop.edited")} />}
          {asset.cull_flag === "pick" && <Check className="size-3 text-emerald-400" />}
          {asset.cull_flag === "reject" && <Ban className="size-3 text-red-400" />}
          {entry.tag_count > 0 && <span>{t("cull.tagCount", { count: entry.tag_count })}</span>}
          {entry.collection_count > 0 && (
            <span>{t("cull.collectionCount", { count: entry.collection_count })}</span>
          )}
        </span>
      </label>
      {primary.map((file) => (
        <div key={file.file_id} className="flex items-center gap-2 pl-5.5 text-muted-foreground">
          <span className="min-w-0 flex-1 truncate font-mono text-[11px]" title={file.path}>
            {file.path}
          </span>
          <span className="shrink-0 text-[11px]">
            {formatBytes(file.size_bytes, i18n.language)} ·{" "}
            {formatDateTime(file.modified_at, i18n.language)}
          </span>
          <button
            type="button"
            aria-label={t("settings.reveal")}
            title={t("settings.reveal")}
            onClick={() => onReveal(file.file_id)}
            className="rounded p-1 hover:bg-accent hover:text-foreground"
          >
            <FolderOpen className="size-3.5" />
          </button>
        </div>
      ))}
    </li>
  );
}
