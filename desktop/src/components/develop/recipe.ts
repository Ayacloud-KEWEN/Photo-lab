import type { Crop, EditRecipe } from "@/api/types";

export const DEFAULT_RECIPE: EditRecipe = {
  version: 1,
  exposure: 0,
  contrast: 0,
  highlights: 0,
  shadows: 0,
  whites: 0,
  blacks: 0,
  temperature: 0,
  tint: 0,
  vibrance: 0,
  saturation: 0,
  clarity: 0,
  sharpness: 0,
  vignette: 0,
  rotate: 0,
  flip_horizontal: false,
  straighten: 0,
  crop: null,
};

export type SliderKey =
  | "exposure"
  | "contrast"
  | "highlights"
  | "shadows"
  | "whites"
  | "blacks"
  | "temperature"
  | "tint"
  | "vibrance"
  | "saturation"
  | "clarity"
  | "sharpness"
  | "vignette"
  | "straighten";

export interface SliderSpec {
  key: SliderKey;
  min: number;
  max: number;
  step: number;
  /** CSS background for the track (temperature and tint show their colours). */
  track?: string;
}

const percent = (key: SliderKey, track?: string): SliderSpec => ({
  key,
  min: -100,
  max: 100,
  step: 1,
  ...(track ? { track } : {}),
});

export const SLIDER_GROUPS: { id: "basic" | "color" | "detail" | "effects"; sliders: SliderSpec[] }[] =
  [
    {
      id: "basic",
      sliders: [
        { key: "exposure", min: -5, max: 5, step: 0.05 },
        percent("contrast"),
        percent("highlights"),
        percent("shadows"),
        percent("whites"),
        percent("blacks"),
      ],
    },
    {
      id: "color",
      sliders: [
        percent("temperature", "linear-gradient(to right, #4d7cff, #d8d8d8, #ffc23d)"),
        percent("tint", "linear-gradient(to right, #3fbf5f, #d8d8d8, #d64fd0)"),
        percent("vibrance"),
        percent("saturation"),
      ],
    },
    {
      id: "detail",
      sliders: [percent("clarity"), { key: "sharpness", min: 0, max: 100, step: 1 }],
    },
    { id: "effects", sliders: [percent("vignette")] },
  ];

export const STRAIGHTEN: SliderSpec = { key: "straighten", min: -45, max: 45, step: 0.1 };

/** Fills in defaults (older or partial recipes) so recipes compare reliably. */
export function normalizeRecipe(recipe: Partial<EditRecipe>): EditRecipe {
  return { ...DEFAULT_RECIPE, ...recipe, crop: recipe.crop ?? null };
}

export function recipeKey(recipe: EditRecipe): string {
  return JSON.stringify(normalizeRecipe(recipe));
}

export function sameRecipe(a: EditRecipe, b: EditRecipe): boolean {
  return recipeKey(a) === recipeKey(b);
}

export function formatSlider(key: SliderKey, value: number): string {
  if (key === "exposure") return `${value > 0 ? "+" : ""}${value.toFixed(2)}`;
  if (key === "straighten") return `${value > 0 ? "+" : ""}${value.toFixed(1)}°`;
  const rounded = Math.round(value);
  return `${rounded > 0 ? "+" : ""}${rounded}`;
}

// --- Crop -----------------------------------------------------------------------------------

export const FULL_FRAME: Crop = { x: 0, y: 0, width: 1, height: 1 };
export const MIN_CROP = 0.05;

export type AspectId = "free" | "original" | "1:1" | "4:3" | "3:2" | "16:9";
export const ASPECTS: AspectId[] = ["free", "original", "1:1", "4:3", "3:2", "16:9"];

/**
 * Width/height in pixels for an aspect, oriented like the frame (a landscape ratio
 * becomes portrait on a portrait photo). `null` for free cropping.
 */
export function aspectRatio(aspect: AspectId, frameWidth: number, frameHeight: number) {
  if (aspect === "free") return null;
  if (aspect === "original") return frameWidth / frameHeight;
  const [w, h] = aspect.split(":").map(Number) as [number, number];
  return frameWidth >= frameHeight ? w / h : h / w;
}

/** The largest crop with ``ratio`` (pixels) centred on ``crop``, inside the frame. */
export function fitAspect(crop: Crop, ratio: number, frameWidth: number, frameHeight: number): Crop {
  // In frame fractions, width / height = ratio * frameHeight / frameWidth.
  const fractionRatio = (ratio * frameHeight) / frameWidth;
  let width = crop.width;
  let height = width / fractionRatio;
  if (height > crop.height) {
    height = crop.height;
    width = height * fractionRatio;
  }
  const centreX = crop.x + crop.width / 2;
  const centreY = crop.y + crop.height / 2;
  return clampCrop({ x: centreX - width / 2, y: centreY - height / 2, width, height });
}

/** Keeps a crop inside the frame (moving it, never resizing). */
export function clampCrop(crop: Crop): Crop {
  const width = Math.min(1, Math.max(MIN_CROP, crop.width));
  const height = Math.min(1, Math.max(MIN_CROP, crop.height));
  return {
    x: Math.min(1 - width, Math.max(0, crop.x)),
    y: Math.min(1 - height, Math.max(0, crop.y)),
    width,
    height,
  };
}

export function isFullFrame(crop: Crop | null | undefined): boolean {
  return !crop || (crop.x <= 1e-4 && crop.y <= 1e-4 && crop.width >= 1 - 1e-4 && crop.height >= 1 - 1e-4);
}

/** Rotating a quarter turn: the crop turns with the photo. */
export function rotateCrop(crop: Crop | null | undefined, clockwise: boolean): Crop | null {
  if (!crop) return null;
  return clockwise
    ? { x: 1 - crop.y - crop.height, y: crop.x, width: crop.height, height: crop.width }
    : { x: crop.y, y: 1 - crop.x - crop.width, width: crop.height, height: crop.width };
}

export function flipCrop(crop: Crop | null | undefined): Crop | null {
  return crop ? { ...crop, x: 1 - crop.x - crop.width } : null;
}

export type CropHandle = "move" | "n" | "s" | "e" | "w" | "ne" | "nw" | "se" | "sw";

const clamp = (value: number, low: number, high: number) => Math.min(high, Math.max(low, value));

/**
 * The crop after dragging ``handle`` by (dx, dy) frame fractions from ``start``.
 * With a ratio (width / height in frame fractions) the side or corner opposite the
 * handle stays put (edges keep their centre), and the crop shrinks to stay inside.
 */
export function resizeCrop(
  start: Crop,
  handle: CropHandle,
  dx: number,
  dy: number,
  ratio: number | null,
): Crop {
  if (handle === "move") return clampCrop({ ...start, x: start.x + dx, y: start.y + dy });

  const right0 = start.x + start.width;
  const bottom0 = start.y + start.height;
  let left = start.x;
  let top = start.y;
  let right = right0;
  let bottom = bottom0;
  if (handle.includes("w")) left = clamp(left + dx, 0, right - MIN_CROP);
  if (handle.includes("e")) right = clamp(right + dx, left + MIN_CROP, 1);
  if (handle.includes("n")) top = clamp(top + dy, 0, bottom - MIN_CROP);
  if (handle.includes("s")) bottom = clamp(bottom + dy, top + MIN_CROP, 1);
  if (ratio === null) return { x: left, y: top, width: right - left, height: bottom - top };

  const horizontal = handle.includes("w") ? "end" : handle.includes("e") ? "start" : "centre";
  const vertical = handle.includes("n") ? "end" : handle.includes("s") ? "start" : "centre";
  const anchorX = horizontal === "end" ? right0 : horizontal === "start" ? start.x : start.x + start.width / 2;
  const anchorY = vertical === "end" ? bottom0 : vertical === "start" ? start.y : start.y + start.height / 2;
  const room = (anchor: number, side: string) =>
    side === "end" ? anchor : side === "start" ? 1 - anchor : 2 * Math.min(anchor, 1 - anchor);

  let width = handle === "n" || handle === "s" ? (bottom - top) * ratio : right - left;
  width = Math.min(width, room(anchorX, horizontal), room(anchorY, vertical) * ratio);
  width = Math.max(width, MIN_CROP);
  const height = width / ratio;
  const place = (anchor: number, size: number, side: string) =>
    side === "end" ? anchor - size : side === "start" ? anchor : anchor - size / 2;
  return clampCrop({
    x: place(anchorX, width, horizontal),
    y: place(anchorY, height, vertical),
    width,
    height,
  });
}

/** Recipe fields that history steps name (everything but the version). */
export type { RecipeField } from "@/api/types";
