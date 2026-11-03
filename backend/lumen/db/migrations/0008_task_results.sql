-- A finished task's outcome (JSON), e.g. what an export wrote and skipped (ADR-020).
ALTER TABLE tasks ADD COLUMN result TEXT CHECK (result IS NULL OR json_valid(result));
