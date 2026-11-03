/** What the inspector shows: a storage root, an asset, or nothing. */
export type Selection = { kind: "root"; id: number } | { kind: "asset"; id: number } | null;
