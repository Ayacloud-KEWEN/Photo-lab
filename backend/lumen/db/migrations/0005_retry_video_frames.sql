-- Retry videos whose frame grab failed, now fixed in lumen.media.thumbnails:
--   * "ffmpeg timed out": ffmpeg inherited the backend's stdin pipe and hung on Windows;
--   * "ffmpeg could not extract a frame": among others, reserved colour codes that
--     ffmpeg's filter graph rejects. Truly broken files simply fail again.
-- Their fingerprints are kept, so only the failed work is redone.
UPDATE media_files
SET ingest_state = 'pending', ingest_attempts = 0, ingest_error = NULL
WHERE (ingest_error = 'ffmpeg timed out' OR ingest_error LIKE 'ffmpeg could not extract a frame:%')
  AND ingest_state IN ('pending', 'error');

INSERT INTO tasks (kind, status, storage_root_id, payload, created_at, updated_at)
SELECT 'ingest_storage_root', 'pending', r.id, '{"reason": "migration 0005"}',
       strftime('%Y-%m-%dT%H:%M:%fZ', 'now'), strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
FROM storage_roots r
WHERE EXISTS (SELECT 1 FROM media_files f
              WHERE f.storage_root_id = r.id AND f.ingest_state = 'pending')
  AND NOT EXISTS (SELECT 1 FROM tasks t
                  WHERE t.storage_root_id = r.id AND t.kind = 'ingest_storage_root'
                    AND t.status IN ('pending', 'running'));
