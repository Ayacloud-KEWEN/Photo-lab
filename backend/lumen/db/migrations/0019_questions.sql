-- Questions asked to the library in plain language (ADR: answered by the local model
-- from what the library holds). The plan is how the question was understood; the answer
-- cites photos by number among asset_ids.

CREATE TABLE library_questions (
    id         INTEGER PRIMARY KEY,
    question   TEXT    NOT NULL,
    language   TEXT    NOT NULL,
    status     TEXT    NOT NULL DEFAULT 'pending'
               CHECK (status IN ('pending', 'done', 'failed')),
    task_id    INTEGER,
    plan       TEXT    CHECK (plan IS NULL OR json_valid(plan)),
    stats      TEXT    CHECK (stats IS NULL OR json_valid(stats)),
    answer     TEXT,
    asset_ids  TEXT    NOT NULL DEFAULT '[]' CHECK (json_valid(asset_ids)),
    error      TEXT,
    created_at TEXT    NOT NULL
);
CREATE INDEX idx_library_questions_created ON library_questions (created_at);
