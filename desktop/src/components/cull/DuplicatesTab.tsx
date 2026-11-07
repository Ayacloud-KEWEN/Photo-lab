import {
  Ban,
  Check,
  Copy,
  FolderOpen,
  Heart,
  Loader2,
  Merge,
  SlidersHorizontal,
  Star,
} from "lucide-react";
import { useState } from "react";
import { useTranslation } from "react-i18next";

import { ApiError, thumbnailUrl } from "@/api/client";
import { useActiveTasks, useConnection, useDuplicateActions, useDuplicates } from "@/api/hooks";
import type { DuplicateAsset, DuplicateGroup, DuplicateKind } from "@/api/types";
import { Button } from "@/components/ui/button";
import { useLibraryState } from "@/library/state";
import { formatBytes, formatDateTime } from "@/lib/format";
import { cn } from "@/lib/utils";

const PAGE = 30;

/**
 * Photos listed more than once: identical files, or copies of one shot in other quality
 * (recompressed by a cloud export, converted, resized).
 */
export function DuplicatesTab() {
  const { t, i18n } = useTranslation();
  const [kind, setKind] = useState<DuplicateKind>("identical");
  const duplicates = useDuplicates(kind);
  const actions = useDuplicateActions();
  const [shown, setShown] = useState(PAGE);
  const [message, setMessage] = useState<string | null>(null);
  const data = duplicates.data;
  const copies = kind === "copies";

  const tasks = useActiveTasks();
  const merging = tasks.data?.some((task) => task.kind === "merge_duplicates") ?? false;
  const mergeAll = () => {
    setMessage(null);
    // Every group (there can be tens of thousands), in the background.
    actions.mergeAll.mutate(kind, {
      onSuccess: () => setMessage(t("cull.mergingAll")),
      onError: (error) =>
        setMessage(error instanceof ApiError ? error.message : t("cull.mergeFailed")),
    });
  };

  return (
    <section>
      <div
        role="radiogroup"
        aria-label={t("cull.duplicateKinds")}
        className="mb-4 inline-flex rounded-md border bg-background/40 p-0.5 text-[12px]"
      >
        {(["identical", "copies"] as const).map((value) => (
          <button
            key={value}
            type="button"
            role="radio"
            aria-checked={kind === value}
            onClick={() => {
              setKind(value);
              setShown(PAGE);
              setMessage(null);
            }}
            className={cn(
              "h-7 rounded px-3 text-muted-foreground hover:text-foreground",
              kind === value && "bg-white/10 text-foreground",
            )}
          >
            {value === "identical" ? t("cull.kindIdentical") : t("cull.kindCopies")}
          </button>
        ))}
      </div>
      <div className="mb-4 flex flex-wrap items-center gap-3 text-xs">
        {!data && duplicates.isPending && (
          <span role="status" className="flex items-center gap-1.5 text-muted-foreground">
            <Loader2 className="size-3.5 animate-spin" />
            {t("cull.finding")}
          </span>
        )}
        {data && (
          <span className="text-muted-foreground">
            {t(copies ? "cull.copyCount" : "cull.duplicateCount", {
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
        {data && data.group_count > 1 && (
          <Button
            size="sm"
            className="ml-auto"
            disabled={actions.mergeAll.isPending || merging}
            onClick={mergeAll}
          >
            <Merge className="size-3.5" />
            {t("cull.mergeAll", { count: data.group_count })}
          </Button>
        )}
      </div>
      <p className="mb-4 max-w-3xl text-[12px] leading-relaxed text-muted-foreground">
        {copies ? t("cull.copiesHint") : t("cull.duplicatesHint")}
      </p>
      {data && data.groups.length === 0 && (
        <p className="text-[13px] text-muted-foreground">
          {copies ? t("cull.noCopies") : t("cull.noDuplicates")}
        </p>
      )}
      <div className="space-y-3">
        {data?.groups.slice(0, shown).map((group) => (
          <DuplicateCard
            key={group.assets.map((a) => a.asset.id).join("-")}
            group={group}
            kind={kind}
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
  kind,
  onMessage,
}: {
  group: DuplicateGroup;
  kind: DuplicateKind;
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
                { groups: [{ asset_ids: ids, keep_asset_id: keep }], kind },
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
              showPicture={kind === "copies"}
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
  showPicture,
  kept,
  onKeep,
  onReveal,
}: {
  entry: DuplicateAsset;
  /** Copies differ in picture: show each one's size and format. */
  showPicture: boolean;
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
        {showPicture && asset.width && asset.height && (
          <span className="text-muted-foreground">
            {asset.width}×{asset.height} · {asset.formats.join(" + ")}
          </span>
        )}
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
