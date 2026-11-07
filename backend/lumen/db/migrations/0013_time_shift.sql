-- Capture times corrected in LUMEN (a camera clock set wrong, or to another time zone):
-- the shift is kept so that re-reading a file's metadata applies it again (ADR-035).

ALTER TABLE media_assets ADD COLUMN time_shift_s INTEGER NOT NULL DEFAULT 0;
