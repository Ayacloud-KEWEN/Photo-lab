-- Phase 4: local AI (embeddings, AI labels) and the cloud analysis cache.

-- One vector per asset and model, computed from the asset's cover file.
CREATE TABLE embeddings (
    asset_id       INTEGER NOT NULL REFERENCES media_assets (id) ON DELETE CASCADE,
    model_id       TEXT    NOT NULL,                 -- e.g. 'siglip2-so400m-patch14-384'
    fingerprint    TEXT    NOT NULL,                 -- cover content the vector was computed from
    dim            INTEGER NOT NULL CHECK (dim > 0),
    vector         BLOB    NOT NULL,                 -- float16, L2-normalized
    labels_version INTEGER NOT NULL DEFAULT 0,       -- label vocabulary applied (0 = none)
    created_at     TEXT    NOT NULL,
    PRIMARY KEY (asset_id, model_id)
) WITHOUT ROWID;

CREATE INDEX idx_embeddings_model ON embeddings (model_id, labels_version);

-- media_tags gains the 'ai' source and a confidence. SQLite cannot alter a CHECK
-- constraint, so the table is rebuilt; the search view depends on it and is
-- recreated unchanged (definition from 0003).
DROP VIEW asset_search_source;

CREATE TABLE media_tags_new (
    asset_id   INTEGER NOT NULL REFERENCES media_assets (id) ON DELETE CASCADE,
    tag_id     INTEGER NOT NULL REFERENCES tags (id) ON DELETE CASCADE,
    source     TEXT    NOT NULL CHECK (source IN ('user', 'import', 'ai')),
    confidence REAL    CHECK (confidence IS NULL OR confidence BETWEEN 0 AND 1),
    created_at TEXT    NOT NULL,
    PRIMARY KEY (asset_id, tag_id)
) WITHOUT ROWID;

INSERT INTO media_tags_new (asset_id, tag_id, source, created_at)
SELECT asset_id, tag_id, source, created_at FROM media_tags;

DROP TABLE media_tags;
ALTER TABLE media_tags_new RENAME TO media_tags;
CREATE INDEX idx_media_tags_tag ON media_tags (tag_id, asset_id);

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

-- Cached cloud analyses. Results are reused when the same request (kind, model,
-- prompt version, language, options and image fingerprints) is made again.
CREATE TABLE ai_analysis (
    id             INTEGER PRIMARY KEY,
    kind           TEXT    NOT NULL
                   CHECK (kind IN ('describe', 'critique', 'select_best', 'story')),
    provider       TEXT    NOT NULL,                 -- 'deepseek'
    model          TEXT    NOT NULL,
    prompt_version INTEGER NOT NULL,
    language       TEXT    NOT NULL,
    cache_key      TEXT    NOT NULL UNIQUE,
    vision         INTEGER NOT NULL CHECK (vision IN (0, 1)),  -- 0 = text-only fallback
    result         TEXT    NOT NULL,                 -- Markdown
    data           TEXT    CHECK (data IS NULL OR json_valid(data)),  -- structured output
    input_tokens   INTEGER,
    output_tokens  INTEGER,
    created_at     TEXT    NOT NULL
);

CREATE TABLE ai_analysis_assets (
    analysis_id INTEGER NOT NULL REFERENCES ai_analysis (id) ON DELETE CASCADE,
    asset_id    INTEGER NOT NULL REFERENCES media_assets (id) ON DELETE CASCADE,
    position    INTEGER NOT NULL,
    PRIMARY KEY (analysis_id, asset_id)
) WITHOUT ROWID;

CREATE INDEX idx_ai_analysis_assets_asset ON ai_analysis_assets (asset_id);
