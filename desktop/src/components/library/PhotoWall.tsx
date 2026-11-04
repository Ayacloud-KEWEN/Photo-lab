import { useVirtualizer } from "@tanstack/react-virtual";
import { Ban, Check, Heart, Play, SlidersHorizontal, Star } from "lucide-react";
import {
  memo,
  useEffect,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
  type KeyboardEvent,
  type MouseEvent,
  type ReactNode,
} from "react";
import { useTranslation } from "react-i18next";

import { motionUrl, thumbnailUrl } from "@/api/client";
import { useConnection } from "@/api/hooks";
import type { AssetSummary } from "@/api/types";
import { LiveIcon } from "@/components/library/LiveIcon";
import {
  clampAspect,
  gridRows,
  justifiedRows,
  neighbor,
  type LayoutRow,
  type WallMode,
} from "@/library/layout";
import type { Modifiers, SelectionState } from "@/library/selection";
import { formatDuration } from "@/lib/format";
import { cn } from "@/lib/utils";

const GAP = 4;
const PADDING_X = 24;
const TARGET_ROW_HEIGHT = 220;
const MIN_GRID_CELL = 168;
const HEADER_HEIGHT = 48;
/** How long the LIVE badge must be hovered before the clip loads, so sweeping past it does not. */
const LIVE_HOVER_DELAY_MS = 250;

export interface WallGroup {
  key: string;
  title?: ReactNode;
  /** Height reserved for the title (default 48px). */
  titleHeight?: number;
  items: AssetSummary[];
}

type Entry =
  | { kind: "header"; key: string; title: ReactNode; height: number }
  | { kind: "row"; key: string; row: LayoutRow; height: number };

interface PhotoWallProps {
  groups: WallGroup[];
  mode: WallMode;
  selection: SelectionState;
  onSelect: (id: number, modifiers: Modifiers) => void;
  onOpen: (id: number) => void;
  /** Called when the end of the loaded items comes into view. */
  onReachEnd: () => void;
  /** Keys not handled by the wall itself (ratings, select all, …). */
  onKeyDown?: (event: KeyboardEvent<HTMLDivElement>) => void;
  footer?: ReactNode;
}

export function PhotoWall({
  groups,
  mode,
  selection,
  onSelect,
  onOpen,
  onReachEnd,
  onKeyDown,
  footer,
}: PhotoWallProps) {
  const scrollRef = useRef<HTMLDivElement>(null);
  const [width, setWidth] = useState(0);

  useLayoutEffect(() => {
    const element = scrollRef.current;
    if (!element) return;
    setWidth(element.clientWidth);
    // clientWidth excludes the scrollbar; padding is subtracted below.
    const observer = new ResizeObserver(() => setWidth(element.clientWidth));
    observer.observe(element);
    return () => observer.disconnect();
  }, []);

  const inner = Math.max(0, width - PADDING_X * 2);
  const byId = useMemo(() => {
    const map = new Map<number, AssetSummary>();
    for (const group of groups) for (const item of group.items) map.set(item.id, item);
    return map;
  }, [groups]);

  const entries = useMemo<Entry[]>(() => {
    const list: Entry[] = [];
    for (const group of groups) {
      if (group.title !== undefined) {
        list.push({
          kind: "header",
          key: `h:${group.key}`,
          title: group.title,
          height: group.titleHeight ?? HEADER_HEIGHT,
        });
      }
      const inputs = group.items.map((item) => ({
        id: item.id,
        aspect: clampAspect(item.width && item.height ? item.width / item.height : 1),
      }));
      const rows =
        mode === "justified"
          ? justifiedRows(inputs, inner, TARGET_ROW_HEIGHT, GAP)
          : gridRows(inputs, inner, MIN_GRID_CELL, GAP);
      rows.forEach((row, index) =>
        list.push({ kind: "row", key: `r:${group.key}:${index}`, row, height: row.height + GAP }),
      );
    }
    return list;
  }, [groups, mode, inner]);

  const rows = useMemo(
    () => entries.flatMap((entry) => (entry.kind === "row" ? [entry.row] : [])),
    [entries],
  );

  const virtualizer = useVirtualizer({
    count: entries.length,
    getScrollElement: () => scrollRef.current,
    estimateSize: (index) => entries[index]?.height ?? TARGET_ROW_HEIGHT,
    overscan: 6,
  });

  useEffect(() => {
    virtualizer.measure();
  }, [entries, virtualizer]);

  const visible = virtualizer.getVirtualItems();
  const lastVisible = visible.at(-1)?.index ?? -1;
  useEffect(() => {
    if (entries.length > 0 && lastVisible >= entries.length - 6) onReachEnd();
  }, [lastVisible, entries.length, onReachEnd]);

  // Keep the keyboard focus in view.
  const focused = selection.focused;
  const focusMovedByKey = useRef(false);
  useEffect(() => {
    if (!focusMovedByKey.current || focused === null) return;
    focusMovedByKey.current = false;
    const index = entries.findIndex(
      (entry) => entry.kind === "row" && entry.row.cells.some((cell) => cell.id === focused),
    );
    if (index >= 0) virtualizer.scrollToIndex(index, { align: "auto" });
  }, [focused, entries, virtualizer]);

  const handleKeyDown = (event: KeyboardEvent<HTMLDivElement>) => {
    const directions: Record<string, "left" | "right" | "up" | "down"> = {
      ArrowLeft: "left",
      ArrowRight: "right",
      ArrowUp: "up",
      ArrowDown: "down",
    };
    const direction = directions[event.key];
    const first = rows[0]?.cells[0]?.id;
    if (direction && first !== undefined) {
      event.preventDefault();
      const next = focused === null ? first : neighbor(rows, focused, direction);
      if (next !== null) {
        focusMovedByKey.current = true;
        onSelect(next, { range: event.shiftKey });
      }
      return;
    }
    if ((event.key === "Home" || event.key === "End") && first !== undefined) {
      event.preventDefault();
      const target = event.key === "Home" ? first : rows.at(-1)?.cells.at(-1)?.id;
      if (target !== undefined) {
        focusMovedByKey.current = true;
        onSelect(target, { range: event.shiftKey });
      }
      return;
    }
    if ((event.key === "Enter" || event.key === " ") && focused !== null) {
      event.preventDefault();
      onOpen(focused);
      return;
    }
    onKeyDown?.(event);
  };

  return (
    <div
      ref={scrollRef}
      tabIndex={0}
      role="grid"
      aria-multiselectable
      onKeyDown={handleKeyDown}
      className="h-full overflow-y-auto outline-none"
      style={{ paddingLeft: PADDING_X, paddingRight: PADDING_X }}
    >
      <div className="relative w-full" style={{ height: virtualizer.getTotalSize() }}>
        {visible.map((item) => {
          const entry = entries[item.index]!;
          if (entry.kind === "header") {
            return (
              <div
                key={entry.key}
                className="absolute left-0 top-0 flex w-full items-end pb-2 text-[13px] font-medium"
                style={{ transform: `translateY(${item.start}px)`, height: entry.height }}
              >
                {entry.title}
              </div>
            );
          }
          return (
            <div
              key={entry.key}
              role="row"
              className="absolute left-0 top-0 w-full"
              style={{ transform: `translateY(${item.start}px)`, height: entry.row.height }}
            >
              {entry.row.cells.map((cell) => {
                const asset = byId.get(cell.id);
                if (!asset) return null;
                return (
                  <Tile
                    key={cell.id}
                    asset={asset}
                    x={cell.x}
                    width={cell.width}
                    height={entry.row.height}
                    selected={selection.selected.has(cell.id)}
                    focused={focused === cell.id}
                    multi={selection.selected.size > 1}
                    onSelect={onSelect}
                    onOpen={onOpen}
                  />
                );
              })}
            </div>
          );
        })}
      </div>
      {footer}
    </div>
  );
}

interface TileProps {
  asset: AssetSummary;
  x: number;
  width: number;
  height: number;
  selected: boolean;
  focused: boolean;
  multi: boolean;
  onSelect: (id: number, modifiers: Modifiers) => void;
  onOpen: (id: number) => void;
}

const Tile = memo(function Tile({
  asset,
  x,
  width,
  height,
  selected,
  focused,
  multi,
  onSelect,
  onOpen,
}: TileProps) {
  const { t } = useTranslation();
  const conn = useConnection();
  const [failed, setFailed] = useState(false);
  const src = conn ? thumbnailUrl(conn, asset.id, asset.rendition_version) : undefined;

  // The clip is only mounted while the LIVE badge is hovered: no preloading across the wall.
  const [motion, setMotion] = useState<"off" | "loading" | "playing">("off");
  const [motionFailed, setMotionFailed] = useState(false);
  const motionTimer = useRef<number | undefined>(undefined);
  useEffect(() => () => window.clearTimeout(motionTimer.current), []);
  const startMotion = () => {
    if (motionFailed) return;
    window.clearTimeout(motionTimer.current);
    motionTimer.current = window.setTimeout(() => setMotion("loading"), LIVE_HOVER_DELAY_MS);
  };
  const stopMotion = () => {
    window.clearTimeout(motionTimer.current);
    setMotion("off");
  };

  const handleClick = (event: MouseEvent) =>
    onSelect(asset.id, { toggle: event.ctrlKey || event.metaKey, range: event.shiftKey });

  return (
    <div
      role="gridcell"
      aria-selected={selected}
      title={asset.file_name}
      onClick={handleClick}
      onDoubleClick={() => onOpen(asset.id)}
      className={cn(
        "group absolute top-0 cursor-default overflow-hidden bg-card",
        selected && "ring-2 ring-highlight ring-offset-1 ring-offset-background",
        focused && !selected && "ring-1 ring-foreground/50",
      )}
      style={{ left: x, width, height }}
    >
      {src && !failed ? (
        <img
          src={src}
          alt={asset.file_name}
          loading="lazy"
          decoding="async"
          draggable={false}
          onError={() => setFailed(true)}
          className={cn(
            "size-full object-cover",
            selected && "opacity-85",
            asset.cull_flag === "reject" && "opacity-40 grayscale",
          )}
        />
      ) : (
        <span className="flex size-full items-center justify-center p-2 text-[11px] text-subtle-foreground">
          {asset.file_name}
        </span>
      )}
      {conn && motion !== "off" && (
        <video
          src={motionUrl(conn, asset.id, asset.rendition_version)}
          muted
          playsInline
          autoPlay
          onPlaying={() => setMotion("playing")}
          onEnded={stopMotion}
          onError={() => {
            setMotionFailed(true); // e.g. no HEVC decoder: keep the thumbnail
            stopMotion();
          }}
          className={cn(
            "pointer-events-none absolute inset-0 size-full object-cover transition-opacity duration-150",
            motion === "playing" ? "opacity-100" : "opacity-0",
          )}
        />
      )}

      {multi && selected && (
        <span className="absolute left-1.5 top-1.5 flex size-5 items-center justify-center rounded-full bg-highlight text-background">
          <Check className="size-3.5" strokeWidth={3} />
        </span>
      )}
      {asset.formats.length > 1 && (
        <span className="absolute right-1.5 top-1.5 rounded bg-black/60 px-1.5 py-0.5 text-[10px] font-medium tracking-wide text-white opacity-0 transition-opacity group-hover:opacity-100">
          {asset.formats.join("+")}
        </span>
      )}

      <span className="pointer-events-none absolute inset-x-0 bottom-0 flex items-end justify-between gap-1 bg-gradient-to-t from-black/55 to-transparent px-1.5 pb-1 pt-4 opacity-0 transition-opacity group-hover:opacity-100 data-[pinned=true]:opacity-100"
        data-pinned={
          asset.rating > 0 ||
          asset.is_favorite ||
          asset.media_type === "video" ||
          asset.is_live ||
          asset.is_edited ||
          asset.cull_flag !== "none"
        }
      >
        <span className="flex items-center gap-1">
          {asset.cull_flag === "reject" && (
            <Ban role="img" aria-label={t("cull.flag_reject")} className="size-3 text-red-400" />
          )}
          {asset.cull_flag === "pick" && (
            <Check role="img" aria-label={t("cull.flag_pick")} className="size-3 text-emerald-400" />
          )}
          {asset.is_edited && (
            <SlidersHorizontal
              role="img"
              aria-label={t("develop.edited")}
              className="size-3 text-white"
            />
          )}
          {asset.is_favorite && <Heart className="size-3 fill-white text-white" />}
          {asset.rating > 0 && (
            <span className="flex text-white" aria-label={`${asset.rating}★`}>
              {Array.from({ length: asset.rating }, (_, index) => (
                <Star key={index} className="size-2.5 fill-current" />
              ))}
            </span>
          )}
        </span>
        {asset.media_type === "video" && (
          <span className="flex items-center gap-1 text-[10.5px] font-medium text-white">
            <Play className="size-2.5 fill-current" />
            {asset.duration_ms ? formatDuration(asset.duration_ms) : null}
          </span>
        )}
        {asset.is_live && (
          <span
            role="img"
            aria-label={t("viewer.live")}
            title={t("viewer.livePlay")}
            data-playing={motion === "playing"}
            onMouseEnter={startMotion}
            onMouseLeave={stopMotion}
            className="pointer-events-auto -m-1 flex items-center rounded-full p-1 text-white hover:bg-black/40 data-[playing=true]:bg-black/50"
          >
            <LiveIcon />
          </span>
        )}
      </span>
    </div>
  );
});
