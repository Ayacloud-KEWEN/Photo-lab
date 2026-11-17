-- Photos LUMEN sent to MapWeb (Periplus): where each is on the map and which version of
-- it (cover content and edit) was sent, to show it on the wall and update it after an
-- edit. Filled when sending and by checking with MapWeb.

CREATE TABLE mapweb_photos (
    asset_id    INTEGER PRIMARY KEY REFERENCES media_assets (id) ON DELETE CASCADE,
    point_id    INTEGER NOT NULL,              -- the footprint on the map
    photo_id    INTEGER,                       -- the photo on it (NULL: not known yet)
    fingerprint TEXT,                          -- cover content sent
    recipe_hash TEXT,                          -- edit sent (NULL: none)
    sent_at     TEXT    NOT NULL
);
CREATE INDEX idx_mapweb_photos_point ON mapweb_photos (point_id);

-- Photos the automatic sending has dealt with: never sent automatically again (a photo
-- the user took off the map stays off).
CREATE TABLE mapweb_auto_done (
    asset_id INTEGER PRIMARY KEY REFERENCES media_assets (id) ON DELETE CASCADE,
    done_at  TEXT    NOT NULL
);
