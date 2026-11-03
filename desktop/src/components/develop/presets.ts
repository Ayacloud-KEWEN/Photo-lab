import type { EditRecipe, RecipeField } from "@/api/types";

import { DEFAULT_RECIPE } from "./recipe";

/** Settings that make sense on another photo: everything but rotation, flip and crop. */
export const COPY_FIELDS: RecipeField[] = [
  "exposure",
  "contrast",
  "highlights",
  "shadows",
  "whites",
  "blacks",
  "temperature",
  "tint",
  "vibrance",
  "saturation",
  "clarity",
  "sharpness",
  "vignette",
];

export type PresetId =
  | "bw"
  | "bwContrast"
  | "warm"
  | "cool"
  | "vivid"
  | "soft"
  | "film"
  | "landscape";

/** Built-in looks. Applying one sets only the values it lists; the rest of the edit stays. */
export const PRESETS: { id: PresetId; values: Partial<EditRecipe> }[] = [
  { id: "bw", values: { saturation: -100, vibrance: 0, contrast: 15, clarity: 10 } },
  {
    id: "bwContrast",
    values: { saturation: -100, vibrance: 0, contrast: 45, whites: 15, blacks: -20, clarity: 25 },
  },
  { id: "warm", values: { temperature: 25, tint: 5, vibrance: 10 } },
  { id: "cool", values: { temperature: -25, tint: -3 } },
  { id: "vivid", values: { vibrance: 35, saturation: 10, contrast: 15, clarity: 10 } },
  { id: "soft", values: { contrast: -25, blacks: 25, highlights: -15, saturation: -15 } },
  {
    id: "film",
    values: { contrast: 10, blacks: 15, temperature: 8, saturation: -10, vignette: -20 },
  },
  { id: "landscape", values: { clarity: 25, vibrance: 25, highlights: -30, shadows: 20 } },
];

/** What to send to apply ``values`` to other photos: a full recipe and the fields to take. */
export function settingsFor(values: Partial<EditRecipe>): {
  recipe: EditRecipe;
  fields: RecipeField[];
} {
  return {
    recipe: { ...DEFAULT_RECIPE, ...values },
    fields: Object.keys(values) as RecipeField[],
  };
}

export function pick(recipe: EditRecipe, fields: RecipeField[]): Partial<EditRecipe> {
  return Object.fromEntries(fields.map((field) => [field, recipe[field]])) as Partial<EditRecipe>;
}
