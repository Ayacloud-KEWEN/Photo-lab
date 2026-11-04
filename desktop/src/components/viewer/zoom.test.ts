import { describe, expect, it } from "vitest";

import { FIT, actualScale, clamp, fit, maxScale, wheelFactor, zoomAt } from "./zoom";

const stage = { width: 1000, height: 600 };
const photo = { width: 2048, height: 1536 }; // 4:3 preview
const fitted = fit(stage, photo); // 800 x 600, centred: left 100

describe("viewer zoom", () => {
  it("fits the photo like object-fit: contain", () => {
    expect(fitted).toEqual({ width: 800, height: 600, left: 100, top: 0 });
    expect(fit(stage, { width: 400, height: 300 }).width).toBe(800); // small photos fill too
  });

  it("computes 100% and the zoom limit from the full-size photo", () => {
    expect(actualScale(fitted, 4000)).toBe(5); // 4000 px photo shown 800 px wide
    expect(actualScale(fitted, 4000, 2)).toBe(2.5); // on a 2x screen
    expect(actualScale(fitted, 600)).toBe(1); // never below "fit"
    expect(maxScale(fitted, 4000)).toBe(20);
  });

  it("keeps the point under the pointer in place", () => {
    const point = { x: 300, y: 150 };
    const zoomed = zoomAt(FIT, 2, point, stage, fitted, 10);
    expect(zoomed.scale).toBe(2);
    // The photo point that was under the pointer (200, 150 in the fitted box) still is.
    expect(fitted.left + zoomed.x + 200 * zoomed.scale).toBeCloseTo(point.x);
    expect(fitted.top + zoomed.y + 150 * zoomed.scale).toBeCloseTo(point.y);
  });

  it("stays within its limits and returns to fit", () => {
    expect(zoomAt(FIT, 50, { x: 500, y: 300 }, stage, fitted, 8).scale).toBe(8);
    const zoomed = zoomAt(FIT, 3, { x: 500, y: 300 }, stage, fitted, 8);
    expect(zoomAt(zoomed, 0.5, { x: 0, y: 0 }, stage, fitted, 8)).toEqual(FIT);
  });

  it("keeps a zoomed photo covering the stage while panning", () => {
    // 2x: 1600 x 1200 inside 1000 x 600, so it may move between the edges only.
    const far = clamp({ scale: 2, x: 5000, y: 5000 }, stage, fitted);
    expect(far).toEqual({ scale: 2, x: -100, y: 0 }); // left/top edges at the stage's
    const other = clamp({ scale: 2, x: -5000, y: -5000 }, stage, fitted);
    expect(fitted.left + other.x + 1600).toBe(1000); // right edge at the stage's
    expect(other.y + 1200).toBe(600);
    // 1.2x: 960 wide, narrower than the stage: centred horizontally.
    const narrow = clamp({ scale: 1.2, x: 300, y: 0 }, stage, fitted);
    expect(fitted.left + narrow.x).toBeCloseTo((1000 - 960) / 2);
  });

  it("turns wheel movement into a zoom factor", () => {
    expect(wheelFactor(-100, 0)).toBeGreaterThan(1); // wheel up: zoom in
    expect(wheelFactor(100, 0)).toBeLessThan(1);
    expect(wheelFactor(3, 1)).toBeCloseTo(wheelFactor(48, 0)); // lines count as 16 px
    expect(wheelFactor(-100, 0) * wheelFactor(100, 0)).toBeCloseTo(1); // symmetric
  });
});
