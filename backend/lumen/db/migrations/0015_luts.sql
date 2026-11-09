-- Imported 3D LUTs (ADR-039). The .cube file is copied to the data folder as
-- luts/<id>.cube, <id> being the start of its SHA-256, so photos graded with it keep
-- their look whatever happens to the original file.

CREATE TABLE luts (
    id          TEXT    PRIMARY KEY CHECK (length(id) = 16),
    name        TEXT    NOT NULL,
    pack        TEXT,                          -- folder it came from, for grouping
    color_space TEXT    NOT NULL DEFAULT 'rec709' CHECK (color_space IN ('rec709', 'p3')),
    kind        TEXT    NOT NULL DEFAULT 'look' CHECK (kind IN ('look', 'log', 'transform')),
    size        INTEGER NOT NULL,              -- grid points per axis
    hidden      INTEGER NOT NULL DEFAULT 0 CHECK (hidden IN (0, 1)),
    source_path TEXT,                          -- where it was imported from
    created_at  TEXT    NOT NULL
);

CREATE INDEX idx_luts_name ON luts (kind, hidden, name);
