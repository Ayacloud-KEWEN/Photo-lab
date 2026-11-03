import {
  Check,
  Crop as CropIcon,
  Eye,
  FlipHorizontal2,
  Redo2,
  RotateCcw,
  RotateCw,
  Undo2,
  X,
} from "lucide-react";
import {
  useEffect,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
  type KeyboardEvent,
  type MutableRefObject,
  type ReactNode,
} from "react";
import { useTranslation } from "react-i18next";

import { ApiError } from "@/api/client";
import {
  useConnection,
  useEditActions,
  useEditState,
  useRefreshLibraryLists,
} from "@/api/hooks";
import type { Crop, EditRecipe, EditState, EditStep } from "@/api/types";
import { Button } from "@/components/ui/button";
import { IconButton } from "@/components/ui/icon-button";
import { formatDateTime } from "@/lib/format";
import { cn } from "@/lib/utils";

import { CropOverlay } from "./CropOverlay";
import { Histogram } from "./Histogram";
import {
  ASPECTS,
  DEFAULT_RECIPE,
  FULL_FRAME,
  SLIDER_GROUPS,
  STRAIGHTEN,
  aspectRatio,
  clampCrop,
  fitAspect,
  flipCrop,
  isFullFrame,
  normalizeRecipe,
  recipeKey,
  rotateCrop,
  type AspectId,
  type RecipeField,
} from "./recipe";
import { Slider } from "./Slider";
import { useDevelopPreview } from "./useDevelopPreview";

/** Saves happen this long after the last change (and right after a slider is let go). */
const SAVE_DELAY_MS = 600;
const COMMIT_DELAY_MS = 150;

export type DevelopKeyHandler = (event: KeyboardEvent<HTMLElement>) => boolean;

/**
 * The develop module for one photo: the live preview (with the crop tool) and the
 * adjustment panel. Edits are saved as history steps shortly after each change and
 * when leaving; the original file is never written.
 */
export function DevelopWorkspace({
  assetId,
  placeholderSrc,
  onExit,
  keysRef,
  overlay,
}: {
  assetId: number;
  /** Shown until the first render arrives (the current preview rendition). */
  placeholderSrc: string | undefined;
  onExit: () => void;
  /** Receives this workspace's keyboard handler (it returns true for handled keys). */
  keysRef: MutableRefObject<DevelopKeyHandler | null>;
  /** Drawn over the photo (e.g. previous / next buttons). */
  overlay?: ReactNode;
}) {
  const { t, i18n } = useTranslation();
  const conn = useConnection();
  const editState = useEditState(assetId);
  const actions = useEditActions();
  const refreshLists = useRefreshLibraryLists();
  const state = editState.data;

  const [recipe, setRecipe] = useState<EditRecipe>(DEFAULT_RECIPE);
  const [loaded, setLoaded] = useState(false);
  const recipeRef = useRef(recipe);
  const savedKey = useRef(recipeKey(DEFAULT_RECIPE));
  const saveTimer = useRef<number | undefined>(undefined);
  const changed = useRef(false);

  const [before, setBefore] = useState(false);
  const [cropping, setCropping] = useState(false);
  const [draft, setDraft] = useState<Crop>(FULL_FRAME);
  const [aspect, setAspect] = useState<AspectId>("free");
  const [natural, setNatural] = useState<{ width: number; height: number } | null>(null);

  // Adopt the saved recipe once it has loaded.
  useEffect(() => {
    if (!state || loaded) return;
    const saved = normalizeRecipe(state.recipe);
    recipeRef.current = saved;
    savedKey.current = recipeKey(saved);
    setRecipe(saved);
    setLoaded(true);
  }, [state, loaded]);

  const save = () => {
    window.clearTimeout(saveTimer.current);
    const current = recipeRef.current;
    const key = recipeKey(current);
    if (key === savedKey.current) return Promise.resolve();
    savedKey.current = key;
    changed.current = true;
    return actions
      .save(assetId, current)
      .then(() => undefined)
      .catch((error: unknown) => {
        savedKey.current = ""; // try again with the next change
        console.warn("saving the edit failed", error);
      });
  };
  const saveLater = (delay = SAVE_DELAY_MS) => {
    window.clearTimeout(saveTimer.current);
    saveTimer.current = window.setTimeout(() => void save(), delay);
  };

  // Leaving (done, or another photo): save what is pending, then refresh thumbnails.
  const leave = useRef(() => {});
  leave.current = () => {
    void save().then(() => {
      if (changed.current) void refreshLists();
    });
  };
  useEffect(() => () => leave.current(), []);

  const change = (patch: Partial<EditRecipe>, delay = SAVE_DELAY_MS) => {
    const next = { ...recipeRef.current, ...patch };
    recipeRef.current = next;
    setRecipe(next);
    saveLater(delay);
  };

  /** Show a state the server put in effect (undo, redo, history). */
  const adopt = (next: EditState) => {
    const adopted = normalizeRecipe(next.recipe);
    window.clearTimeout(saveTimer.current);
    recipeRef.current = adopted;
    savedKey.current = recipeKey(adopted);
    changed.current = true;
    setRecipe(adopted);
    setCropping(false);
  };
  const dirty = () => recipeKey(recipeRef.current) !== savedKey.current;
  const undo = () => {
    // Unsaved changes are undone first, back to the last saved step.
    if (dirty() && state) adopt(state);
    else if (state?.can_undo) void actions.undo(assetId).then(adopt);
  };
  const redo = () => {
    if (!dirty() && state?.can_redo) void actions.redo(assetId).then(adopt);
  };
  const selectStep = (editId: number | null) =>
    void save().then(() => actions.select(assetId, editId).then(adopt));
  const resetAll = () => {
    change(DEFAULT_RECIPE, COMMIT_DELAY_MS);
    setCropping(false);
  };

  // --- Geometry ---------------------------------------------------------------------------
  const rotate = (clockwise: boolean) => {
    const current = recipeRef.current;
    // Rotation happens before the flip, so a flipped photo turns the other way.
    const turn = clockwise !== current.flip_horizontal ? 1 : 3;
    change({ rotate: (current.rotate + turn) % 4, crop: rotateCrop(current.crop, clockwise) });
    if (cropping) setDraft((crop) => rotateCrop(crop, clockwise) ?? FULL_FRAME);
  };
  const flip = () => {
    const current = recipeRef.current;
    change({
      flip_horizontal: !current.flip_horizontal,
      straighten: -current.straighten,
      crop: flipCrop(current.crop),
    });
    if (cropping) setDraft((crop) => flipCrop(crop) ?? FULL_FRAME);
  };
  const startCrop = () => {
    setDraft(recipeRef.current.crop ?? FULL_FRAME);
    setBefore(false);
    setCropping(true);
  };
  const applyCrop = () => {
    change({ crop: isFullFrame(draft) ? null : draft }, COMMIT_DELAY_MS);
    setCropping(false);
  };
  const ratio =
    cropping && natural ? aspectRatio(aspect, natural.width, natural.height) : null;
  const chooseAspect = (next: AspectId) => {
    setAspect(next);
    const pixels = natural ? aspectRatio(next, natural.width, natural.height) : null;
    if (!natural || pixels === null) return;
    const fitted = fitAspect(FULL_FRAME, pixels, natural.width, natural.height);
    const centreX = draft.x + draft.width / 2;
    const centreY = draft.y + draft.height / 2;
    setDraft(
      clampCrop({
        ...fitted,
        x: centreX - fitted.width / 2,
        y: centreY - fitted.height / 2,
      }),
    );
  };

  // --- Keyboard ---------------------------------------------------------------------------
  const handleKey: DevelopKeyHandler = (event) => {
    const key = event.key;
    const ctrl = event.ctrlKey || event.metaKey;
    if (ctrl && key.toLowerCase() === "z") {
      if (event.shiftKey) redo();
      else undo();
    } else if (ctrl && key.toLowerCase() === "y") redo();
    else if (key === "\\") setBefore((value) => !value);
    else if (key.toLowerCase() === "c" && !ctrl) {
      if (cropping) applyCrop();
      else startCrop();
    } else if (key === "Enter" && cropping) applyCrop();
    else if (key === "Escape" && cropping) setCropping(false);
    else return false;
    return true;
  };
  // Registered after every render (handlers close over the latest state).
  useEffect(() => {
    keysRef.current = handleKey;
    return () => {
      keysRef.current = null;
    };
  });

  // --- Preview ----------------------------------------------------------------------------
  const edge = useMemo(
    () =>
      Math.min(
        2048,
        Math.max(
          1024,
          Math.round(
            Math.max(window.innerWidth, window.innerHeight) * (window.devicePixelRatio || 1) * 0.8,
          ),
        ),
      ),
    [],
  );
  const shown = before
    ? DEFAULT_RECIPE
    : cropping
      ? { ...recipe, crop: null }
      : recipe;
  const preview = useDevelopPreview(conn, assetId, loaded ? shown : DEFAULT_RECIPE, edge);
  const unavailable =
    editState.error instanceof ApiError && editState.error.code === "develop_unavailable";

  return (
    <div className="flex min-h-0 flex-1">
      <div className="relative min-w-0 flex-1">
        <FittedImage
          src={preview.src ?? placeholderSrc}
          onNaturalSize={setNatural}
          label={before ? t("develop.beforeLabel") : t("develop.title")}
        >
          {cropping && natural && (
            <CropOverlay
              crop={draft}
              ratio={ratio === null ? null : (ratio * natural.height) / natural.width}
              onChange={setDraft}
            />
          )}
        </FittedImage>
        {before && (
          <span className="absolute left-4 top-4 rounded bg-black/60 px-2 py-0.5 text-[11px] text-white">
            {t("develop.beforeLabel")}
          </span>
        )}
        {preview.failed && (
          <span className="absolute bottom-4 left-1/2 -translate-x-1/2 rounded bg-black/70 px-3 py-1 text-[12px] text-white">
            {t("develop.failed")}
          </span>
        )}
        {overlay}
      </div>

      <aside
        aria-label={t("develop.title")}
        className="flex w-80 shrink-0 flex-col border-l border-white/10 bg-panel"
      >
        <div className="flex h-11 shrink-0 items-center gap-2 border-b border-white/10 px-4">
          <span className="text-[13px] font-medium">{t("develop.title")}</span>
          {state && (
            <span className="rounded bg-white/10 px-1.5 py-px text-[10.5px] tracking-wide text-muted-foreground">
              {state.is_raw ? `RAW · ${state.source_format}` : state.source_format}
            </span>
          )}
          <Button size="sm" variant="secondary" className="ml-auto" onClick={onExit}>
            {t("develop.done")}
          </Button>
        </div>

        {unavailable ? (
          <p className="p-4 text-[12.5px] text-muted-foreground">{t("develop.unavailable")}</p>
        ) : !loaded ? (
          <div className="flex-1" />
        ) : (
          <div className="min-h-0 flex-1 space-y-4 overflow-y-auto px-4 py-3">
            <Histogram data={preview.histogram} />

            <section aria-label={t("develop.groups.geometry")}>
              <GroupTitle>{t("develop.groups.geometry")}</GroupTitle>
              <div className="flex items-center gap-1">
                <IconButton label={t("develop.rotateLeft")} onClick={() => rotate(false)}>
                  <RotateCcw />
                </IconButton>
                <IconButton label={t("develop.rotateRight")} onClick={() => rotate(true)}>
                  <RotateCw />
                </IconButton>
                <IconButton
                  label={t("develop.flip")}
                  active={recipe.flip_horizontal}
                  onClick={flip}
                >
                  <FlipHorizontal2 />
                </IconButton>
                <IconButton
                  label={t("develop.crop")}
                  active={cropping || !!recipe.crop}
                  onClick={cropping ? applyCrop : startCrop}
                >
                  <CropIcon />
                </IconButton>
              </div>
              {cropping && (
                <div className="mt-2 space-y-2 rounded-md bg-white/5 p-2">
                  <div
                    role="radiogroup"
                    aria-label={t("develop.aspect")}
                    className="flex flex-wrap gap-1"
                  >
                    {ASPECTS.map((id) => (
                      <button
                        key={id}
                        type="button"
                        role="radio"
                        aria-checked={aspect === id}
                        onClick={() => chooseAspect(id)}
                        className={cn(
                          "rounded px-2 py-0.5 text-[11.5px] text-muted-foreground hover:bg-white/10",
                          aspect === id && "bg-white/15 text-foreground",
                        )}
                      >
                        {id === "free" || id === "original" ? t(`develop.aspects.${id}`) : id}
                      </button>
                    ))}
                  </div>
                  <div className="flex gap-1">
                    <Button size="sm" onClick={applyCrop}>
                      <Check /> {t("develop.cropApply")}
                    </Button>
                    <Button size="sm" variant="ghost" onClick={() => setCropping(false)}>
                      <X /> {t("develop.cropCancel")}
                    </Button>
                    <Button
                      size="sm"
                      variant="ghost"
                      className="ml-auto"
                      onClick={() => setDraft(FULL_FRAME)}
                    >
                      {t("develop.cropReset")}
                    </Button>
                  </div>
                </div>
              )}
              <Slider
                spec={STRAIGHTEN}
                value={recipe.straighten}
                onChange={(value) => change({ straighten: value })}
                onCommit={() => saveLater(COMMIT_DELAY_MS)}
              />
            </section>

            {SLIDER_GROUPS.map((group) => (
              <section key={group.id} aria-label={t(`develop.groups.${group.id}`)}>
                <GroupTitle>{t(`develop.groups.${group.id}`)}</GroupTitle>
                {group.sliders.map((spec) => (
                  <Slider
                    key={spec.key}
                    spec={spec}
                    value={recipe[spec.key]}
                    onChange={(value) => change({ [spec.key]: value } as Partial<EditRecipe>)}
                    onCommit={() => saveLater(COMMIT_DELAY_MS)}
                  />
                ))}
              </section>
            ))}

            {state && (
              <History
                state={state}
                language={i18n.language}
                onSelect={selectStep}
              />
            )}
          </div>
        )}

        <div className="flex shrink-0 items-center gap-1 border-t border-white/10 px-3 py-2">
          <IconButton label={t("develop.undo")} onClick={undo} disabled={!state?.can_undo && !dirty()}>
            <Undo2 />
          </IconButton>
          <IconButton label={t("develop.redo")} onClick={redo} disabled={!state?.can_redo}>
            <Redo2 />
          </IconButton>
          <IconButton label={t("develop.before")} active={before} onClick={() => setBefore((v) => !v)}>
            <Eye />
          </IconButton>
          <Button
            size="sm"
            variant="ghost"
            className="ml-auto"
            disabled={recipeKey(recipe) === recipeKey(DEFAULT_RECIPE)}
            onClick={resetAll}
          >
            {t("develop.reset")}
          </Button>
        </div>
      </aside>
    </div>
  );
}

function GroupTitle({ children }: { children: ReactNode }) {
  return (
    <h3 className="mb-1 text-[11px] font-medium uppercase tracking-wider text-subtle-foreground">
      {children}
    </h3>
  );
}

/** Saved steps, newest first, with the original at the bottom. Clicking one returns to it. */
function History({
  state,
  language,
  onSelect,
}: {
  state: EditState;
  language: string;
  onSelect: (editId: number | null) => void;
}) {
  const { t } = useTranslation();
  const list = useMemo(() => new Intl.ListFormat(language), [language]);
  const describe = (step: EditStep) =>
    step.changes.length === 0
      ? t("develop.resetStep")
      : list.format(step.changes.map((field) => t(`develop.fields.${field as RecipeField}`)));
  const rows: { id: number | null; label: string; time?: string }[] = [
    ...[...state.steps]
      .reverse()
      .map((step) => ({ id: step.id, label: describe(step), time: step.created_at })),
    { id: null, label: t("develop.original") },
  ];

  return (
    <section aria-label={t("develop.history")}>
      <GroupTitle>{t("develop.history")}</GroupTitle>
      <ol className="space-y-px">
        {rows.map((row) => {
          const current = row.id === state.current_edit_id;
          return (
            <li key={row.id ?? "original"}>
              <button
                type="button"
                aria-current={current ? "step" : undefined}
                onClick={() => onSelect(row.id)}
                className={cn(
                  "flex w-full items-baseline gap-2 rounded px-2 py-1 text-left text-[12px] text-muted-foreground hover:bg-white/5",
                  current && "bg-white/10 text-foreground",
                )}
              >
                <span className="min-w-0 flex-1 truncate">{row.label}</span>
                {row.time && (
                  <span className="shrink-0 text-[10.5px] text-subtle-foreground">
                    {formatDateTime(row.time, language)}
                  </span>
                )}
              </button>
            </li>
          );
        })}
      </ol>
    </section>
  );
}

/** The image fitted into the stage; children are laid exactly over it. */
function FittedImage({
  src,
  label,
  onNaturalSize,
  children,
}: {
  src: string | undefined;
  label: string;
  onNaturalSize: (size: { width: number; height: number }) => void;
  children?: ReactNode;
}) {
  const stageRef = useRef<HTMLDivElement>(null);
  const [stage, setStage] = useState<{ width: number; height: number } | null>(null);
  const [natural, setNatural] = useState<{ width: number; height: number } | null>(null);

  useLayoutEffect(() => {
    const element = stageRef.current;
    if (!element) return;
    const observer = new ResizeObserver(([entry]) => {
      if (entry) setStage({ width: entry.contentRect.width, height: entry.contentRect.height });
    });
    observer.observe(element);
    return () => observer.disconnect();
  }, []);

  let box: { width: number; height: number } | null = null;
  if (stage && natural) {
    const scale = Math.min(stage.width / natural.width, stage.height / natural.height, 1.5);
    box = { width: natural.width * scale, height: natural.height * scale };
  }

  const image = src && (
    <img
      src={src}
      alt={label}
      draggable={false}
      onLoad={(event) => {
        const loaded = event.currentTarget;
        const size = { width: loaded.naturalWidth, height: loaded.naturalHeight };
        setNatural(size);
        onNaturalSize(size);
      }}
      className={cn(
        "select-none",
        box ? "block size-full object-contain" : "absolute inset-0 m-auto max-h-full max-w-full",
      )}
    />
  );
  return (
    <div ref={stageRef} className="absolute inset-3">
      {box ? (
        <div className="absolute inset-0 m-auto" style={box}>
          {image}
          {children}
        </div>
      ) : (
        image
      )}
    </div>
  );
}
