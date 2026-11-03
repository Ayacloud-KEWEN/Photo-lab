import { Camera, RotateCcw, RotateCw, Volume2, VolumeX } from "lucide-react";
import { useEffect, useRef, useState, type MutableRefObject, type ReactNode } from "react";
import { useTranslation } from "react-i18next";

import { ApiError, api, originalUrl } from "@/api/client";
import {
  useConnection,
  useRefreshLibraryLists,
  useSaveVideoEdit,
  useVideoEdit,
} from "@/api/hooks";
import type { AssetDetail, VideoRecipe } from "@/api/types";
import { rememberedExportFolder, rememberExportFolder } from "@/components/library/ExportDialog";
import { Button } from "@/components/ui/button";
import { IconButton } from "@/components/ui/icon-button";
import { pickDirectory } from "@/lib/dialogs";
import { formatClock } from "@/lib/format";

import type { DevelopKeyHandler } from "./DevelopWorkspace";
import { TrimmedVideo } from "./TrimmedVideo";

const SAVE_DELAY_MS = 600;
const MIN_CLIP_MS = 100;
export const DEFAULT_VIDEO_RECIPE: VideoRecipe = {
  version: 1,
  kind: "video",
  trim_start_ms: 0,
  trim_end_ms: null,
  rotate: 0,
  mute: false,
};

/**
 * Trimming, turning and muting a video. Edits are saved shortly after each change and
 * when leaving; the original file is never written.
 */
export function VideoWorkspace({
  detail,
  posterSrc,
  onExit,
  keysRef,
  overlay,
}: {
  detail: AssetDetail;
  posterSrc: string | undefined;
  onExit: () => void;
  keysRef: MutableRefObject<DevelopKeyHandler | null>;
  overlay?: ReactNode;
}) {
  const { t } = useTranslation();
  const conn = useConnection();
  const edit = useVideoEdit(detail.id);
  const saveEdit = useSaveVideoEdit();
  const refreshLists = useRefreshLibraryLists();
  const videoRef = useRef<HTMLVideoElement>(null);

  const [recipe, setRecipe] = useState<VideoRecipe>(DEFAULT_VIDEO_RECIPE);
  const [loaded, setLoaded] = useState(false);
  const [loadedDuration, setLoadedDuration] = useState<number | null>(null);
  const [frameMessage, setFrameMessage] = useState<string | null>(null);
  const recipeRef = useRef(recipe);
  const savedKey = useRef(JSON.stringify(DEFAULT_VIDEO_RECIPE));
  const saveTimer = useRef<number | undefined>(undefined);
  const changed = useRef(false);
  const duration = edit.data?.duration_ms ?? loadedDuration ?? 0;

  useEffect(() => {
    if (!edit.data || loaded) return;
    recipeRef.current = edit.data.recipe;
    savedKey.current = JSON.stringify(edit.data.recipe);
    setRecipe(edit.data.recipe);
    setLoaded(true);
  }, [edit.data, loaded]);

  const save = () => {
    window.clearTimeout(saveTimer.current);
    const current = recipeRef.current;
    const key = JSON.stringify(current);
    if (key === savedKey.current) return Promise.resolve();
    savedKey.current = key;
    changed.current = true;
    return saveEdit(detail.id, current)
      .then(() => undefined)
      .catch((error: unknown) => {
        savedKey.current = "";
        console.warn("saving the video edit failed", error);
      });
  };
  const leave = useRef(() => {});
  leave.current = () => {
    void save().then(() => {
      if (changed.current) void refreshLists();
    });
  };
  useEffect(() => () => leave.current(), []);

  const change = (patch: Partial<VideoRecipe>) => {
    const next = { ...recipeRef.current, ...patch };
    recipeRef.current = next;
    setRecipe(next);
    window.clearTimeout(saveTimer.current);
    saveTimer.current = window.setTimeout(() => void save(), SAVE_DELAY_MS);
  };
  const seek = (ms: number) => {
    if (videoRef.current) videoRef.current.currentTime = ms / 1000;
  };
  const end = recipe.trim_end_ms ?? duration;
  const setStart = (ms: number) => {
    const start = Math.max(0, Math.min(Math.round(ms), end - MIN_CLIP_MS));
    change({ trim_start_ms: start });
    seek(start);
  };
  const setEnd = (ms: number) => {
    const value = Math.max(recipe.trim_start_ms + MIN_CLIP_MS, Math.min(Math.round(ms), duration));
    change({ trim_end_ms: value >= duration ? null : value });
    seek(value);
  };
  const now = () => Math.round((videoRef.current?.currentTime ?? 0) * 1000);
  const rotate = (clockwise: boolean) =>
    change({ rotate: (recipeRef.current.rotate + (clockwise ? 1 : 3)) % 4 });

  const exportFrame = async () => {
    if (!conn) return;
    const time = now();
    let folder = rememberedExportFolder();
    if (!folder) folder = (await pickDirectory(t("export.pickFolder"))) ?? "";
    if (!folder) return;
    try {
      await save();
      const result = await api.exportFrame(conn, detail.id, time, folder);
      rememberExportFolder(folder);
      setFrameMessage(t("video.frameSaved", { path: result.path }));
    } catch (error) {
      setFrameMessage(
        t("video.frameFailed", {
          message: error instanceof ApiError ? error.message : String(error),
        }),
      );
    }
  };

  const handleKey: DevelopKeyHandler = (event) => {
    const key = event.key.toLowerCase();
    if (event.ctrlKey || event.metaKey || event.altKey) return false;
    if (key === "i") setStart(now());
    else if (key === "o") setEnd(now());
    else return false;
    return true;
  };
  useEffect(() => {
    keysRef.current = handleKey;
    return () => {
      keysRef.current = null;
    };
  });

  const unavailable = edit.error instanceof ApiError && edit.error.code === "develop_unavailable";
  const keptMs = Math.max(0, end - recipe.trim_start_ms);

  return (
    <div className="flex min-h-0 flex-1">
      <div className="relative min-w-0 flex-1">
        {conn && (
          <TrimmedVideo
            src={originalUrl(conn, detail.id, detail.rendition_version ?? "")}
            poster={posterSrc}
            recipe={loaded ? recipe : DEFAULT_VIDEO_RECIPE}
            mode="edit"
            videoRef={videoRef}
            onDuration={setLoadedDuration}
          />
        )}
        {overlay}
      </div>

      <aside
        aria-label={t("video.title")}
        className="flex w-80 shrink-0 flex-col border-l border-white/10 bg-panel"
      >
        <div className="flex h-11 shrink-0 items-center gap-2 border-b border-white/10 px-4">
          <span className="text-[13px] font-medium">{t("video.title")}</span>
          <Button size="sm" variant="secondary" className="ml-auto" onClick={onExit}>
            {t("develop.done")}
          </Button>
        </div>
        {unavailable ? (
          <p className="p-4 text-[12.5px] text-muted-foreground">{t("develop.unavailable")}</p>
        ) : !loaded ? (
          <div className="flex-1" />
        ) : (
          <div className="min-h-0 flex-1 space-y-5 overflow-y-auto px-4 py-3 text-[12px]">
            <section aria-label={t("video.trim")} className="space-y-2">
              <h3 className="text-[11px] font-medium uppercase tracking-wider text-subtle-foreground">
                {t("video.trim")}
              </h3>
              <TrimPoint
                label={t("video.start")}
                value={recipe.trim_start_ms}
                max={duration}
                onChange={setStart}
                onUseCurrent={() => setStart(now())}
                useCurrentLabel={t("video.setStart")}
              />
              <TrimPoint
                label={t("video.end")}
                value={end}
                max={duration}
                onChange={setEnd}
                onUseCurrent={() => setEnd(now())}
                useCurrentLabel={t("video.setEnd")}
              />
              <p className="text-muted-foreground">
                {t("video.kept", { length: formatClock(keptMs), total: formatClock(duration) })}
              </p>
            </section>

            <section aria-label={t("video.picture")} className="space-y-1">
              <h3 className="text-[11px] font-medium uppercase tracking-wider text-subtle-foreground">
                {t("video.picture")}
              </h3>
              <div className="flex items-center gap-1">
                <IconButton label={t("develop.rotateLeft")} onClick={() => rotate(false)}>
                  <RotateCcw />
                </IconButton>
                <IconButton label={t("develop.rotateRight")} onClick={() => rotate(true)}>
                  <RotateCw />
                </IconButton>
                <IconButton
                  label={recipe.mute ? t("video.unmute") : t("video.mute")}
                  active={recipe.mute}
                  onClick={() => change({ mute: !recipe.mute })}
                >
                  {recipe.mute ? <VolumeX /> : <Volume2 />}
                </IconButton>
              </div>
            </section>

            <section aria-label={t("video.frame")} className="space-y-2">
              <Button size="sm" variant="outline" onClick={() => void exportFrame()}>
                <Camera /> {t("video.exportFrame")}
              </Button>
              {frameMessage && (
                <p className="break-all text-[11.5px] text-muted-foreground">{frameMessage}</p>
              )}
            </section>
          </div>
        )}
        <div className="flex shrink-0 items-center border-t border-white/10 px-3 py-2">
          <Button
            size="sm"
            variant="ghost"
            className="ml-auto"
            disabled={JSON.stringify(recipe) === JSON.stringify(DEFAULT_VIDEO_RECIPE)}
            onClick={() => change(DEFAULT_VIDEO_RECIPE)}
          >
            {t("develop.reset")}
          </Button>
        </div>
      </aside>
    </div>
  );
}

function TrimPoint({
  label,
  value,
  max,
  onChange,
  onUseCurrent,
  useCurrentLabel,
}: {
  label: string;
  value: number;
  max: number;
  onChange: (ms: number) => void;
  onUseCurrent: () => void;
  useCurrentLabel: string;
}) {
  return (
    <div>
      <div className="flex items-center justify-between">
        <label className="text-muted-foreground">
          {label}
          <input
            type="range"
            aria-label={label}
            min={0}
            max={Math.max(max, 1)}
            step={100}
            value={value}
            onChange={(event) => onChange(Number(event.target.value))}
            className="develop-slider mt-1 block w-48"
          />
        </label>
        <span className="tabular-nums">{formatClock(value)}</span>
      </div>
      <button
        type="button"
        onClick={onUseCurrent}
        className="mt-0.5 text-[11px] text-highlight hover:underline"
      >
        {useCurrentLabel}
      </button>
    </div>
  );
}
