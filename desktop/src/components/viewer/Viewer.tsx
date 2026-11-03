import { useQueryClient } from "@tanstack/react-query";
import {
  ChevronLeft,
  ChevronRight,
  Heart,
  Info,
  Maximize2,
  Minimize2,
  X,
} from "lucide-react";
import { useEffect, useRef, useState, type KeyboardEvent, type ReactNode } from "react";
import { useTranslation } from "react-i18next";

import { api, originalUrl, thumbnailUrl } from "@/api/client";
import { queryKeys, useAsset, useConnection, useUpdateAsset } from "@/api/hooks";
import type { AssetDetail } from "@/api/types";
import { AssetDetails } from "@/components/layout/Inspector";
import { StarRating } from "@/components/library/StarRating";
import { Button } from "@/components/ui/button";
import { Tooltip } from "@/components/ui/tooltip";
import { useLibraryState } from "@/library/state";
import { formatDateTime } from "@/lib/format";
import { cn } from "@/lib/utils";

/** Formats the webview can decode itself, so the original can be shown at 100%. */
const BROWSER_IMAGE = new Set(["jpg", "jpeg", "jpe", "png"]);

export function Viewer() {
  const { viewer, closeViewer } = useLibraryState();
  if (!viewer || viewer.ids.length === 0) return null;
  return (
    <ViewerOverlay
      key={viewer.nonce}
      ids={viewer.ids}
      start={viewer.index}
      onClose={closeViewer}
    />
  );
}

function ViewerOverlay({
  ids,
  start,
  onClose,
}: {
  ids: readonly number[];
  start: number;
  onClose: () => void;
}) {
  const { t, i18n } = useTranslation();
  const conn = useConnection();
  const queryClient = useQueryClient();
  const rootRef = useRef<HTMLDivElement>(null);
  const [index, setIndex] = useState(start);
  const [zoomed, setZoomed] = useState(false);
  const [showInfo, setShowInfo] = useState(false);
  const id = ids[index]!;
  const asset = useAsset(id);
  const update = useUpdateAsset();
  const detail = asset.data;

  useEffect(() => rootRef.current?.focus(), []);
  useEffect(() => setZoomed(false), [id]);

  // Prefetch neighbours so moving through photos feels instant.
  useEffect(() => {
    if (!conn) return;
    for (const neighbour of [ids[index + 1], ids[index - 1]]) {
      if (neighbour === undefined) continue;
      void queryClient
        .fetchQuery({
          queryKey: queryKeys.asset(neighbour),
          queryFn: () => api.getAsset(conn, neighbour),
        })
        .then((next) => {
          if (next.media_type === "photo" && next.rendition_version) {
            new Image().src = thumbnailUrl(conn, next.id, next.rendition_version, "preview");
          }
        })
        .catch(() => undefined);
    }
  }, [conn, ids, index, queryClient]);

  const go = (step: number) =>
    setIndex((current) => Math.min(ids.length - 1, Math.max(0, current + step)));
  const cover = detail?.files.find((file) => file.id === detail.cover_file_id);
  const extension = cover?.path.split(".").pop()?.toLowerCase() ?? "";
  const canZoom = detail?.media_type === "photo" && BROWSER_IMAGE.has(extension);

  const edit = (changes: { rating?: number; is_favorite?: boolean }) =>
    update.mutate({ id, changes });

  const onKeyDown = (event: KeyboardEvent<HTMLDivElement>) => {
    if ((event.target as HTMLElement).closest("input, textarea")) return;
    const key = event.key;
    if (key === "Escape") onClose();
    else if (key === "ArrowLeft") go(-1);
    else if (key === "ArrowRight" || key === " ") go(1);
    else if (key === "Home") setIndex(0);
    else if (key === "End") setIndex(ids.length - 1);
    else if (/^[0-5]$/.test(key)) edit({ rating: Number(key) });
    else if (key.toLowerCase() === "f" && detail) edit({ is_favorite: !detail.is_favorite });
    else if (key.toLowerCase() === "z" && canZoom) setZoomed((value) => !value);
    else if (key.toLowerCase() === "i") setShowInfo((value) => !value);
    else return;
    event.preventDefault();
    event.stopPropagation();
  };

  return (
    <div
      ref={rootRef}
      role="dialog"
      aria-modal
      aria-label={detail ? fileName(detail) : undefined}
      tabIndex={-1}
      onKeyDown={onKeyDown}
      className="fixed inset-0 z-40 flex flex-col bg-[#0b0b0b] outline-none"
    >
      <header className="flex h-11 shrink-0 items-center gap-3 px-3 text-[12.5px]">
        <span className="min-w-0 truncate font-medium">{detail ? fileName(detail) : ""}</span>
        {detail?.capture_time && (
          <span className="shrink-0 text-muted-foreground">
            {formatDateTime(detail.capture_time, i18n.language)}
          </span>
        )}
        <span className="shrink-0 text-subtle-foreground">
          {t("viewer.position", { index: index + 1, total: ids.length })}
        </span>
        <div className="ml-auto flex items-center gap-1">
          {canZoom && (
            <IconButton
              label={zoomed ? t("viewer.fit") : t("viewer.actualSize")}
              onClick={() => setZoomed((value) => !value)}
            >
              {zoomed ? <Minimize2 /> : <Maximize2 />}
            </IconButton>
          )}
          <IconButton label={t("viewer.info")} active={showInfo} onClick={() => setShowInfo((v) => !v)}>
            <Info />
          </IconButton>
          <IconButton label={t("viewer.close")} onClick={onClose}>
            <X />
          </IconButton>
        </div>
      </header>

      <div className="flex min-h-0 flex-1">
        <div className="relative min-w-0 flex-1">
          {conn && detail && (
            <Stage
              detail={detail}
              zoomed={zoomed && canZoom}
              previewSrc={
                detail.rendition_version
                  ? thumbnailUrl(conn, detail.id, detail.rendition_version, "preview")
                  : undefined
              }
              originalSrc={originalUrl(conn, detail.id, detail.rendition_version ?? "")}
            />
          )}
          {index > 0 && (
            <NavButton side="left" label={t("viewer.previous")} onClick={() => go(-1)} />
          )}
          {index < ids.length - 1 && (
            <NavButton side="right" label={t("viewer.next")} onClick={() => go(1)} />
          )}
        </div>
        {showInfo && detail && (
          <aside className="w-80 shrink-0 overflow-y-auto border-l border-white/10 bg-panel p-4">
            <AssetDetails asset={detail} />
          </aside>
        )}
      </div>

      <footer className="flex h-11 shrink-0 items-center justify-center gap-4">
        <StarRating value={detail?.rating ?? 0} onChange={(rating) => edit({ rating })} />
        <button
          type="button"
          aria-pressed={detail?.is_favorite ?? false}
          aria-label={t("inspector.favorite")}
          onClick={() => detail && edit({ is_favorite: !detail.is_favorite })}
          className="p-1"
        >
          <Heart
            className={cn(
              "size-4",
              detail?.is_favorite ? "fill-destructive text-destructive" : "text-subtle-foreground",
            )}
          />
        </button>
      </footer>
    </div>
  );
}

function fileName(detail: AssetDetail): string {
  const cover = detail.files.find((file) => file.id === detail.cover_file_id) ?? detail.files[0];
  return cover?.relative_path.split(/[\\/]/).pop() ?? "";
}

function Stage({
  detail,
  zoomed,
  previewSrc,
  originalSrc,
}: {
  detail: AssetDetail;
  zoomed: boolean;
  previewSrc: string | undefined;
  originalSrc: string;
}) {
  const { t } = useTranslation();
  const [videoFailed, setVideoFailed] = useState(false);

  if (detail.media_type === "video") {
    return videoFailed ? (
      <div className="flex size-full flex-col items-center justify-center gap-4 text-sm text-muted-foreground">
        {previewSrc && <img src={previewSrc} alt="" className="max-h-[60%] max-w-[80%] opacity-60" />}
        {t("viewer.videoUnsupported")}
      </div>
    ) : (
      <video
        key={detail.id}
        src={originalSrc}
        poster={previewSrc}
        controls
        autoPlay
        onError={() => setVideoFailed(true)}
        className="size-full bg-black object-contain"
      />
    );
  }
  if (zoomed) {
    return (
      <div className="size-full overflow-auto">
        <div className="flex min-h-full min-w-full items-center justify-center">
          <img src={originalSrc} alt="" draggable={false} className="max-w-none" />
        </div>
      </div>
    );
  }
  return (
    <img
      key={detail.id}
      src={previewSrc}
      alt=""
      draggable={false}
      className="size-full select-none object-contain p-2"
    />
  );
}

function NavButton({
  side,
  label,
  onClick,
}: {
  side: "left" | "right";
  label: string;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      aria-label={label}
      title={label}
      onClick={onClick}
      className={cn(
        "absolute top-1/2 flex size-10 -translate-y-1/2 items-center justify-center rounded-full bg-black/40 text-white/80 opacity-0 transition-opacity hover:bg-black/60 hover:text-white focus-visible:opacity-100 [div:hover>&]:opacity-100",
        side === "left" ? "left-3" : "right-3",
      )}
    >
      {side === "left" ? <ChevronLeft className="size-5" /> : <ChevronRight className="size-5" />}
    </button>
  );
}

function IconButton({
  label,
  onClick,
  active,
  children,
}: {
  label: string;
  onClick: () => void;
  active?: boolean;
  children: ReactNode;
}) {
  return (
    <Tooltip label={label}>
      <Button
        variant="ghost"
        size="icon-sm"
        aria-label={label}
        aria-pressed={active}
        onClick={onClick}
        className={cn(active && "bg-accent text-foreground")}
      >
        {children}
      </Button>
    </Tooltip>
  );
}
