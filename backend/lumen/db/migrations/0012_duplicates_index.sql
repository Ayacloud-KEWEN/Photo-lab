-- Finding duplicate copies groups present files by fingerprint; this partial index holds
-- exactly the rows (and columns) needed, so it is read without visiting the table.

CREATE INDEX idx_media_files_duplicates ON media_files (fingerprint, asset_id)
    WHERE fingerprint IS NOT NULL AND asset_id IS NOT NULL AND status = 'present'
      AND file_role != 'sidecar';
