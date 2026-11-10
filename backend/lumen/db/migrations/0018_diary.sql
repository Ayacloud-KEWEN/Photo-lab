-- A portfolio's travel diary: the user's text by day, between its photos. A day's
-- opening text has no photo (after_asset_id NULL); other texts follow a photo. Days are
-- capture dates (YYYY-MM-DD, '' for undated photos).

CREATE TABLE collection_diary (
    id             INTEGER PRIMARY KEY,
    collection_id  INTEGER NOT NULL REFERENCES collections (id) ON DELETE CASCADE,
    day            TEXT    NOT NULL,
    after_asset_id INTEGER REFERENCES media_assets (id) ON DELETE CASCADE,
    text           TEXT    NOT NULL,
    updated_at     TEXT    NOT NULL
);
CREATE UNIQUE INDEX idx_collection_diary_place
    ON collection_diary (collection_id, day, COALESCE(after_asset_id, 0));
