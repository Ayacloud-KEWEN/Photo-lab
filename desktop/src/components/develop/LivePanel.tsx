import { Loader2, Sparkles, Undo2 } from "lucide-react";
import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";

import { liveStripUrl, motionUrl, type BackendConnection } from "@/api/client";
import { useLiveInfo } from "@/api/hooks";
import type { EditRecipe, LiveEffect, LiveInfo } from "@/api/types";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

const EFFECTS: LiveEffect[] = ["live", "loop", "bounce", "long_exposure"];

/** Index of the frame shown at ``time`` (the last one starting at or before it). */
export function frameIndexAt(info: LiveInfo, time: number): number {
  let index = 0;
  info.frames.forEach((frame, i) => {
    if (frame.time_ms <= time) index = i;
  });
  return index;
}

/** The frame the still was taken at (or the middle of the clip). */
function stillIndex(info: LiveInfo): number {
  if (info.still_ms === null) return Math.floor(info.frames.length / 2);
  let best = 0;
  info.frames.forEach((frame, i) => {
    const current = info.frames[best]!;
    if (Math.abs(frame.time_ms - info.still_ms!) < Math.abs(current.time_ms - info.still_ms!)) {
      best = i;
    }
  });
  return best;
}

function seconds(ms: number, language: string): string {
  return new Intl.NumberFormat(language, { minimumFractionDigits: 2, maximumFractionDigits: 2 })
    .format(ms / 1000);
}

/**
 * The develop panel's Live Photo group: how the clip plays (live, loop, bounce) or a long
 * exposure of it, and which frame is the photo. Dragging over the frames shows them at
 * once (``onScrub``, from the clip); letting go develops the chosen frame.
 */
export function LivePanel({
  conn,
  assetId,
  contentVersion,
  editVersion,
  recipe,
  stillSize,
  onChange,
  onScrub,
}: {
  conn: BackendConnection;
  assetId: number;
  /** Rendition version of the original (the clip and its strip). */
  contentVersion: string;
  /** Rendition version with the saved edit (loop and bounce include the adjustments). */
  editVersion: string;
  recipe: EditRecipe;
  stillSize: { width: number; height: number } | null;
  onChange: (patch: Partial<EditRecipe>) => void;
  onScrub: (timeMs: number | null) => void;
}) {
  const { t, i18n } = useTranslation();
  const live = useLiveInfo(assetId);
  const info = live.data;
  const effect = recipe.live_effect ?? "live";
  const chosen = recipe.live_frame_ms ?? null;
  const [dragging, setDragging] = useState<number | null>(null);

  const index =
    dragging ?? (info ? (chosen === null ? stillIndex(info) : frameIndexAt(info, chosen)) : 0);
  const duration = info
    ? Math.max(info.duration_ms, info.frames[info.frames.length - 1]?.time_ms ?? 0, 1)
    : 1;
  const at = (time: number) => `${Math.min(100, (time / duration) * 100)}%`;

  const scrub = (next: number) => {
    if (!info) return;
    setDragging(next);
    onScrub(info.frames[next]?.time_ms ?? 0);
  };
  const commit = () => {
    if (dragging === null || !info) return;
    const frame = info.frames[dragging];
    setDragging(null);
    if (frame) onChange({ live_frame_ms: frame.time_ms });
    else onScrub(null);
  };

  return (
    <section aria-label={t("develop.groups.live")}>
      <h3 className="mb-1 text-[11px] font-medium uppercase tracking-wider text-subtle-foreground">
        {t("develop.groups.live")}
      </h3>
      <div role="radiogroup" aria-label={t("develop.live.effect")} className="grid grid-cols-4 gap-1">
        {EFFECTS.map((id) => (
          <button
            key={id}
            type="button"
            role="radio"
            aria-checked={effect === id}
            onClick={() => onChange({ live_effect: id })}
            className={cn(
              "truncate rounded bg-white/5 px-1 py-1 text-[11.5px] text-muted-foreground hover:bg-white/10",
              effect === id && "bg-white/15 text-foreground",
            )}
          >
            {t(`develop.live.effects.${id}`)}
          </button>
        ))}
      </div>

      {effect === "long_exposure" ? (
        <p className="mt-2 text-[11.5px] leading-relaxed text-subtle-foreground">
          {t("develop.live.longExposureHint")}
        </p>
      ) : (
        <div className="mt-3 space-y-1.5">
          <div className="flex items-baseline justify-between text-[12px] text-muted-foreground">
            <span>{t("develop.live.frame")}</span>
            {info && (
              <span className="tabular-nums text-foreground">
                {chosen === null && dragging === null
                  ? t("develop.live.still")
                  : t("develop.live.seconds", {
                      value: seconds(info.frames[index]?.time_ms ?? 0, i18n.language),
                    })}
              </span>
            )}
          </div>
          {live.isError ? (
            <p className="text-[11.5px] text-subtle-foreground">{t("develop.live.unavailable")}</p>
          ) : !info ? (
            <div className="flex h-12 items-center justify-center rounded bg-white/5">
              <Loader2 className="size-4 animate-spin text-muted-foreground" />
            </div>
          ) : (
            <>
              <div className="relative h-12 overflow-hidden rounded bg-black">
                <img
                  src={liveStripUrl(conn, assetId, contentVersion)}
                  alt=""
                  draggable={false}
                  className="pointer-events-none size-full select-none object-fill opacity-80"
                />
                {info.still_ms !== null && (
                  <span
                    title={t("develop.live.stillMarker")}
                    className="pointer-events-none absolute inset-y-0 w-px bg-white/60"
                    style={{ left: at(info.still_ms) }}
                  />
                )}
                {info.recommended_ms !== null && (
                  <span
                    title={t("develop.live.sharpest")}
                    className="pointer-events-none absolute bottom-0.5 size-1.5 -translate-x-1/2 rounded-full bg-amber-300"
                    style={{ left: at(info.recommended_ms) }}
                  />
                )}
                <span
                  className={cn(
                    "pointer-events-none absolute inset-y-0 w-1 -translate-x-1/2 rounded-sm border border-white shadow",
                    chosen === null && dragging === null ? "opacity-50" : "bg-highlight/40",
                  )}
                  style={{ left: at(info.frames[index]?.time_ms ?? 0) }}
                />
                <input
                  type="range"
                  aria-label={t("develop.live.frame")}
                  min={0}
                  max={Math.max(0, info.frames.length - 1)}
                  step={1}
                  value={index}
                  onChange={(event) => scrub(Number(event.target.value))}
                  onPointerUp={commit}
                  onKeyUp={commit}
                  onBlur={commit}
                  className="absolute inset-0 size-full cursor-pointer opacity-0"
                />
              </div>
              <div className="flex gap-1">
                <Button
                  size="sm"
                  variant="ghost"
                  disabled={info.recommended_ms === null || info.recommended_ms === chosen}
                  onClick={() => onChange({ live_frame_ms: info.recommended_ms })}
                >
                  <Sparkles /> {t("develop.live.sharpest")}
                </Button>
                <Button
                  size="sm"
                  variant="ghost"
                  className="ml-auto"
                  disabled={chosen === null}
                  onClick={() => onChange({ live_frame_ms: null })}
                >
                  <Undo2 /> {t("develop.live.useStill")}
                </Button>
              </div>
              {chosen !== null && (
                <p className="text-[11px] text-subtle-foreground">
                  {stillSize
                    ? t("develop.live.resolution", {
                        frame: `${info.width}×${info.height}`,
                        still: `${stillSize.width}×${stillSize.height}`,
                      })
                    : t("develop.live.resolutionFrame", { frame: `${info.width}×${info.height}` })}
                </p>
              )}
            </>
          )}
        </div>
      )}

      {(effect === "loop" || effect === "bounce") && (
        <MotionPreview src={motionUrl(conn, assetId, editVersion, effect)} />
      )}
    </section>
  );
}

/** The loop / bounce as it will play (rendered on the backend with the adjustments). */
function MotionPreview({ src }: { src: string }) {
  const { t } = useTranslation();
  const [ready, setReady] = useState(false);
  const [failed, setFailed] = useState(false);
  useEffect(() => {
    setReady(false);
    setFailed(false);
  }, [src]);
  return (
    <div className="relative mt-3 min-h-20 overflow-hidden rounded bg-black">
      <video
        key={src}
        src={src}
        aria-label={t("develop.live.motionPreview")}
        autoPlay
        loop
        muted
        playsInline
        onLoadedData={() => setReady(true)}
        onError={() => setFailed(true)}
        className={cn("block max-h-48 w-full object-contain", !ready && "invisible")}
      />
      {!ready && (
        <div className="absolute inset-0 flex min-h-20 items-center justify-center gap-2 text-[11.5px] text-muted-foreground">
          {failed ? (
            t("develop.live.motionFailed")
          ) : (
            <>
              <Loader2 className="size-3.5 animate-spin" /> {t("develop.live.rendering")}
            </>
          )}
        </div>
      )}
    </div>
  );
}
