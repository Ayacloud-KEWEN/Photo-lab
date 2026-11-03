/** Explorer-style multi-selection: click, Ctrl+click (toggle), Shift+click (range). */

export interface SelectionState {
  selected: ReadonlySet<number>;
  /** Start of a Shift range. */
  anchor: number | null;
  /** Keyboard focus; also what the inspector shows. */
  focused: number | null;
}

export const emptySelection: SelectionState = { selected: new Set(), anchor: null, focused: null };

export interface Modifiers {
  toggle?: boolean;
  range?: boolean;
}

export function selectItem(
  state: SelectionState,
  id: number,
  order: readonly number[],
  { toggle = false, range = false }: Modifiers = {},
): SelectionState {
  if (range && state.anchor !== null) {
    const from = order.indexOf(state.anchor);
    const to = order.indexOf(id);
    if (from >= 0 && to >= 0) {
      const [start, end] = from <= to ? [from, to] : [to, from];
      const span = order.slice(start, end + 1);
      const selected = toggle ? new Set([...state.selected, ...span]) : new Set(span);
      return { selected, anchor: state.anchor, focused: id };
    }
  }
  if (toggle) {
    const selected = new Set(state.selected);
    if (selected.has(id)) selected.delete(id);
    else selected.add(id);
    return { selected, anchor: id, focused: id };
  }
  return { selected: new Set([id]), anchor: id, focused: id };
}

export function selectAll(ids: readonly number[], focused: number | null): SelectionState {
  return { selected: new Set(ids), anchor: ids[0] ?? null, focused: focused ?? ids[0] ?? null };
}

/** Drop ids that are no longer listed (after filtering or deletion). */
export function pruneSelection(state: SelectionState, visible: ReadonlySet<number>): SelectionState {
  const selected = new Set([...state.selected].filter((id) => visible.has(id)));
  if (selected.size === state.selected.size && (state.focused === null || visible.has(state.focused)))
    return state;
  return {
    selected,
    anchor: state.anchor !== null && visible.has(state.anchor) ? state.anchor : null,
    focused: state.focused !== null && visible.has(state.focused) ? state.focused : null,
  };
}
