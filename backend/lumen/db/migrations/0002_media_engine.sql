-- Phase 2: media scanning and ingestion.

-- Each scan of a root increments its generation; files not seen in the latest
-- generation are marked missing.
ALTER TABLE storage_roots ADD COLUMN scan_generation INTEGER NOT NULL DEFAULT 0;

ALTER TABLE media_files ADD COLUMN mtime_ns INTEGER NOT NULL DEFAULT 0;   -- exact change detection
ALTER TABLE media_files ADD COLUMN group_key TEXT NOT NULL DEFAULT '';   -- normalized dir + stem, for RAW+JPEG pairing
ALTER TABLE media_files ADD COLUMN scan_generation INTEGER NOT NULL DEFAULT 0;
ALTER TABLE media_files ADD COLUMN ingest_state TEXT NOT NULL DEFAULT 'pending'
    CHECK (ingest_state IN ('pending', 'done', 'error'));
ALTER TABLE media_files ADD COLUMN ingest_attempts INTEGER NOT NULL DEFAULT 0
    CHECK (ingest_attempts >= 0);
ALTER TABLE media_files ADD COLUMN ingest_error TEXT;

CREATE INDEX idx_media_files_ingest ON media_files (storage_root_id, ingest_state, id);
CREATE INDEX idx_media_files_group ON media_files (storage_root_id, group_key);

-- The file whose thumbnail represents the asset (e.g. the JPEG of a RAW+JPEG pair).
ALTER TABLE media_assets ADD COLUMN cover_file_id INTEGER
    REFERENCES media_files (id) ON DELETE SET NULL;

ALTER TABLE media_metadata ADD COLUMN video_codec TEXT;
ALTER TABLE media_metadata ADD COLUMN frame_rate REAL CHECK (frame_rate IS NULL OR frame_rate > 0);

-- Where an asset was captured. One row per asset; 'manual' rows are never overwritten by EXIF.
CREATE TABLE media_locations (
    asset_id   INTEGER PRIMARY KEY REFERENCES media_assets (id) ON DELETE CASCADE,
    latitude   REAL NOT NULL CHECK (latitude BETWEEN -90 AND 90),
    longitude  REAL NOT NULL CHECK (longitude BETWEEN -180 AND 180),
    altitude_m REAL,
    source     TEXT NOT NULL CHECK (source IN ('exif', 'manual')),
    updated_at TEXT NOT NULL
);

CREATE INDEX idx_media_locations_coords ON media_locations (latitude, longitude);

-- Task scheduling: delayed retries and cooperative cancellation of running tasks.
ALTER TABLE tasks ADD COLUMN run_after TEXT;
ALTER TABLE tasks ADD COLUMN cancel_requested INTEGER NOT NULL DEFAULT 0
    CHECK (cancel_requested IN (0, 1));
