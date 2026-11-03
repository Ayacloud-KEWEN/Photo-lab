-- Non-destructive photo editing (ADR-018). Every saved edit is a recipe (JSON); the asset
-- points at the one in effect. Originals are never written.

CREATE TABLE edit_history (
    id          INTEGER PRIMARY KEY,
    asset_id    INTEGER NOT NULL REFERENCES media_assets (id) ON DELETE CASCADE,
    recipe      TEXT NOT NULL CHECK (json_valid(recipe)),
    -- Content hash of the recipe; '' when it changes nothing (a reset).
    recipe_hash TEXT NOT NULL,
    created_at  TEXT NOT NULL
);
CREATE INDEX idx_edit_history_asset ON edit_history (asset_id, id);

ALTER TABLE media_assets ADD COLUMN current_edit_id INTEGER
    REFERENCES edit_history (id) ON DELETE SET NULL;
