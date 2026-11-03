import { describe, expect, it } from "vitest";

import { clampAspect, gridRows, justifiedRows, neighbor, type LayoutInput } from "./layout";

const items = (aspects: number[]): LayoutInput[] =>
  aspects.map((aspect, index) => ({ id: index + 1, aspect }));

const rowWidth = (row: { cells: { width: number }[] }, gap: number) =>
  row.cells.reduce((sum, cell) => sum + cell.width, 0) + gap * (row.cells.length - 1);

describe("justifiedRows", () => {
  it("fills every complete row to the exact width", () => {
    const rows = justifiedRows(items([1.5, 1.5, 0.67, 1, 1.78, 1.5, 1.5, 1]), 1000, 200, 4);
    expect(rows.length).toBeGreaterThan(1);
    for (const row of rows.slice(0, -1)) {
      expect(rowWidth(row, 4)).toBeCloseTo(1000, 6);
      expect(row.height).toBeGreaterThan(150);
      expect(row.height).toBeLessThan(260);
    }
  });

  it("keeps aspect ratios and positions cells left to right", () => {
    const [row] = justifiedRows(items([2, 1, 1]), 400, 100, 0);
    expect(row!.height).toBe(100);
    expect(row!.cells.map((cell) => [cell.x, cell.width])).toEqual([
      [0, 200],
      [200, 100],
      [300, 100],
    ]);
  });

  it("does not stretch the last row", () => {
    const rows = justifiedRows(items([1, 1, 1, 1, 1, 1]), 1000, 200, 0); // 5 fill a row
    const last = rows.at(-1)!;
    expect(last.height).toBe(200);
    expect(rowWidth(last, 0)).toBeLessThan(1000);
  });

  it("handles empty input and zero width", () => {
    expect(justifiedRows([], 1000, 200, 4)).toEqual([]);
    expect(justifiedRows(items([1]), 0, 200, 4)).toEqual([]);
  });

  it("clamps extreme or unknown aspect ratios", () => {
    expect(clampAspect(10)).toBe(3);
    expect(clampAspect(0.1)).toBe(0.4);
    expect(clampAspect(null)).toBe(1);
    expect(clampAspect(Number.NaN)).toBe(1);
  });
});

describe("gridRows", () => {
  it("makes square cells that fill the width", () => {
    const rows = gridRows(items([1, 2, 0.5, 1, 1]), 500, 120, 4);
    expect(rows[0]!.cells).toHaveLength(4);
    expect(rows[1]!.cells).toHaveLength(1);
    expect(rows[0]!.height).toBe(rows[0]!.cells[0]!.width);
    expect(rowWidth(rows[0]!, 4)).toBeCloseTo(500, 6);
  });
});

describe("neighbor", () => {
  const rows = gridRows(items([1, 1, 1, 1, 1, 1, 1]), 300, 90, 0); // 3 per row
  it("moves within and across rows", () => {
    expect(neighbor(rows, 2, "right")).toBe(3);
    expect(neighbor(rows, 3, "right")).toBe(4); // wraps to next row
    expect(neighbor(rows, 4, "left")).toBe(3);
    expect(neighbor(rows, 1, "left")).toBeNull();
    expect(neighbor(rows, 7, "right")).toBeNull();
  });
  it("moves vertically to the closest column", () => {
    expect(neighbor(rows, 2, "down")).toBe(5);
    expect(neighbor(rows, 6, "down")).toBe(7); // only one cell in the last row
    expect(neighbor(rows, 5, "up")).toBe(2);
    expect(neighbor(rows, 1, "up")).toBeNull();
  });
});
