import { useQueryClient } from "@tanstack/react-query";
import {
  ChevronLeft,
  ChevronRight,
  Download,
  FolderPlus,
  Heart,
  Info,
  MapPinPlus,
  Maximize2,
  Minimize2,
  ScanSearch,
  SlidersHorizontal,
  Unplug,
  X,
} from "lucide-react";
import {
  useEffect,
  useRef,
  useState,
  type KeyboardEvent,
  type ReactNode,
  type RefObject,
} from "react";
import { useTranslation } from "react-i18next";

import {
  api,
  motionEffectOf,
  motionUrl,
  originalUrl,
  thumbnailUrl,
  type BackendConnection,
} from "@/api/client";
import {
  queryKeys,
  useAiStatus,
  useAsset,
  useConnection,
  useStorageRoots,
  useUpdateAsset,
  useVideoEdit,
} from "@/api/hooks";
import type { AssetDetail, CullFlag } from "@/api/types";
import { DevelopWorkspace, type DevelopKeyHandler } from "@/components/develop/DevelopWorkspace";
import { ZoomableImage, type ZoomHandle } from "@/components/viewer/ZoomableImage";
import { TrimmedVideo } from "@/components/develop/TrimmedVideo";
import { VideoWorkspace } from "@/components/develop/VideoWorkspace";
import { AssetDetails } from "@/components/layout/Inspector";
import { LiveIcon } from "@/components/library/LiveIcon";
import { StarRating } from "@/components/library/StarRating";
import { CullFlagToggle } from "@/components/library/CullFlagToggle";
import { IconButton } from "@/components/ui/icon-button";
import { useLibraryState } from "@/library/state";
import { formatDateTime } from "@/lib/format";
import { cn } from "@/lib/utils";

/** Formats the webview can decode itself, so the original can be shown at 100%. */
const BROWSER_IMAGE = new Set(["jpg", "jpeg", "jpe", "png"]);
/** Shown for zooming: the original file if the webview can decode it, else a rendition. */
function fullSource(conn: BackendConnection, detail: AssetDetail): string {
  const cover = detail.files.find((file) => file.id === detail.cover_file_id);
  const extension = cover?.path.split(".").pop()?.toLowerCase() ?? "";
  const version = detail.rendition_version ?? "";
  return !detail.is_edited && BROWSER_IMAGE.has(extension)
    ? originalUrl(conn, detail.id, version)
    : thumbnailUrl(conn, detail.id, version, "full");
}

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
  const { findSimilar, openExport, openCollect, openMapSend } = useLibraryState();
  const aiReady = !!aiStatus.data?.local.enabled && !!aiStatus.data?.local.model_downloaded;
  const roots = useStorageRoots();
  // The drive holding the original is unplugged: only the cached previews can be shown.
  const coverRoot = detail?.files.find((file) => file.id === detail.cover_file_id)?.storage_root_id;
  const offlineRoot = roots.data?.find((root) => root.id === coverRoot && !root.is_available);

  useEffect(() => rootRef.current?.focus(), []);
  const zoomRef = useRef<ZoomHandle>(null);
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
  const isPhoto = detail?.media_type === "photo";
  const isVideo = detail?.media_type === "video";
  const showDevelop = developing && (isPhoto || isVideo);
  const canZoom = isPhoto && !showDevelop;
  // Leaving develop removes the focused control: keep keyboard shortcuts working.
  useEffect(() => {
    if (!showDevelop) rootRef.current?.focus();
  }, [showDevelop]);

  const edit = (changes: { rating?: number; is_favorite?: boolean; cull_flag?: CullFlag }) =>
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
    else if (key === "Escape" && zoomed && canZoom) zoomRef.current?.reset();
    else if (key === "Escape") onClose();
    else if (key.toLowerCase() === "d" && (isPhoto || isVideo)) setDeveloping((value) => !value);
    else if (key === "ArrowLeft") go(-1);
    else if (key === "ArrowRight" || key === " ") go(1);
    else if (key === "Home") setIndex(0);
    else if (key === "End") setIndex(ids.length - 1);
    else if (/^[0-5]$/.test(key)) edit({ rating: Number(key) });
    else if (key.toLowerCase() === "f" && detail) edit({ is_favorite: !detail.is_favorite });
    else if (key.toLowerCase() === "x" && detail)
      edit({ cull_flag: detail.cull_flag === "reject" ? "none" : "reject" });
    else if (key.toLowerCase() === "p" && detail)
      edit({ cull_flag: detail.cull_flag === "pick" ? "none" : "pick" });
    else if (key.toLowerCase() === "z" && canZoom) zoomRef.current?.toggleActual();
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
              onClick={() => zoomRef.current?.toggleActual()}
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
          {(isPhoto || isVideo) && (
            <IconButton
              label={showDevelop ? t("develop.done") : t("develop.edit")}
              active={showDevelop}
              onClick={() => setDeveloping((value) => !value)}
            >
              <SlidersHorizontal />
            </IconButton>
          )}
          {detail && (
            <IconButton label={t("collections.addTo")} onClick={() => openCollect([id])}>
              <FolderPlus />
            </IconButton>
          )}
          {detail && (
            <IconButton label={t("export.action")} onClick={() => openExport([id])}>
              <Download />
            </IconButton>
          )}
          {detail?.media_type === "photo" && (
            <IconButton label={t("mapweb.send")} onClick={() => openMapSend([id])}>
              <MapPinPlus />
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
      {offlineRoot && (
        <div
          role="status"
          className="flex shrink-0 items-center justify-center gap-2 bg-amber-500/15 px-3 py-1.5 text-[12px] text-amber-200"
        >
          <Unplug className="size-3.5 shrink-0" />
          {t("viewer.driveOffline", { name: offlineRoot.display_name })}
        </div>
      )}

      {showDevelop && conn && detail && isVideo ? (
        <VideoWorkspace
          key={detail.id}
          detail={detail}
          posterSrc={
            detail.rendition_version
              ? thumbnailUrl(conn, detail.id, detail.rendition_version, "preview")
              : undefined
          }
          onExit={() => setDeveloping(false)}
          keysRef={developKeys}
          overlay={navigation}
        />
      ) : showDevelop && conn && detail ? (
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
              zoomRef={zoomRef}
              onZoomedChange={setZoomed}
              fullSrc={fullSource(conn, detail)}
              previewSrc={
                detail.rendition_version
                  ? thumbnailUrl(conn, detail.id, detail.rendition_version, "preview")
                  : undefined
              }
              originalSrc={originalUrl(conn, detail.id, detail.rendition_version ?? "")}
              motionSrc={
                // A long exposure is a still picture: its clip is not played.
                detail.motion_file_id && detail.live_effect !== "long_exposure"
                  ? motionUrl(
                      conn,
                      detail.id,
                      detail.rendition_version ?? "",
                      motionEffectOf(detail.live_effect),
                    )
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
        {detail && (
          <CullFlagToggle dark value={detail.cull_flag} onChange={(flag) => edit({ cull_flag: flag })} />
        )}
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
  zoomRef,
  onZoomedChange,
  previewSrc,
  fullSrc,
  originalSrc,
  motionSrc,
}: {
  detail: AssetDetail;
  zoomRef: RefObject<ZoomHandle | null>;
  onZoomedChange: (zoomed: boolean) => void;
  previewSrc: string | undefined;
  fullSrc: string;
  originalSrc: string;
  motionSrc: string | undefined;
}) {
  const { t } = useTranslation();
  const [videoFailed, setVideoFailed] = useState(false);
  const [zoomed, setZoomed] = useState(false);

  if (detail.media_type === "video" && detail.is_edited) {
    return videoFailed ? (
      <VideoUnsupported previewSrc={previewSrc} />
    ) : (
      <EditedVideo
        key={detail.id}
        assetId={detail.id}
        src={originalSrc}
        poster={previewSrc}
        onError={() => setVideoFailed(true)}
      />
    );
  }
  if (detail.media_type === "video") {
    return videoFailed ? (
      <VideoUnsupported previewSrc={previewSrc} />
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
  const long = Math.max(detail.metadata.width ?? 0, detail.metadata.height ?? 0);
  const still = (
    <ZoomableImage
      key={detail.id}
      ref={zoomRef}
      previewSrc={previewSrc}
      fullSrc={fullSrc}
      fullLongEdge={long || null}
      onZoomedChange={(value) => {
        setZoomed(value);
        onZoomedChange(value);
      }}
    />
  );
  const effect = motionEffectOf(detail.live_effect);
  if (motionSrc && effect !== "live") {
    return (
      <LiveLoop
        key={`${detail.id}-${effect}`}
        still={still}
        motionSrc={motionSrc}
        label={t(`develop.live.effects.${effect}`)}
        hidden={zoomed}
      />
    );
  }
  return (
    <div className="relative size-full">
      {motionSrc ? (
        <LivePhoto key={detail.id} still={still} motionSrc={motionSrc} hidden={zoomed} />
      ) : (
        still
      )}
      {detail.live_effect === "long_exposure" && !zoomed && (
        <span className="pointer-events-none absolute left-4 top-4 rounded-full bg-black/50 px-2 py-1 text-[11px] font-semibold tracking-wide text-white/90">
          {t("develop.live.effects.long_exposure")}
        </span>
      )}
    </div>
  );
}

/** The still, with its motion clip played over it while the LIVE button is hovered. */
function LivePhoto({
  still,
  motionSrc,
  hidden,
}: {
  still: ReactNode;
  motionSrc: string;
  /** While zoomed in, the clip (fitted to the window) and its button are put away. */
  hidden: boolean;
}) {
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
      {!failed && !hidden && (
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

/** A Live Photo set to loop or bounce: it plays over the still, over and over. */
function LiveLoop({
  still,
  motionSrc,
  label,
  hidden,
}: {
  still: ReactNode;
  motionSrc: string;
  label: string;
  hidden: boolean;
}) {
  const [playing, setPlaying] = useState(false);
  const [failed, setFailed] = useState(false);
  return (
    <div className="relative size-full">
      {still}
      {!failed && !hidden && (
        <>
          <video
            src={motionSrc}
            aria-label={label}
            muted
            playsInline
            autoPlay
            loop
            onPlaying={() => setPlaying(true)}
            onError={() => setFailed(true)}
            className={cn(
              "pointer-events-none absolute inset-0 size-full object-contain p-2 transition-opacity duration-300",
              playing ? "opacity-100" : "opacity-0",
            )}
          />
          <span className="pointer-events-none absolute left-4 top-4 flex items-center gap-1 rounded-full bg-black/50 px-2 py-1 text-[11px] font-semibold tracking-wide text-white/90">
            <LiveIcon className="size-3.5" />
            {label}
          </span>
        </>
      )}
    </div>
  );
}

function VideoUnsupported({ previewSrc }: { previewSrc: string | undefined }) {
  const { t } = useTranslation();
  return (
    <div className="flex size-full flex-col items-center justify-center gap-4 text-sm text-muted-foreground">
      {previewSrc && <img src={previewSrc} alt="" className="max-h-[60%] max-w-[80%] opacity-60" />}
      {t("viewer.videoUnsupported")}
    </div>
  );
}

/** An edited video plays as edited: its kept part, turned, muted if chosen. */
function EditedVideo({
  assetId,
  src,
  poster,
  onError,
}: {
  assetId: number;
  src: string;
  poster: string | undefined;
  onError: () => void;
}) {
  const edit = useVideoEdit(assetId);
  if (!edit.data) return null;
  return (
    <TrimmedVideo src={src} poster={poster} recipe={edit.data.recipe} autoPlay onError={onError} />
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

