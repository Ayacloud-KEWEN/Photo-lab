import { useRef, type PointerEvent } from "react";
import { useTranslation } from "react-i18next";

import type { Crop } from "@/api/types";
import { cn } from "@/lib/utils";

import { resizeCrop, type CropHandle } from "./recipe";

const HANDLES: { handle: Exclude<CropHandle, "move">; className: string }[] = [
  { handle: "nw", className: "-left-1.5 -top-1.5 cursor-nwse-resize" },
  { handle: "ne", className: "-right-1.5 -top-1.5 cursor-nesw-resize" },
  { handle: "sw", className: "-bottom-1.5 -left-1.5 cursor-nesw-resize" },
  { handle: "se", className: "-bottom-1.5 -right-1.5 cursor-nwse-resize" },
  { handle: "n", className: "-top-1 left-1/2 -translate-x-1/2 cursor-ns-resize" },
  { handle: "s", className: "-bottom-1 left-1/2 -translate-x-1/2 cursor-ns-resize" },
  { handle: "w", className: "-left-1 top-1/2 -translate-y-1/2 cursor-ew-resize" },
  { handle: "e", className: "-right-1 top-1/2 -translate-y-1/2 cursor-ew-resize" },
];

/**
 * The crop rectangle over the uncropped photo: drag inside to move it, drag the
 * handles to resize. Must be placed exactly over the image (``absolute inset-0``).
 */
export function CropOverlay({
  crop,
  ratio,
  onChange,
}: {
  crop: Crop;
  /** Width / height in frame fractions, or null for free cropping. */
  ratio: number | null;
  onChange: (crop: Crop) => void;
}) {
  const { t } = useTranslation();
  const frameRef = useRef<HTMLDivElement>(null);
  const drag = useRef<{
    handle: CropHandle;
    x: number;
    y: number;
    width: number;
    height: number;
    start: Crop;
  } | null>(null);

  const begin = (handle: CropHandle) => (event: PointerEvent) => {
    const frame = frameRef.current?.getBoundingClientRect();
    if (!frame || event.button !== 0) return;
    event.preventDefault();
    event.stopPropagation();
    drag.current = {
      handle,
      x: event.clientX,
      y: event.clientY,
      width: frame.width,
      height: frame.height,
      start: crop,
    };
    frameRef.current?.setPointerCapture?.(event.pointerId);
  };
  const move = (event: PointerEvent) => {
    const current = drag.current;
    if (!current || current.width === 0 || current.height === 0) return;
    const dx = (event.clientX - current.x) / current.width;
    const dy = (event.clientY - current.y) / current.height;
    onChange(resizeCrop(current.start, current.handle, dx, dy, ratio));
  };
  const end = () => {
    drag.current = null;
  };

  const percent = (value: number) => `${value * 100}%`;
  return (
    <div
      ref={frameRef}
      className="absolute inset-0 touch-none overflow-hidden"
      onPointerMove={move}
      onPointerUp={end}
      onPointerCancel={end}
    >
      <div
        role="group"
        aria-label={t("develop.cropBox")}
        onPointerDown={begin("move")}
        className="absolute cursor-move border border-white/90 shadow-[0_0_0_9999px_rgba(0,0,0,0.55)]"
        style={{
          left: percent(crop.x),
          top: percent(crop.y),
          width: percent(crop.width),
          height: percent(crop.height),
        }}
      >
        {/* Rule-of-thirds guides */}
        <span className="pointer-events-none absolute inset-y-0 left-1/3 w-px bg-white/30" />
        <span className="pointer-events-none absolute inset-y-0 left-2/3 w-px bg-white/30" />
        <span className="pointer-events-none absolute inset-x-0 top-1/3 h-px bg-white/30" />
        <span className="pointer-events-none absolute inset-x-0 top-2/3 h-px bg-white/30" />
        {HANDLES.map(({ handle, className }) => (
          <span
            key={handle}
            data-handle={handle}
            onPointerDown={begin(handle)}
            className={cn(
              "absolute bg-white shadow",
              handle.length === 2 ? "size-3" : handle === "n" || handle === "s" ? "h-2 w-6" : "h-6 w-2",
              className,
            )}
          />
        ))}
      </div>
    </div>
  );
}
