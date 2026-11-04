-- Offline place names (ADR-023): the town, region and country of each located asset,
-- from the bundled GeoNames extract. Names are stored in each interface language
-- (falling back to the international name), so search and filters need no lookup.

CREATE TABLE media_places (
    asset_id     INTEGER PRIMARY KEY REFERENCES media_assets (id) ON DELETE CASCADE,
    place_id     INTEGER NOT NULL,                  -- GeoNames id of the town
    city         TEXT    NOT NULL,
    city_zh      TEXT    NOT NULL,
    city_fr      TEXT    NOT NULL,
    region       TEXT,
    region_zh    TEXT,
    region_fr    TEXT,
    country_code TEXT    NOT NULL,                  -- ISO 3166-1 alpha-2
    country      TEXT    NOT NULL,
    country_zh   TEXT    NOT NULL,
    country_fr   TEXT    NOT NULL,
    distance_km  REAL    NOT NULL CHECK (distance_km >= 0),
    data_version TEXT    NOT NULL,                  -- place data the names came from
    located_at   TEXT    NOT NULL,                  -- media_locations.updated_at used
    updated_at   TEXT    NOT NULL
);

CREATE INDEX idx_media_places_place ON media_places (country_code, place_id);

-- The search document gains the place names in every language (definition from 0004).
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
       ) AS body
FROM media_assets a;
