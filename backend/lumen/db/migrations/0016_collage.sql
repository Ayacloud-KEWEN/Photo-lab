-- The two small photos next to a portfolio's cover in the list (its collage). NULL: the
-- first items besides the cover, as before.

ALTER TABLE collections ADD COLUMN collage1_asset_id INTEGER
    REFERENCES media_assets (id) ON DELETE SET NULL;
ALTER TABLE collections ADD COLUMN collage2_asset_id INTEGER
    REFERENCES media_assets (id) ON DELETE SET NULL;
