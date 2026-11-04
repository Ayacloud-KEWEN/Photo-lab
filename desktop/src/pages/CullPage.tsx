import { Ban, Check, ClipboardCopy, Crown, ImageOff, Images, Loader2, Undo2 } from "lucide-react";
import { useState } from "react";
import { useTranslation } from "react-i18next";

import { api, thumbnailUrl } from "@/api/client";
import {
  useBatchUpdate,
  useConnection,
  useSimilarGroups,
  useSuspects,
  type SimilarParams,
} from "@/api/hooks";
import type { CullFlag, CullItem, SimilarGroup } from "@/api/types";
import { Button } from "@/components/ui/button";
import { cleanQuery, useLibraryState } from "@/library/state";
import { formatDateTime } from "@/lib/format";
import { cn } from "@/lib/utils";

type Tab = "similar" | "suspects";

const WINDOWS = [1, 10, 60] as const;
const SIMILARITIES = [
  ["loose", 0.85],
  ["normal", 0.9],
  ["strict", 0.95],
] as const;
const PAGE = 30;

/** Culling: similar photos to choose from, and photos that look like rejects. */
export function CullPage({ onShowLibrary }: { onShowLibrary: () => void }) {
  const { t } = useTranslation();
  const [tab, setTab] = useState<Tab>("similar");
  const { setQuery } = useLibraryState();
  const conn = useConnection();
  const [copied, setCopied] = useState<string | null>(null);

  const copyRejected = async () => {
    if (!conn) return;
    const files = await api.rejectedFiles(conn);
    try {
      await navigator.clipboard.writeText(files.paths.join("\r\n"));
      setCopied(t("cull.copied", { files: files.paths.length, count: files.asset_count }));
    } catch {
      setCopied(t("cull.copyFailed"));
    }
  };

  return (
    <div className="h-full overflow-y-auto px-6 py-5">
      <div className="mb-4 flex flex-wrap items-center gap-3">
        <h1 className="text-lg font-medium">{t("nav.cull")}</h1>
        <div role="tablist" className="flex h-7 rounded-md border p-0.5">
          {(["similar", "suspects"] as const).map((id) => (
            <button
              key={id}
              type="button"
              role="tab"
              aria-selected={tab === id}
              onClick={() => setTab(id)}
              className={cn(
                "rounded px-2.5 text-xs transition-colors",
                tab === id ? "bg-accent text-foreground" : "text-muted-foreground hover:text-foreground",
              )}
            >
              {t(`cull.tab_${id}`)}
            </button>
          ))}
        </div>
        <div className="ml-auto flex items-center gap-2">
          {copied && <span className="text-xs text-muted-foreground">{copied}</span>}
          <Button size="sm" variant="ghost" onClick={() => void copyRejected()}>
            <ClipboardCopy className="size-3.5" />
            {t("cull.copyRejected")}
          </Button>
          <Button
            size="sm"
            variant="secondary"
            onClick={() => {
              setQuery(cleanQuery({ rejected: "only" }));
              onShowLibrary();
            }}
          >
            <Images className="size-3.5" />
            {t("cull.showRejected")}
          </Button>
        </div>
      </div>
      <p className="mb-5 max-w-3xl text-[12px] leading-relaxed text-muted-foreground">
        {t("cull.hint")}
      </p>
      {tab === "similar" ? <SimilarTab /> : <SuspectsTab />}
    </div>
  );
}

// --- Similar photos ------------------------------------------------------------------------

function SimilarTab() {
  const { t } = useTranslation();
  const [params, setParams] = useState<SimilarParams>({
    window_minutes: 10,
    similarity: 0.9,
    pending_only: true,
  });
  const [shown, setShown] = useState(PAGE);
  const groups = useSimilarGroups(params);
  const data = groups.data;

  return (
    <section>
      <div className="mb-4 flex flex-wrap items-center gap-3 text-xs">
        <label className="flex items-center gap-1.5 text-muted-foreground">
          {t("cull.window")}
          <select
            value={params.window_minutes}
            onChange={(event) => setParams({ ...params, window_minutes: Number(event.target.value) })}
            className="h-7 rounded-md border bg-background/60 px-2 text-foreground"
          >
            {WINDOWS.map((minutes) => (
              <option key={minutes} value={minutes} className="bg-popover">
                {t(`cull.window_${minutes}`)}
              </option>
            ))}
          </select>
        </label>
        <label className="flex items-center gap-1.5 text-muted-foreground">
          {t("cull.similarity")}
          <select
            value={params.similarity}
            onChange={(event) => setParams({ ...params, similarity: Number(event.target.value) })}
            className="h-7 rounded-md border bg-background/60 px-2 text-foreground"
          >
            {SIMILARITIES.map(([id, value]) => (
              <option key={id} value={value} className="bg-popover">
                {t(`cull.similarity_${id}`)}
              </option>
            ))}
          </select>
        </label>
        <label className="flex cursor-pointer items-center gap-1.5 text-muted-foreground">
          <input
            type="checkbox"
            checked={params.pending_only}
            onChange={(event) => setParams({ ...params, pending_only: event.target.checked })}
            className="size-3.5 accent-[var(--highlight)]"
          />
          {t("cull.pendingOnly")}
        </label>
        {data?.available && (
          <span className="text-muted-foreground">
            {t("cull.groupCount", { count: data.group_count, pending: data.pending_count })}
          </span>
        )}
        {groups.isFetching && <Loader2 className="size-3.5 animate-spin text-muted-foreground" />}
      </div>

      {data && !data.available && (
        <p className="rounded-md border bg-card px-4 py-3 text-[13px] text-muted-foreground">
          {t("cull.needsAi")}
        </p>
      )}
      {data?.available && data.groups.length === 0 && (
        <p className="text-[13px] text-muted-foreground">
          {params.pending_only ? t("cull.allDone") : t("cull.noGroups")}
        </p>
      )}
      <div className="space-y-4">
        {data?.groups.slice(0, shown).map((group) => (
          <GroupCard key={group.items.map((item) => item.asset.id).join("-")} group={group} />
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

function GroupCard({ group }: { group: SimilarGroup }) {
  const { t, i18n } = useTranslation();
  const batch = useBatchUpdate();
  const { openViewer } = useLibraryState();
  const ids = group.items.map((item) => item.asset.id);
  const first = group.items[0]?.asset.capture_time;
  const keepBest = () => {
    batch.mutate({ asset_ids: [group.recommended_id], cull_flag: "pick" });
    const others = ids.filter((id) => id !== group.recommended_id);
    batch.mutate({ asset_ids: others, cull_flag: "reject" });
  };

  return (
    <article
      aria-label={t("cull.group", { count: ids.length })}
      className="rounded-lg border bg-card p-3"
    >
      <header className="mb-2 flex flex-wrap items-center gap-2 text-[12px]">
        <span className="font-medium">{first ? formatDateTime(first, i18n.language) : ""}</span>
        <span className="text-muted-foreground">{t("cull.group", { count: ids.length })}</span>
        <span className="ml-auto flex gap-1.5">
          <Button size="sm" disabled={batch.isPending} onClick={keepBest}>
            <Crown className="size-3.5" />
            {t("cull.keepBest")}
          </Button>
          <Button
            size="sm"
            variant="secondary"
            disabled={batch.isPending}
            onClick={() => batch.mutate({ asset_ids: ids, cull_flag: "pick" })}
          >
            <Check className="size-3.5" />
            {t("cull.keepAll")}
          </Button>
        </span>
      </header>
      <div className="flex flex-wrap gap-2">
        {group.items.map((item) => (
          <CullTile
            key={item.asset.id}
            item={item}
            recommended={item.asset.id === group.recommended_id}
            onOpen={() => openViewer(ids, item.asset.id)}
          />
        ))}
      </div>
    </article>
  );
}

// --- Suspected rejects ---------------------------------------------------------------------

function SuspectsTab() {
  const { t } = useTranslation();
  const [pendingOnly, setPendingOnly] = useState(true);
  const [shown, setShown] = useState(PAGE * 2);
  const suspects = useSuspects(pendingOnly);
  const batch = useBatchUpdate();
  const { openViewer } = useLibraryState();
  const items = suspects.data?.items ?? [];
  const visible = items.slice(0, shown);
  const pending = visible.filter((item) => item.asset.cull_flag === "none");

  return (
    <section>
      <div className="mb-4 flex flex-wrap items-center gap-3 text-xs">
        <label className="flex cursor-pointer items-center gap-1.5 text-muted-foreground">
          <input
            type="checkbox"
            checked={pendingOnly}
            onChange={(event) => setPendingOnly(event.target.checked)}
            className="size-3.5 accent-[var(--highlight)]"
          />
          {t("cull.pendingOnly")}
        </label>
        {suspects.data && (
          <span className="text-muted-foreground">
            {t("cull.suspectCount", { count: suspects.data.total })}
          </span>
        )}
        {pending.length > 0 && (
          <Button
            size="sm"
            variant="secondary"
            className="ml-auto"
            disabled={batch.isPending}
            onClick={() =>
              batch.mutate({ asset_ids: pending.map((item) => item.asset.id), cull_flag: "reject" })
            }
          >
            <Ban className="size-3.5" />
            {t("cull.rejectShown", { count: pending.length })}
          </Button>
        )}
      </div>
      {suspects.data && items.length === 0 && (
        <p className="text-[13px] text-muted-foreground">{t("cull.noSuspects")}</p>
      )}
      <div className="flex flex-wrap gap-2">
        {visible.map((item) => (
          <CullTile
            key={item.asset.id}
            item={item}
            onOpen={() =>
              openViewer(
                visible.map((entry) => entry.asset.id),
                item.asset.id,
              )
            }
          />
        ))}
      </div>
      {items.length > shown && (
        <Button className="mt-4" size="sm" variant="secondary" onClick={() => setShown(shown + PAGE)}>
          {t("cull.more", { count: items.length - shown })}
        </Button>
      )}
    </section>
  );
}

// --- A photo with its flag, quality and keep / reject buttons ------------------------------

function CullTile({
  item,
  recommended = false,
  onOpen,
}: {
  item: CullItem;
  recommended?: boolean;
  onOpen: () => void;
}) {
  const { t } = useTranslation();
  const conn = useConnection();
  const batch = useBatchUpdate();
  const { asset, quality } = item;
  const [failed, setFailed] = useState(false);
  const flag = asset.cull_flag;
  const setFlag = (value: CullFlag) => batch.mutate({ asset_ids: [asset.id], cull_flag: value });
  const ratio = asset.width && asset.height ? asset.width / asset.height : 1.5;

  return (
    <figure
      className={cn(
        "group relative h-40 overflow-hidden rounded-md border-2 bg-black",
        recommended ? "border-highlight" : "border-transparent",
      )}
      style={{ width: `${Math.round(160 * Math.min(Math.max(ratio, 0.6), 1.8))}px` }}
    >
      <button
        type="button"
        aria-label={asset.file_name}
        onClick={onOpen}
        className="size-full"
      >
        {conn && !failed && (
          <img
            src={thumbnailUrl(conn, asset.id, asset.rendition_version)}
            alt=""
            loading="lazy"
            draggable={false}
            onError={() => setFailed(true)}
            className={cn("size-full object-cover", flag === "reject" && "opacity-35 grayscale")}
          />
        )}
        {failed && (
          <span className="flex size-full items-center justify-center bg-card text-subtle-foreground">
            <ImageOff className="size-6" />
          </span>
        )}
      </button>
      <span className="pointer-events-none absolute left-1.5 top-1.5 flex flex-wrap gap-1">
        {recommended && (
          <Badge tone="highlight">
            <Crown className="size-3" />
            {t("cull.recommended")}
          </Badge>
        )}
        {flag === "pick" && (
          <Badge tone="ok">
            <Check className="size-3" />
            {t("cull.flag_pick")}
          </Badge>
        )}
        {flag === "reject" && (
          <Badge tone="error">
            <Ban className="size-3" />
            {t("cull.flag_reject")}
          </Badge>
        )}
        {quality?.flags.map((name) => (
          <Badge key={name} tone="warn">
            {t(`cull.quality_${name}`)}
          </Badge>
        ))}
      </span>
      {quality && (
        <span className="pointer-events-none absolute bottom-1 left-1.5 rounded bg-black/60 px-1 text-[10px] text-white">
          {t("cull.sharpness", { value: Math.round(quality.sharpness * 100) })}
        </span>
      )}
      <span className="absolute bottom-1 right-1 flex gap-1 opacity-0 transition-opacity group-hover:opacity-100 group-focus-within:opacity-100">
        {flag !== "none" ? (
          <IconButton label={t("cull.unflag")} onClick={() => setFlag("none")}>
            <Undo2 className="size-3.5" />
          </IconButton>
        ) : null}
        {flag !== "pick" && (
          <IconButton label={t("cull.keep")} onClick={() => setFlag("pick")}>
            <Check className="size-3.5" />
          </IconButton>
        )}
        {flag !== "reject" && (
          <IconButton label={t("cull.reject")} onClick={() => setFlag("reject")}>
            <Ban className="size-3.5" />
          </IconButton>
        )}
      </span>
    </figure>
  );
}

function Badge({
  tone,
  children,
}: {
  tone: "highlight" | "ok" | "error" | "warn";
  children: React.ReactNode;
}) {
  return (
    <span
      className={cn(
        "flex items-center gap-0.5 rounded px-1 py-0.5 text-[10px] font-medium leading-none",
        tone === "highlight" && "bg-highlight text-background",
        tone === "ok" && "bg-emerald-600 text-white",
        tone === "error" && "bg-red-600 text-white",
        tone === "warn" && "bg-amber-500/90 text-black",
      )}
    >
      {children}
    </span>
  );
}

function IconButton({
  label,
  onClick,
  children,
}: {
  label: string;
  onClick: () => void;
  children: React.ReactNode;
}) {
  return (
    <button
      type="button"
      aria-label={label}
      title={label}
      onClick={onClick}
      className="flex size-7 items-center justify-center rounded-md bg-black/70 text-white hover:bg-black/90"
    >
      {children}
    </button>
  );
}
