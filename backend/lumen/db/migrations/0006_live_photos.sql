-- Live Photos: the still and its motion clip (.MOV) become one asset (ADR-017).

-- Apple's pairing id, written in both files (MakerNotes / QuickTime Keys).
ALTER TABLE media_metadata ADD COLUMN content_identifier TEXT;
CREATE INDEX idx_media_metadata_content_identifier ON media_metadata (content_identifier)
    WHERE content_identifier IS NOT NULL;

-- Re-read the metadata of files that may be Live Photo halves, so that existing ones get
-- paired. Fingerprints and renditions are kept, so this is fast.
UPDATE media_files
SET ingest_state = 'pending', ingest_attempts = 0, ingest_error = NULL
WHERE status = 'present' AND ingest_state = 'done'
  AND extension IN ('mov', 'heic', 'heif', 'jpg', 'jpeg');

INSERT INTO tasks (kind, status, storage_root_id, payload, created_at, updated_at)
SELECT 'ingest_storage_root', 'pending', r.id, '{"reason": "migration 0006"}',
       strftime('%Y-%m-%dT%H:%M:%fZ', 'now'), strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
FROM storage_roots r
WHERE EXISTS (SELECT 1 FROM media_files f
              WHERE f.storage_root_id = r.id AND f.ingest_state = 'pending')
  AND NOT EXISTS (SELECT 1 FROM tasks t
                  WHERE t.storage_root_id = r.id AND t.kind = 'ingest_storage_root'
                    AND t.status IN ('pending', 'running'));
