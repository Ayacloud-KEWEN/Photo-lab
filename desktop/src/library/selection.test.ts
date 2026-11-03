import { describe, expect, it } from "vitest";

import { emptySelection, pruneSelection, selectAll, selectItem } from "./selection";

const order = [10, 20, 30, 40, 50];
const ids = (state: { selected: ReadonlySet<number> }) => [...state.selected].sort((a, b) => a - b);

describe("selection", () => {
  it("plain click selects one item", () => {
    const state = selectItem(selectItem(emptySelection, 10, order), 30, order);
    expect(ids(state)).toEqual([30]);
    expect(state.focused).toBe(30);
  });

  it("ctrl+click toggles", () => {
    let state = selectItem(emptySelection, 10, order);
    state = selectItem(state, 30, order, { toggle: true });
    expect(ids(state)).toEqual([10, 30]);
    state = selectItem(state, 10, order, { toggle: true });
    expect(ids(state)).toEqual([30]);
  });

  it("shift+click selects a range from the anchor, in either direction", () => {
    let state = selectItem(emptySelection, 20, order);
    state = selectItem(state, 40, order, { range: true });
    expect(ids(state)).toEqual([20, 30, 40]);
    state = selectItem(state, 10, order, { range: true });
    expect(ids(state)).toEqual([10, 20]);
  });

  it("ctrl+shift adds a range to the selection", () => {
    let state = selectItem(emptySelection, 10, order);
    state = selectItem(state, 40, order, { toggle: true });
    state = selectItem(state, 50, order, { toggle: true, range: true });
    expect(ids(state)).toEqual([10, 40, 50]);
  });

  it("select all and prune", () => {
    const all = selectAll(order, 30);
    expect(ids(all)).toEqual(order);
    const pruned = pruneSelection(all, new Set([20, 30]));
    expect(ids(pruned)).toEqual([20, 30]);
    expect(pruned.focused).toBe(30);
    expect(pruneSelection(pruned, new Set([20, 30]))).toBe(pruned); // unchanged → same object
  });
});
