import { Pause, Play, VolumeX } from "lucide-react";
import {
  useEffect,
  useLayoutEffect,
  useRef,
  useState,
  type CSSProperties,
  type ReactNode,
  type RefObject,
} from "react";
import { useTranslation } from "react-i18next";

import type { VideoRecipe } from "@/api/types";
import { formatClock } from "@/lib/format";
import { cn } from "@/lib/utils";

/**
 * A video played as edited: only the kept part, turned, and silent if muted. Native
 * controls would turn with the picture, so it has its own: play/pause and a scrubber
 * over the kept part ("view"), or over the whole video with the kept part marked ("edit").
 */
export function TrimmedVideo({
  src,
  poster,
  recipe,
  mode = "view",
  videoRef,
  autoPlay = false,
  onError,
  onDuration,
}: {
  src: string;
  poster?: string | undefined;
  recipe: VideoRecipe;
  mode?: "view" | "edit";
  videoRef?: RefObject<HTMLVideoElement | null>;
  autoPlay?: boolean;
  onError?: () => void;
  onDuration?: (ms: number) => void;
}) {
  const { t } = useTranslation();
  const ownRef = useRef<HTMLVideoElement>(null);
  const ref = videoRef ?? ownRef;
  const [current, setCurrent] = useState(recipe.trim_start_ms / 1000);
  const [duration, setDuration] = useState(0);
  const [playing, setPlaying] = useState(false);

  const start = recipe.trim_start_ms / 1000;
  const end = recipe.trim_end_ms == null ? duration : recipe.trim_end_ms / 1000;
  const low = mode === "view" ? start : 0;
  const high = mode === "view" ? end : duration;

  // Keep playback inside the kept part.
  const inside = (video: HTMLVideoElement) =>
    video.currentTime >= start - 0.05 && (end === 0 || video.currentTime < end - 0.05);
  const onPlay = () => {
    const video = ref.current;
    if (video && !inside(video)) video.currentTime = start;
    setPlaying(true);
  };
  const onTimeUpdate = () => {
    const video = ref.current;
    if (!video) return;
    if (end > 0 && video.currentTime >= end && !video.paused) {
      video.pause();
      video.currentTime = end;
    }
    setCurrent(video.currentTime);
  };
  useEffect(() => {
    // A changed trim (while editing) shows its new start.
    const video = ref.current;
    if (video && video.readyState > 0 && mode === "view") video.currentTime = start;
  }, [start, mode, ref]);

  const toggle = () => {
    const video = ref.current;
    if (!video) return;
    if (video.paused) void video.play()?.catch(() => undefined);
    else video.pause();
  };
  const range = high - low;
  const percent = (seconds: number) => `${range > 0 ? ((seconds - low) / range) * 100 : 0}%`;
  const track =
    mode === "edit" && duration > 0
      ? `linear-gradient(to right, var(--border) ${percent(start)}, var(--highlight) ${percent(start)}, var(--highlight) ${percent(end)}, var(--border) ${percent(end)})`
      : undefined;

  return (
    <div className="flex size-full flex-col">
      <RotatedBox turns={recipe.rotate}>
        <video
          ref={ref}
          src={src}
          poster={poster}
          muted={recipe.mute}
          autoPlay={autoPlay}
          playsInline
          preload="metadata"
          onClick={toggle}
          onLoadedMetadata={(event) => {
            const video = event.currentTarget;
            setDuration(video.duration);
            onDuration?.(Math.round(video.duration * 1000));
            if (start > 0) video.currentTime = start;
          }}
          onPlay={onPlay}
          onPause={() => setPlaying(false)}
          onTimeUpdate={onTimeUpdate}
          onError={onError}
          className="size-full bg-black object-contain"
        />
      </RotatedBox>
      <div className="flex h-10 shrink-0 items-center gap-3 px-3 text-[11.5px] text-muted-foreground">
        <button
          type="button"
          aria-label={playing ? t("video.pause") : t("video.play")}
          onClick={toggle}
          className="rounded p-1 text-foreground hover:bg-white/10"
        >
          {playing ? <Pause className="size-4" /> : <Play className="size-4" />}
        </button>
        <span className="w-28 shrink-0 tabular-nums">
          {formatClock((current - low) * 1000)} / {formatClock(range * 1000)}
        </span>
        <input
          type="range"
          aria-label={t("video.position")}
          min={low}
          max={Math.max(low, high)}
          step={0.01}
          value={Math.min(Math.max(current, low), Math.max(low, high))}
          onChange={(event) => {
            const video = ref.current;
            if (video) video.currentTime = Number(event.target.value);
            setCurrent(Number(event.target.value));
          }}
          className="develop-slider min-w-0 flex-1"
          style={track ? ({ "--track": track } as CSSProperties) : undefined}
        />
        {recipe.mute && <VolumeX aria-label={t("video.muted")} className="size-4 shrink-0" />}
      </div>
    </div>
  );
}

/** Children turned by quarter turns, fitted to this box (a turned video swaps its sides). */
function RotatedBox({ turns, children }: { turns: number; children: ReactNode }) {
  const boxRef = useRef<HTMLDivElement>(null);
  const [size, setSize] = useState({ width: 0, height: 0 });
  useLayoutEffect(() => {
    const element = boxRef.current;
    if (!element) return;
    const observer = new ResizeObserver(([entry]) => {
      if (entry) setSize({ width: entry.contentRect.width, height: entry.contentRect.height });
    });
    observer.observe(element);
    return () => observer.disconnect();
  }, []);
  const sideways = turns % 2 === 1;
  return (
    <div ref={boxRef} className="relative min-h-0 flex-1 overflow-hidden">
      <div
        className={cn("absolute left-1/2 top-1/2", !sideways && "size-full")}
        style={{
          ...(sideways ? { width: size.height, height: size.width } : {}),
          transform: `translate(-50%, -50%) rotate(${turns * 90}deg)`,
        }}
      >
        {children}
      </div>
    </div>
  );
}
