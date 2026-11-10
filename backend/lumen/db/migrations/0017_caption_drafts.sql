-- Captions the local model suggests for a portfolio's photos: kept apart until the user
-- accepts them, so a suggestion never replaces what the user wrote.

ALTER TABLE collection_items ADD COLUMN caption_draft TEXT;
