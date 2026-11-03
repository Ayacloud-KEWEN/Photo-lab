import { describe, expect, it } from "vitest";

import {
  DEFAULT_RECIPE,
  FULL_FRAME,
  aspectRatio,
  clampCrop,
  fitAspect,
  flipCrop,
  formatSlider,
  isFullFrame,
  normalizeRecipe,
  resizeCrop,
  rotateCrop,
  sameRecipe,
} from "./recipe";

const close = (a: object, b: object) =>
  Object.entries(b).forEach(([key, value]) =>
    expect((a as Record<string, number>)[key]).toBeCloseTo(value as number, 6),
  );

describe("develop recipes", () => {
  it("compares recipes including omitted defaults", () => {
    expect(sameRecipe(normalizeRecipe({ exposure: 0 }), DEFAULT_RECIPE)).toBe(true);
    expect(sameRecipe({ ...DEFAULT_RECIPE, contrast: 5 }, DEFAULT_RECIPE)).toBe(false);
  });

  it("formats slider values", () => {
    expect(formatSlider("exposure", 0.5)).toBe("+0.50");
    expect(formatSlider("contrast", -12.4)).toBe("-12");
    expect(formatSlider("straighten", 1.25)).toBe("+1.3°");
    expect(formatSlider("saturation", 0)).toBe("0");
  });

  it("orients aspect ratios like the frame", () => {
    expect(aspectRatio("free", 6000, 4000)).toBeNull();
    expect(aspectRatio("original", 6000, 4000)).toBeCloseTo(1.5);
    expect(aspectRatio("16:9", 6000, 4000)).toBeCloseTo(16 / 9);
    expect(aspectRatio("16:9", 4000, 6000)).toBeCloseTo(9 / 16);
  });

  it("fits an aspect ratio inside the frame", () => {
    // A 3:2 frame cropped square: full height, centred.
    close(fitAspect(FULL_FRAME, 1, 3000, 2000), { x: 1 / 6, y: 0, width: 2 / 3, height: 1 });
  });

  it("keeps crops inside the frame", () => {
    close(clampCrop({ x: 0.8, y: -0.2, width: 0.5, height: 0.5 }), {
      x: 0.5,
      y: 0,
      width: 0.5,
      height: 0.5,
    });
    expect(isFullFrame(null)).toBe(true);
    expect(isFullFrame({ x: 0, y: 0, width: 0.9, height: 1 })).toBe(false);
  });

  it("resizes freely from edges and corners", () => {
    const start = { x: 0.2, y: 0.2, width: 0.5, height: 0.5 };
    close(resizeCrop(start, "se", 0.1, 0.2, null), { x: 0.2, y: 0.2, width: 0.6, height: 0.7 });
    close(resizeCrop(start, "w", -0.5, 0, null), { x: 0, width: 0.7 }); // stops at the edge
    close(resizeCrop(start, "move", 0.5, 0, null), { x: 0.5, y: 0.2, width: 0.5 });
  });

  it("keeps the ratio and the opposite corner when resizing with an aspect", () => {
    const start = { x: 0.2, y: 0.2, width: 0.4, height: 0.4 };
    const out = resizeCrop(start, "se", 0.2, 0, 1);
    close(out, { x: 0.2, y: 0.2, width: 0.6, height: 0.6 });
    const shrunk = resizeCrop(start, "nw", 0.1, 0.1, 1);
    close(shrunk, { x: 0.3, y: 0.3, width: 0.3, height: 0.3 });
    // Growing past the frame stops at the edge, still square.
    const capped = resizeCrop(start, "se", 0.9, 0, 1);
    expect(capped.width).toBeCloseTo(capped.height);
    expect(capped.x + capped.width).toBeLessThanOrEqual(1 + 1e-9);
  });

  it("turns and mirrors crops with the photo", () => {
    const crop = { x: 0.1, y: 0.2, width: 0.3, height: 0.4 };
    close(rotateCrop(crop, true)!, { x: 0.4, y: 0.1, width: 0.4, height: 0.3 });
    close(rotateCrop(rotateCrop(crop, true), false)!, crop);
    close(flipCrop(crop)!, { x: 0.6, y: 0.2 });
    expect(rotateCrop(null, true)).toBeNull();
  });
});
