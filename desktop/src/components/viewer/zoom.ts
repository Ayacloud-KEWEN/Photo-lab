/**
 * Zoom and pan of a photo in the viewer, as pure functions.
 *
 * The photo is first fitted into the stage (scale 1). Zooming scales that fitted box by
 * `scale` around its top-left corner and moves it by `x`/`y` (CSS pixels, relative to the
 * fitted position), so the transform is `translate(x, y) scale(scale)`.
 */

export interface Size {
  width: number;
  height: number;
}

export interface View {
  scale: number;
  x: number;
  y: number;
}

export const FIT: View = { scale: 1, x: 0, y: 0 };
/** How far past one photo pixel per screen pixel zooming may go. */
export const MAX_PIXEL_ZOOM = 4;

/** The photo fitted into the stage (like `object-fit: contain`), and where it sits in it. */
export function fit(stage: Size, photo: Size): Size & { left: number; top: number } {
  const ratio = Math.min(stage.width / photo.width, stage.height / photo.height);
  const width = photo.width * ratio;
  const height = photo.height * ratio;
  return { width, height, left: (stage.width - width) / 2, top: (stage.height - height) / 2 };
}

/** The scale at which one photo pixel covers one screen (device) pixel. */
export function actualScale(fitted: Size, fullWidth: number, devicePixelRatio = 1): number {
  return Math.max(1, fullWidth / (fitted.width * devicePixelRatio));
}

export function maxScale(fitted: Size, fullWidth: number, devicePixelRatio = 1): number {
  return Math.max(1, actualScale(fitted, fullWidth, devicePixelRatio) * MAX_PIXEL_ZOOM);
}

/**
 * Keep the zoomed photo covering the stage where it is larger than the stage, and
 * centred where it is smaller.
 */
export function clamp(view: View, stage: Size, fitted: ReturnType<typeof fit>): View {
  const axis = (offset: number, start: number, size: number, room: number) => {
    const scaled = size * view.scale;
    if (scaled <= room) return (room - scaled) / 2 - start;
    return Math.min(0 - start, Math.max(room - scaled - start, offset)); // 0 - x: never -0
  };
  return {
    scale: view.scale,
    x: axis(view.x, fitted.left, fitted.width, stage.width),
    y: axis(view.y, fitted.top, fitted.height, stage.height),
  };
}

/**
 * Zoom to `scale` (bounded to [1, max]) keeping the photo point under `point` (stage
 * coordinates) where it is.
 */
export function zoomAt(
  view: View,
  scale: number,
  point: { x: number; y: number },
  stage: Size,
  fitted: ReturnType<typeof fit>,
  max: number,
): View {
  const next = Math.min(max, Math.max(1, scale));
  if (next === 1) return FIT;
  // The photo point (in fitted-box units) under the pointer stays under it.
  const u = (point.x - fitted.left - view.x) / view.scale;
  const v = (point.y - fitted.top - view.y) / view.scale;
  return clamp(
    { scale: next, x: point.x - fitted.left - u * next, y: point.y - fitted.top - v * next },
    stage,
    fitted,
  );
}

/** Wheel movement as a zoom factor (lines and pages counted as pixels). */
export function wheelFactor(deltaY: number, deltaMode: number): number {
  const pixels = deltaMode === 1 ? deltaY * 16 : deltaMode === 2 ? deltaY * 400 : deltaY;
  return Math.exp(-pixels * 0.0015);
}
