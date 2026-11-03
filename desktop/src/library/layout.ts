/**
 * Photo wall layout. "Justified" rows keep each photo's aspect ratio and fill the
 * full width (every row the same width, row heights vary slightly); "grid" uses
 * square cells. Pure functions, so they are easy to test and cheap to recompute.
 */

export interface LayoutInput {
  id: number;
  /** width / height; unknown dimensions should pass 1. */
  aspect: number;
}

export interface LayoutCell {
  id: number;
  x: number;
  width: number;
}

export interface LayoutRow {
  cells: LayoutCell[];
  height: number;
}

export type WallMode = "justified" | "grid";

const MIN_ASPECT = 0.4; // very tall portraits and panoramas are clamped,
const MAX_ASPECT = 3; // so one photo cannot take a whole row or be a sliver

export function clampAspect(aspect: number | null | undefined): number {
  if (!aspect || !Number.isFinite(aspect)) return 1;
  return Math.min(MAX_ASPECT, Math.max(MIN_ASPECT, aspect));
}

export function justifiedRows(
  items: LayoutInput[],
  width: number,
  targetHeight: number,
  gap: number,
): LayoutRow[] {
  if (width <= 0) return [];
  const rows: LayoutRow[] = [];
  let pending: LayoutInput[] = [];
  let aspectSum = 0;

  const flush = (height: number) => {
    let x = 0;
    const cells = pending.map((item) => {
      const cellWidth = clampAspect(item.aspect) * height;
      const cell = { id: item.id, x, width: cellWidth };
      x += cellWidth + gap;
      return cell;
    });
    rows.push({ cells, height });
    pending = [];
    aspectSum = 0;
  };

  for (const item of items) {
    pending.push(item);
    aspectSum += clampAspect(item.aspect);
    const gaps = gap * (pending.length - 1);
    if (aspectSum * targetHeight + gaps >= width) {
      flush((width - gaps) / aspectSum);
    }
  }
  // The last, incomplete row keeps the target height instead of being stretched.
  if (pending.length > 0) flush(targetHeight);
  return rows;
}

export function gridRows(
  items: LayoutInput[],
  width: number,
  minCell: number,
  gap: number,
): LayoutRow[] {
  if (width <= 0) return [];
  const columns = Math.max(1, Math.floor((width + gap) / (minCell + gap)));
  const size = (width - gap * (columns - 1)) / columns;
  const rows: LayoutRow[] = [];
  for (let start = 0; start < items.length; start += columns) {
    rows.push({
      height: size,
      cells: items.slice(start, start + columns).map((item, index) => ({
        id: item.id,
        x: index * (size + gap),
        width: size,
      })),
    });
  }
  return rows;
}

/** Find the cell a keyboard arrow moves to; `null` when there is none. */
export function neighbor(
  rows: LayoutRow[],
  id: number,
  direction: "left" | "right" | "up" | "down",
): number | null {
  const rowIndex = rows.findIndex((row) => row.cells.some((cell) => cell.id === id));
  if (rowIndex < 0) return null;
  const row = rows[rowIndex]!;
  const cellIndex = row.cells.findIndex((cell) => cell.id === id);
  const cell = row.cells[cellIndex]!;

  if (direction === "left" || direction === "right") {
    const step = direction === "left" ? -1 : 1;
    const sameRow = row.cells[cellIndex + step];
    if (sameRow) return sameRow.id;
    const next = rows[rowIndex + step];
    if (!next || next.cells.length === 0) return null;
    return (step > 0 ? next.cells[0] : next.cells.at(-1))!.id;
  }

  // Up/down: the cell in the adjacent row whose centre is closest horizontally.
  let target = rows[rowIndex + (direction === "up" ? -1 : 1)];
  let offset = direction === "up" ? -1 : 1;
  while (target && target.cells.length === 0) {
    offset += direction === "up" ? -1 : 1;
    target = rows[rowIndex + offset];
  }
  if (!target) return null;
  const centre = cell.x + cell.width / 2;
  let best = target.cells[0]!;
  for (const candidate of target.cells) {
    const distance = Math.abs(candidate.x + candidate.width / 2 - centre);
    if (distance < Math.abs(best.x + best.width / 2 - centre)) best = candidate;
  }
  return best.id;
}
