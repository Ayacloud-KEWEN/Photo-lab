import { useVirtualizer } from "@tanstack/react-virtual";
import { Play } from "lucide-react";
import { useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";

import { thumbnailUrl } from "@/api/client";
import { useConnection } from "@/api/hooks";
import type { AssetSummary } from "@/api/types";
import { formatDuration } from "@/lib/format";
import { cn } from "@/lib/utils";

const MIN_TILE = 168;
const GAP = 4;
const PADDING = 24;

interface MediaGridProps {
  assets: AssetSummary[];
  selectedId: number | null;
  onSelect: (id: number) => void;
  /** Called when the last rows come into view (load the next page). */
  onReachEnd: () => void;
}

/** Virtualized grid of square thumbnails; renders only the rows in view. */
export function MediaGrid({ assets, selectedId, onSelect, onReachEnd }: MediaGridProps) {
  const scrollRef = useRef<HTMLDivElement>(null);
  const [width, setWidth] = useState(0);

  useLayoutEffect(() => {
    const element = scrollRef.current;
    if (!element) return;
    setWidth(element.clientWidth);
    // clientWidth includes the padding (subtracted below) and excludes the scrollbar.
    const observer = new ResizeObserver(() => setWidth(element.clientWidth));
    observer.observe(element);
    return () => observer.disconnect();
  }, []);

  const inner = Math.max(0, width - PADDING * 2);
  const columns = Math.max(1, Math.floor((inner + GAP) / (MIN_TILE + GAP)));
  const tile = columns > 0 ? (inner - GAP * (columns - 1)) / columns : MIN_TILE;
  const rowCount = Math.ceil(assets.length / columns);

  const virtualizer = useVirtualizer({
    count: rowCount,
    getScrollElement: () => scrollRef.current,
    estimateSize: () => tile + GAP,
    overscan: 4,
  });

  useEffect(() => {
    virtualizer.measure();
  }, [tile, virtualizer]);

  const rows = virtualizer.getVirtualItems();
  const lastRow = rows.at(-1)?.index ?? -1;
  useEffect(() => {
    if (rowCount > 0 && lastRow >= rowCount - 3) onReachEnd();
  }, [lastRow, rowCount, onReachEnd]);

  return (
    <div ref={scrollRef} className="h-full overflow-y-auto" style={{ padding: `0 ${PADDING}px` }}>
      <div className="relative w-full" style={{ height: virtualizer.getTotalSize() + PADDING }}>
        {rows.map((row) => (
          <div
            key={row.key}
            className="absolute left-0 top-0 flex w-full"
            style={{ transform: `translateY(${row.start}px)`, gap: GAP, height: tile }}
          >
            {assets.slice(row.index * columns, row.index * columns + columns).map((asset) => (
              <Tile
                key={asset.id}
                asset={asset}
                size={tile}
                selected={asset.id === selectedId}
                onSelect={onSelect}
              />
            ))}
          </div>
        ))}
      </div>
    </div>
  );
}

function Tile({
  asset,
  size,
  selected,
  onSelect,
}: {
  asset: AssetSummary;
  size: number;
  selected: boolean;
  onSelect: (id: number) => void;
}) {
  const conn = useConnection();
  const src = useMemo(
    () => (conn ? thumbnailUrl(conn, asset.id, asset.rendition_version) : undefined),
    [conn, asset.id, asset.rendition_version],
  );
  const [failed, setFailed] = useState(false);
  const paired = asset.formats.length > 1;

  return (
    <button
      type="button"
      onClick={() => onSelect(asset.id)}
      aria-pressed={selected}
      title={asset.file_name}
      className={cn(
        "group relative shrink-0 overflow-hidden rounded-[3px] bg-card outline-none",
        selected
          ? "ring-2 ring-highlight ring-offset-2 ring-offset-background"
          : "focus-visible:ring-2 focus-visible:ring-ring",
      )}
      style={{ width: size, height: size }}
    >
      {src && !failed ? (
        <img
          src={src}
          alt={asset.file_name}
          loading="lazy"
          decoding="async"
          draggable={false}
          onError={() => setFailed(true)}
          className="size-full object-cover transition-opacity group-hover:opacity-90"
        />
      ) : (
        <span className="flex size-full items-center justify-center p-2 text-[11px] text-subtle-foreground">
          {asset.file_name}
        </span>
      )}
      {asset.media_type === "video" && (
        <span className="absolute bottom-1.5 right-1.5 flex items-center gap-1 rounded bg-black/60 px-1.5 py-0.5 text-[10.5px] font-medium text-white">
          <Play className="size-2.5 fill-current" />
          {asset.duration_ms ? formatDuration(asset.duration_ms) : null}
        </span>
      )}
      {paired && (
        <span className="absolute left-1.5 top-1.5 rounded bg-black/60 px-1.5 py-0.5 text-[10px] font-medium tracking-wide text-white opacity-0 transition-opacity group-hover:opacity-100">
          {asset.formats.join("+")}
        </span>
      )}
    </button>
  );
}
