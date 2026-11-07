import { describe, expect, it } from "vitest";

import type { RouteStop } from "@/api/types";

import { DAY_COLORS, dayColor, routeDays, stopsLabel } from "./route";

const stop = (day: number, start: string): RouteStop => ({
  lat: 0, lon: 0, start, end: start, day, asset_ids: [1],
  cover: { id: 1, lat: 0, lon: 0, v: "v", p: null }, place: null,
}); // prettier-ignore

describe("route helpers", () => {
  it("groups stops by day and keeps their position in the route", () => {
    const days = routeDays([
      stop(1, "2025-03-01T09:00:00"),
      stop(1, "2025-03-01T15:00:00"),
      stop(3, "2025-03-03T10:00:00"),
    ]);
    expect(days.map((day) => [day.day, day.date, day.stops.map((s) => s.index)])).toEqual([
      [1, "2025-03-01", [0, 1]],
      [3, "2025-03-03", [2]],
    ]);
    expect(routeDays([])).toEqual([]);
  });

  it("labels a group of stops by their numbers", () => {
    expect(stopsLabel([4])).toBe("5");
    expect(stopsLabel([2, 0, 1])).toBe("1–3");
    expect(stopsLabel([0, 28])).toBe("1, 29");
    expect(stopsLabel([0, 1, 2, 9, 20, 28])).toBe("1–3, 10…");
  });

  it("repeats the day colours", () => {
    expect(dayColor(1)).toBe(DAY_COLORS[0]);
    expect(dayColor(DAY_COLORS.length + 2)).toBe(DAY_COLORS[1]);
  });
});
