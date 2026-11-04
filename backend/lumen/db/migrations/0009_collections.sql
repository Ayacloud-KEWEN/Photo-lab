-- Portfolios: albums and trips, each an ordered list of assets with captions (ADR-022).

CREATE TABLE collections (
    id             INTEGER PRIMARY KEY,
    uuid           TEXT    NOT NULL UNIQUE,
    name           TEXT    NOT NULL CHECK (length(trim(name)) > 0),
    kind           TEXT    NOT NULL DEFAULT 'album' CHECK (kind IN ('album', 'trip')),
    description    TEXT,
    place          TEXT,                 -- trips: where, as the user names it
    start_date     TEXT,                 -- trips: 'YYYY-MM-DD'
    end_date       TEXT,
    cover_asset_id INTEGER REFERENCES media_assets (id) ON DELETE SET NULL,
    created_at     TEXT    NOT NULL,
    updated_at     TEXT    NOT NULL
);

CREATE TABLE collection_items (
    collection_id INTEGER NOT NULL REFERENCES collections (id) ON DELETE CASCADE,
    asset_id      INTEGER NOT NULL REFERENCES media_assets (id) ON DELETE CASCADE,
    position      INTEGER NOT NULL,
    caption       TEXT,
    added_at      TEXT    NOT NULL,
    PRIMARY KEY (collection_id, asset_id)
);
CREATE INDEX idx_collection_items_order ON collection_items (collection_id, position);
CREATE INDEX idx_collection_items_asset ON collection_items (asset_id);
