-- Phase 3: tags, ratings import, full-text search.

CREATE TABLE tags (
    id         INTEGER PRIMARY KEY,
    name       TEXT NOT NULL CHECK (length(trim(name)) > 0),
    name_key   TEXT NOT NULL UNIQUE,                  -- lower-cased, for case-insensitive uniqueness
    created_at TEXT NOT NULL
);

CREATE TABLE media_tags (
    asset_id   INTEGER NOT NULL REFERENCES media_assets (id) ON DELETE CASCADE,
    tag_id     INTEGER NOT NULL REFERENCES tags (id) ON DELETE CASCADE,
    source     TEXT    NOT NULL CHECK (source IN ('user', 'import')),
    created_at TEXT    NOT NULL,
    PRIMARY KEY (asset_id, tag_id)
) WITHOUT ROWID;

CREATE INDEX idx_media_tags_tag ON media_tags (tag_id, asset_id);

-- NULL: never rated; 'import': taken from XMP/EXIF; 'user': set in LUMEN (never overwritten).
ALTER TABLE media_assets ADD COLUMN rating_source TEXT
    CHECK (rating_source IS NULL OR rating_source IN ('import', 'user'));
CREATE INDEX idx_media_assets_rating ON media_assets (rating, capture_time);

-- Read-only imports from XMP/IPTC (Lightroom etc.).
ALTER TABLE media_metadata ADD COLUMN keywords TEXT
    CHECK (keywords IS NULL OR json_valid(keywords));
ALTER TABLE media_metadata ADD COLUMN xmp_rating INTEGER
    CHECK (xmp_rating IS NULL OR xmp_rating BETWEEN -1 AND 5);
CREATE INDEX idx_media_metadata_model ON media_metadata (camera_model);

-- Full-text search. The view is the single definition of what is searchable;
-- lumen.library.search re-indexes assets from it whenever they change.
CREATE VIEW asset_search_source AS
SELECT a.id AS asset_id,
       trim(
           COALESCE((SELECT group_concat(f.relative_path, ' ')
                     FROM media_files f WHERE f.asset_id = a.id), '')
           || ' ' ||
           COALESCE((SELECT group_concat(DISTINCT r.display_name)
                     FROM media_files f JOIN storage_roots r ON r.id = f.storage_root_id
                     WHERE f.asset_id = a.id), '')
           || ' ' ||
           COALESCE((SELECT group_concat(DISTINCT trim(COALESCE(m.camera_make, '') || ' '
                                                    || COALESCE(m.camera_model, '') || ' '
                                                    || COALESCE(m.lens_model, '')))
                     FROM media_files f JOIN media_metadata m ON m.file_id = f.id
                     WHERE f.asset_id = a.id), '')
           || ' ' ||
           COALESCE((SELECT group_concat(t.name, ' ')
                     FROM media_tags mt JOIN tags t ON t.id = mt.tag_id
                     WHERE mt.asset_id = a.id), '')
           || ' ' ||
           COALESCE(a.notes, '')
       ) AS body
FROM media_assets a;

-- Trigram tokens give substring matching, which also works for Chinese text.
CREATE VIRTUAL TABLE asset_search USING fts5(body, tokenize = 'trigram');

CREATE TRIGGER trg_asset_search_delete AFTER DELETE ON media_assets
BEGIN
    DELETE FROM asset_search WHERE rowid = old.id;
END;

INSERT INTO asset_search (rowid, body) SELECT asset_id, body FROM asset_search_source;

-- Re-read metadata of already indexed files so keywords and ratings get imported.
-- Fingerprints and thumbnails are kept, so this is fast.
UPDATE media_files
SET ingest_state = 'pending', ingest_attempts = 0, ingest_error = NULL
WHERE status = 'present' AND ingest_state = 'done';

INSERT INTO tasks (kind, status, storage_root_id, payload, created_at, updated_at)
SELECT 'ingest_storage_root', 'pending', r.id, '{"reason": "migration 0003"}',
       strftime('%Y-%m-%dT%H:%M:%fZ', 'now'), strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
FROM storage_roots r
WHERE EXISTS (SELECT 1 FROM media_files f
              WHERE f.storage_root_id = r.id AND f.ingest_state = 'pending')
  AND NOT EXISTS (SELECT 1 FROM tasks t
                  WHERE t.storage_root_id = r.id AND t.kind = 'ingest_storage_root'
                    AND t.status IN ('pending', 'running'));
