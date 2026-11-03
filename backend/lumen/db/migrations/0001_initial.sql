-- LUMEN Studio initial schema (Phase 1).
-- Timestamps are ISO 8601 UTC strings, e.g. 2026-11-03T08:15:30.123Z.
-- Boolean columns are INTEGER 0/1. JSON columns are TEXT validated with json_valid().

-- A directory the user registered as a source of media. Never modified on disk.
CREATE TABLE storage_roots (
    id              INTEGER PRIMARY KEY,
    path            TEXT    NOT NULL,                 -- absolute path as displayed
    path_key        TEXT    NOT NULL UNIQUE,          -- normalized (case-folded) for uniqueness
    display_name    TEXT    NOT NULL,
    volume_serial   TEXT,                             -- identifies the drive across letter changes
    volume_label    TEXT,
    status          TEXT    NOT NULL DEFAULT 'pending_scan'
                    CHECK (status IN ('pending_scan', 'scanning', 'ready', 'offline', 'error')),
    last_scanned_at TEXT,
    created_at      TEXT    NOT NULL,
    updated_at      TEXT    NOT NULL
);

CREATE INDEX idx_storage_roots_volume_serial ON storage_roots (volume_serial);

-- A logical photo or video. One asset may have several physical files (RAW + JPEG, copies).
CREATE TABLE media_assets (
    id           INTEGER PRIMARY KEY,
    uuid         TEXT    NOT NULL UNIQUE,
    media_type   TEXT    NOT NULL CHECK (media_type IN ('photo', 'video')),
    capture_time TEXT,                                -- best known capture time, local ISO 8601
    rating       INTEGER NOT NULL DEFAULT 0 CHECK (rating BETWEEN 0 AND 5),
    is_favorite  INTEGER NOT NULL DEFAULT 0 CHECK (is_favorite IN (0, 1)),
    notes        TEXT,
    created_at   TEXT    NOT NULL,
    updated_at   TEXT    NOT NULL
);

CREATE INDEX idx_media_assets_capture_time ON media_assets (capture_time);
CREATE INDEX idx_media_assets_media_type ON media_assets (media_type, capture_time);
CREATE INDEX idx_media_assets_favorite ON media_assets (capture_time) WHERE is_favorite = 1;

-- A physical file inside a storage root, addressed by its path relative to that root.
CREATE TABLE media_files (
    id                INTEGER PRIMARY KEY,
    asset_id          INTEGER REFERENCES media_assets (id) ON DELETE SET NULL,
    storage_root_id   INTEGER NOT NULL REFERENCES storage_roots (id) ON DELETE CASCADE,
    relative_path     TEXT    NOT NULL,
    relative_path_key TEXT    NOT NULL,               -- normalized (case-folded)
    file_name         TEXT    NOT NULL,
    extension         TEXT    NOT NULL,               -- lower case, without dot
    file_role         TEXT    NOT NULL DEFAULT 'primary'
                      CHECK (file_role IN ('primary', 'companion', 'sidecar')),
    mime_type         TEXT,
    size_bytes        INTEGER NOT NULL CHECK (size_bytes >= 0),
    modified_at       TEXT    NOT NULL,               -- file system mtime
    fingerprint       TEXT,                           -- '<algorithm>:<hex>', computed during scan
    status            TEXT    NOT NULL DEFAULT 'present'
                      CHECK (status IN ('present', 'missing', 'error')),
    last_seen_at      TEXT,
    created_at        TEXT    NOT NULL,
    updated_at        TEXT    NOT NULL,
    UNIQUE (storage_root_id, relative_path_key)
);

CREATE INDEX idx_media_files_asset ON media_files (asset_id);
CREATE INDEX idx_media_files_fingerprint ON media_files (fingerprint);
CREATE INDEX idx_media_files_status ON media_files (storage_root_id, status);

-- Technical metadata extracted from one file.
CREATE TABLE media_metadata (
    file_id           INTEGER PRIMARY KEY REFERENCES media_files (id) ON DELETE CASCADE,
    width             INTEGER CHECK (width > 0),
    height            INTEGER CHECK (height > 0),
    orientation       INTEGER CHECK (orientation BETWEEN 1 AND 8),
    duration_ms       INTEGER CHECK (duration_ms >= 0),
    capture_time      TEXT,
    camera_make       TEXT,
    camera_model      TEXT,
    lens_model        TEXT,
    focal_length_mm   REAL,
    aperture          REAL,
    exposure_time_s   REAL,
    iso               INTEGER,
    raw_json          TEXT CHECK (raw_json IS NULL OR json_valid(raw_json)),
    extractor         TEXT    NOT NULL,               -- e.g. 'exiftool'
    extractor_version TEXT    NOT NULL,
    extracted_at      TEXT    NOT NULL
);

CREATE INDEX idx_media_metadata_camera ON media_metadata (camera_make, camera_model);
CREATE INDEX idx_media_metadata_lens ON media_metadata (lens_model);
CREATE INDEX idx_media_metadata_capture_time ON media_metadata (capture_time);

-- Persistent background jobs: survive restarts, support retries and cancellation.
CREATE TABLE tasks (
    id               INTEGER PRIMARY KEY,
    kind             TEXT    NOT NULL,                -- e.g. 'scan_storage_root'
    status           TEXT    NOT NULL DEFAULT 'pending'
                     CHECK (status IN ('pending', 'running', 'succeeded', 'failed', 'cancelled')),
    priority         INTEGER NOT NULL DEFAULT 0,
    storage_root_id  INTEGER REFERENCES storage_roots (id) ON DELETE CASCADE,
    payload          TEXT    NOT NULL DEFAULT '{}' CHECK (json_valid(payload)),
    progress_current INTEGER NOT NULL DEFAULT 0 CHECK (progress_current >= 0),
    progress_total   INTEGER CHECK (progress_total IS NULL OR progress_total >= 0),
    attempts         INTEGER NOT NULL DEFAULT 0 CHECK (attempts >= 0),
    max_attempts     INTEGER NOT NULL DEFAULT 3 CHECK (max_attempts >= 1),
    error            TEXT,
    created_at       TEXT    NOT NULL,
    updated_at       TEXT    NOT NULL,
    started_at       TEXT,
    finished_at      TEXT
);

CREATE INDEX idx_tasks_queue ON tasks (status, priority DESC, created_at);
CREATE INDEX idx_tasks_storage_root ON tasks (storage_root_id);
CREATE INDEX idx_tasks_kind ON tasks (kind, status);

-- Application-wide key/value settings.
CREATE TABLE app_settings (
    key        TEXT PRIMARY KEY,
    value      TEXT NOT NULL CHECK (json_valid(value)),
    updated_at TEXT NOT NULL
);
