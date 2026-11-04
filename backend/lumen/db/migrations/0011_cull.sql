-- Culling (ADR-025): pick / reject flags and photo quality scores.

-- 'reject' hides the asset everywhere unless asked for; nothing is deleted.
ALTER TABLE media_assets ADD COLUMN cull_flag TEXT NOT NULL DEFAULT 'none'
    CHECK (cull_flag IN ('none', 'pick', 'reject'));
CREATE INDEX idx_media_assets_rejected ON media_assets (capture_time) WHERE cull_flag = 'reject';

-- Sharpness and exposure measured on the photo's preview (not its edit).
CREATE TABLE media_quality (
    asset_id    INTEGER PRIMARY KEY REFERENCES media_assets (id) ON DELETE CASCADE,
    fingerprint TEXT    NOT NULL,              -- cover content that was measured
    version     INTEGER NOT NULL,              -- scoring method
    sharpness   REAL,                          -- 0..1, NULL when the preview was unavailable
    exposure    REAL,                          -- 0..1 (1 = nothing clipped)
    highlights  REAL,                          -- fraction of clipped highlights
    shadows     REAL,                          -- fraction of crushed shadows
    score       REAL,                          -- 0..1 overall
    flags       TEXT    NOT NULL DEFAULT '',   -- comma separated: blurry, overexposed, underexposed
    updated_at  TEXT    NOT NULL
);

CREATE INDEX idx_media_quality_score ON media_quality (score);
