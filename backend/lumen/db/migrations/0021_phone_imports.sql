-- Files copied from a phone (iPhone) by "Import from iPhone": what was already imported,
-- so the next import only copies new photos. Nothing on the phone is ever changed.

CREATE TABLE phone_imports (
    id          INTEGER PRIMARY KEY,
    serial      TEXT    NOT NULL,              -- the phone
    object_key  TEXT    NOT NULL,              -- the file's persistent id on the phone
    file_name   TEXT    NOT NULL,
    size_bytes  INTEGER NOT NULL,
    path        TEXT    NOT NULL,              -- where it was copied ('' : already in the library)
    imported_at TEXT    NOT NULL,
    UNIQUE (serial, object_key)
);
CREATE INDEX idx_phone_imports_name ON phone_imports (serial, file_name, size_bytes);
