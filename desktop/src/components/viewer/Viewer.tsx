import { useQueryClient } from "@tanstack/react-query";
import {
  ChevronLeft,
  ChevronRight,
  Download,
  Heart,
  Info,
  Maximize2,
  Minimize2,
  ScanSearch,
  SlidersHorizontal,
  X,
} from "lucide-react";
import { useEffect, useRef, useState, type KeyboardEvent, type ReactNode } from "react";
import { useTranslation } from "react-i18next";

import { api, motionUrl, originalUrl, thumbnailUrl } from "@/api/client";
import { queryKeys, useAiStatus, useAsset, useConnection, useUpdateAsset } from "@/api/hooks";
import type { AssetDetail } from "@/api/types";
import { DevelopWorkspace, type DevelopKeyHandler } from "@/components/develop/DevelopWorkspace";
import { AssetDetails } from "@/components/layout/Inspector";
import { LiveIcon } from "@/components/library/LiveIcon";
import { StarRating } from "@/components/library/StarRating";
import { IconButton } from "@/components/ui/icon-button";
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
  const [developing, setDeveloping] = useState(false);
  const developKeys = useRef<DevelopKeyHandler | null>(null);
  const id = ids[index]!;
  const asset = useAsset(id);
  const update = useUpdateAsset();
  const detail = asset.data;
  const aiStatus = useAiStatus();
  const { findSimilar, openExport } = useLibraryState();
  const aiReady = !!aiStatus.data?.local.enabled && !!aiStatus.data?.local.model_downloaded;

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
  const isPhoto = detail?.media_type === "photo";
  const showDevelop = developing && isPhoto;
  // 1:1 shows the original file, so not for edited photos or while developing.
  const canZoom = isPhoto && BROWSER_IMAGE.has(extension) && !detail.is_edited && !showDevelop;
  // Leaving develop removes the focused control: keep keyboard shortcuts working.
  useEffect(() => {
    if (!showDevelop) rootRef.current?.focus();
  }, [showDevelop]);

  const edit = (changes: { rating?: number; is_favorite?: boolean }) =>
    update.mutate({ id, changes });

  const onKeyDown = (event: KeyboardEvent<HTMLDivElement>) => {
    const target = event.target as HTMLElement;
    const key = event.key;
    if (target.closest("textarea, input:not([type=range])")) return;
    // A focused slider keeps its own keys; shortcuts still work after dragging one.
    if (target.matches("input[type=range]") && /^(Arrow|Page|Home$|End$)/.test(key)) return;
    if (showDevelop && developKeys.current?.(event)) {
      event.preventDefault();
      event.stopPropagation();
      return;
    }
    if (key === "Escape" && showDevelop) setDeveloping(false);
    else if (key === "Escape") onClose();
    else if (key.toLowerCase() === "d" && isPhoto) setDeveloping((value) => !value);
    else if (key === "ArrowLeft") go(-1);
    else if (key === "ArrowRight" || key === " ") go(1);
    else if (key === "Home") setIndex(0);
    else if (key === "End") setIndex(ids.length - 1);
    else if (/^[0-5]$/.test(key)) edit({ rating: Number(key) });
    else if (key.toLowerCase() === "f" && detail) edit({ is_favorite: !detail.is_favorite });
    else if (key.toLowerCase() === "z" && canZoom) setZoomed((value) => !value);
    else if (key.toLowerCase() === "i" && !showDevelop) setShowInfo((value) => !value);
    else return;
    event.preventDefault();
    event.stopPropagation();
  };

  const navigation = (
    <>
      {index > 0 && <NavButton side="left" label={t("viewer.previous")} onClick={() => go(-1)} />}
      {index < ids.length - 1 && (
        <NavButton side="right" label={t("viewer.next")} onClick={() => go(1)} />
      )}
    </>
  );

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
          {aiReady && (
            <IconButton
              label={t("ai.findSimilar")}
              onClick={() => {
                findSimilar(id);
                onClose();
              }}
            >
              <ScanSearch />
            </IconButton>
          )}
          {isPhoto && (
            <IconButton
              label={showDevelop ? t("develop.done") : t("develop.edit")}
              active={showDevelop}
              onClick={() => setDeveloping((value) => !value)}
            >
              <SlidersHorizontal />
            </IconButton>
          )}
          {isPhoto && (
            <IconButton label={t("export.action")} onClick={() => openExport([id])}>
              <Download />
            </IconButton>
          )}
          {!showDevelop && (
            <IconButton
              label={t("viewer.info")}
              active={showInfo}
              onClick={() => setShowInfo((v) => !v)}
            >
              <Info />
            </IconButton>
          )}
          <IconButton label={t("viewer.close")} onClick={onClose}>
            <X />
          </IconButton>
        </div>
      </header>

      {showDevelop && conn && detail ? (
        <DevelopWorkspace
          key={detail.id}
          assetId={detail.id}
          placeholderSrc={
            detail.rendition_version
              ? thumbnailUrl(conn, detail.id, detail.rendition_version, "preview")
              : undefined
          }
          onExit={() => setDeveloping(false)}
          keysRef={developKeys}
          overlay={navigation}
        />
      ) : (
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
              motionSrc={
                detail.motion_file_id
                  ? motionUrl(conn, detail.id, detail.rendition_version ?? "")
                  : undefined
              }
            />
          )}
          {navigation}
        </div>
        {showInfo && detail && (
          <aside className="w-80 shrink-0 overflow-y-auto border-l border-white/10 bg-panel p-4">
            <AssetDetails asset={detail} />
          </aside>
        )}
      </div>
      )}

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
  motionSrc,
}: {
  detail: AssetDetail;
  zoomed: boolean;
  previewSrc: string | undefined;
  originalSrc: string;
  motionSrc: string | undefined;
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
  const still = (
    <img
      key={detail.id}
      src={previewSrc}
      alt=""
      draggable={false}
      className="size-full select-none object-contain p-2"
    />
  );
  return motionSrc ? <LivePhoto key={detail.id} still={still} motionSrc={motionSrc} /> : still;
}

/** The still, with its motion clip played over it while the LIVE button is hovered. */
function LivePhoto({ still, motionSrc }: { still: ReactNode; motionSrc: string }) {
  const { t } = useTranslation();
  const videoRef = useRef<HTMLVideoElement>(null);
  const [playing, setPlaying] = useState(false);
  const [failed, setFailed] = useState(false);

  const play = () => {
    const video = videoRef.current;
    if (!video || failed) return;
    video.currentTime = 0;
    setPlaying(true);
    video.play()?.catch(() => setFailed(true));
  };
  const stop = () => {
    videoRef.current?.pause();
    setPlaying(false);
  };

  return (
    <div className="relative size-full">
      {still}
      {!failed && (
        <>
          <video
            ref={videoRef}
            src={motionSrc}
            muted
            playsInline
            preload="auto"
            onEnded={stop}
            onError={() => {
              setFailed(true);
              setPlaying(false);
            }}
            className={cn(
              "pointer-events-none absolute inset-0 size-full object-contain p-2 transition-opacity duration-150",
              playing ? "opacity-100" : "opacity-0",
            )}
          />
          <button
            type="button"
            aria-label={t("viewer.livePlay")}
            title={t("viewer.livePlay")}
            aria-pressed={playing}
            onMouseEnter={play}
            onMouseLeave={stop}
            onFocus={play}
            onBlur={stop}
            className="absolute left-4 top-4 flex items-center gap-1 rounded-full bg-black/50 px-2 py-1 text-[11px] font-semibold tracking-wide text-white/90 hover:bg-black/70"
          >
            <LiveIcon className="size-3.5" />
            {t("viewer.live")}
          </button>
        </>
      )}
    </div>
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

