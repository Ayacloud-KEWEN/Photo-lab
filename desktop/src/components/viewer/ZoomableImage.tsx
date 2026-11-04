import {
  forwardRef,
  useEffect,
  useImperativeHandle,
  useLayoutEffect,
  useRef,
  useState,
  type PointerEvent,
} from "react";

import { cn } from "@/lib/utils";

import {
  FIT,
  actualScale,
  clamp,
  fit,
  maxScale,
  wheelFactor,
  zoomAt,
  type Size,
  type View,
} from "./zoom";

export interface ZoomHandle {
  /** Between fitting the window and one photo pixel per screen pixel. */
  toggleActual: () => void;
  reset: () => void;
}

const INDICATOR_MS = 1200;

/**
 * A photo that zooms with the mouse wheel (around the pointer), pans by dragging, and
 * switches between "fit" and 100% on double-click. It shows the preview until zoomed in,
 * then the full-size image (loaded once, on the first zoom).
 */
export const ZoomableImage = forwardRef<
  ZoomHandle,
  {
    previewSrc: string | undefined;
    fullSrc: string;
    /** Long side of the full-size photo, if known (refined once it has loaded). */
    fullLongEdge: number | null;
    label?: string;
    onZoomedChange?: (zoomed: boolean) => void;
  }
>(function ZoomableImage({ previewSrc, fullSrc, fullLongEdge, label = "", onZoomedChange }, ref) {
  const stageRef = useRef<HTMLDivElement>(null);
  const [stage, setStage] = useState<Size | null>(null);
  const [photo, setPhoto] = useState<Size | null>(null);
  const [fullSize, setFullSize] = useState<Size | null>(null);
  const [view, setView] = useState<View>(FIT);
  const [wantFull, setWantFull] = useState(false);
  const [fullLoaded, setFullLoaded] = useState(false);
  const [indicator, setIndicator] = useState(false);
  const [dragging, setDragging] = useState(false);
  const drag = useRef<{ pointer: number; x: number; y: number; view: View } | null>(null);

  useLayoutEffect(() => {
    const element = stageRef.current;
    if (!element) return;
    const observer = new ResizeObserver(([entry]) => {
      if (entry) setStage({ width: entry.contentRect.width, height: entry.contentRect.height });
    });
    observer.observe(element);
    return () => observer.disconnect();
  }, []);

  const fitted = stage && photo ? fit(stage, photo) : null;
  const dpr = window.devicePixelRatio || 1;
  // The full photo's width at the preview's orientation: measured once loaded, else from
  // the long side in the metadata, else the preview's own (zooming is then up to 4x it).
  const fullWidth =
    fullSize?.width ??
    (photo && fullLongEdge
      ? photo.width >= photo.height
        ? fullLongEdge
        : (fullLongEdge * photo.width) / photo.height
      : (photo?.width ?? 1));
  const max = fitted ? maxScale(fitted, fullWidth, dpr) : 1;

  // Latest values for the native wheel listener.
  const latest = useRef({ stage, fitted, max });
  latest.current = { stage, fitted, max };

  const show = (next: View) => {
    setView(next);
    if (next.scale > 1) setWantFull(true);
    setIndicator(true);
  };
  useEffect(() => {
    if (!indicator) return;
    const timer = window.setTimeout(() => setIndicator(false), INDICATOR_MS);
    return () => window.clearTimeout(timer);
  }, [indicator, view]);

  const zoomed = view.scale > 1;
  useEffect(() => onZoomedChange?.(zoomed), [zoomed, onZoomedChange]);

  useEffect(() => {
    const element = stageRef.current;
    if (!element) return;
    const onWheel = (event: WheelEvent) => {
      const { stage: size, fitted: box, max: limit } = latest.current;
      if (!size || !box) return;
      event.preventDefault();
      const rect = element.getBoundingClientRect();
      const point = { x: event.clientX - rect.left, y: event.clientY - rect.top };
      setView((current) => {
        const next = zoomAt(
          current,
          current.scale * wheelFactor(event.deltaY, event.deltaMode),
          point,
          size,
          box,
          limit,
        );
        if (next.scale > 1) setWantFull(true);
        return next;
      });
      setIndicator(true);
    };
    // Not passive: the wheel must not also scroll anything behind the viewer.
    element.addEventListener("wheel", onWheel, { passive: false });
    return () => element.removeEventListener("wheel", onWheel);
  }, []);

  const toggleAt = (point: { x: number; y: number }) => {
    if (!stage || !fitted) return;
    if (zoomed) show(FIT);
    else show(zoomAt(view, actualScale(fitted, fullWidth, dpr), point, stage, fitted, max));
  };
  useImperativeHandle(ref, () => ({
    toggleActual: () => stage && toggleAt({ x: stage.width / 2, y: stage.height / 2 }),
    reset: () => show(FIT),
  }));

  const onPointerDown = (event: PointerEvent<HTMLDivElement>) => {
    if (!zoomed || event.button !== 0) return;
    drag.current = { pointer: event.pointerId, x: event.clientX, y: event.clientY, view };
    event.currentTarget.setPointerCapture?.(event.pointerId);
    setDragging(true);
  };
  const onPointerMove = (event: PointerEvent<HTMLDivElement>) => {
    const start = drag.current;
    if (!start || start.pointer !== event.pointerId || !stage || !fitted) return;
    setView(
      clamp(
        {
          scale: start.view.scale,
          x: start.view.x + event.clientX - start.x,
          y: start.view.y + event.clientY - start.y,
        },
        stage,
        fitted,
      ),
    );
  };
  const endDrag = () => {
    drag.current = null;
    setDragging(false);
  };

  const percent = fitted ? Math.round(((view.scale * fitted.width * dpr) / fullWidth) * 100) : 100;
  const preview = previewSrc && (
    <img
      src={previewSrc}
      alt={label}
      draggable={false}
      onLoad={(event) =>
        setPhoto({
          width: event.currentTarget.naturalWidth,
          height: event.currentTarget.naturalHeight,
        })
      }
      className={cn(
        "select-none",
        fitted ? "block size-full" : "absolute inset-0 m-auto max-h-full max-w-full",
      )}
    />
  );

  return (
    <div
      ref={stageRef}
      data-zoom={view.scale.toFixed(3)}
      onPointerDown={onPointerDown}
      onPointerMove={onPointerMove}
      onPointerUp={endDrag}
      onPointerCancel={endDrag}
      onDoubleClick={(event) => {
        const rect = event.currentTarget.getBoundingClientRect();
        toggleAt({ x: event.clientX - rect.left, y: event.clientY - rect.top });
      }}
      className={cn(
        "absolute inset-2 touch-none overflow-hidden",
        zoomed && (dragging ? "cursor-grabbing" : "cursor-grab"),
      )}
    >
      {fitted ? (
        <div
          className="absolute origin-top-left"
          style={{
            left: fitted.left,
            top: fitted.top,
            width: fitted.width,
            height: fitted.height,
            transform: `translate(${view.x}px, ${view.y}px) scale(${view.scale})`,
          }}
        >
          {preview}
          {wantFull && (
            <img
              src={fullSrc}
              alt=""
              draggable={false}
              onLoad={(event) => {
                const image = event.currentTarget;
                setFullSize({ width: image.naturalWidth, height: image.naturalHeight });
                setFullLoaded(true);
              }}
              className={cn(
                "absolute inset-0 size-full select-none",
                fullLoaded ? "opacity-100" : "opacity-0",
              )}
            />
          )}
        </div>
      ) : (
        preview
      )}
      {indicator && fitted && (
        <span className="pointer-events-none absolute bottom-3 left-3 rounded bg-black/70 px-2 py-0.5 text-[11.5px] tabular-nums text-white">
          {percent}%
        </span>
      )}
    </div>
  );
});
