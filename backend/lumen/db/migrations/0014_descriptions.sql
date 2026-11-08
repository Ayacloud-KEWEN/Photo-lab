-- Photo descriptions and the text read in photos by the local vision-language model
-- (ADR-038). One row per asset; they join the search document so the search box finds
-- what is in a photo ("喂海鸥") and what is written in it ("Kotor").

CREATE TABLE media_descriptions (
    asset_id       INTEGER PRIMARY KEY REFERENCES media_assets (id) ON DELETE CASCADE,
    fingerprint    TEXT    NOT NULL,                -- the cover file that was read
    model          TEXT    NOT NULL,                -- e.g. qwen3.6-35b-a3b
    prompt_version INTEGER NOT NULL,
    description    TEXT    NOT NULL,
    text           TEXT    NOT NULL,                -- as written in the photo, one line each
    keywords       TEXT    NOT NULL CHECK (json_valid(keywords)),
    truncated      INTEGER NOT NULL DEFAULT 0 CHECK (truncated IN (0, 1)),
    seconds        REAL,
    created_at     TEXT    NOT NULL
);

-- Photos the user asked to have read (first in line), and with which model: the
-- default one, or the slower, more careful one ("fine").
CREATE TABLE vlm_requests (
    asset_id     INTEGER PRIMARY KEY REFERENCES media_assets (id) ON DELETE CASCADE,
    fine         INTEGER NOT NULL DEFAULT 0 CHECK (fine IN (0, 1)),
    requested_at TEXT    NOT NULL
);

-- The search document gains the description, the text and the keywords (from 0010).
DROP VIEW asset_search_source;

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
           COALESCE((SELECT p.city || ' ' || p.city_zh || ' ' || p.city_fr || ' '
                            || COALESCE(p.region || ' ' || p.region_zh || ' ' || p.region_fr, '')
                            || ' ' || p.country || ' ' || p.country_zh || ' ' || p.country_fr
                     FROM media_places p WHERE p.asset_id = a.id), '')
           || ' ' ||
           COALESCE(a.notes, '')
           || ' ' ||
           COALESCE((SELECT d.description || ' ' || d.text || ' '
                            || COALESCE((SELECT group_concat(k.value, ' ')
                                         FROM json_each(d.keywords) k), '')
                     FROM media_descriptions d WHERE d.asset_id = a.id), '')
       ) AS body
FROM media_assets a;
