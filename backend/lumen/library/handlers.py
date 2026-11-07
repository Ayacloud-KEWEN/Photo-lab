from lumen.ai.pipeline import AI_DOWNLOAD_TASK, AI_INDEX_TASK, download_model, index_assets
from lumen.geo.tasks import GEO_TASK, locate_assets
from lumen.library.common import INGEST_TASK, SCAN_TASK
from lumen.library.exports import EXPORT_TASK, export_assets
from lumen.library.ingest import ingest_storage_root
from lumen.library.live import REPAIR_TASK as LIVE_REPAIR_TASK
from lumen.library.live import repair_task as pair_live_photos
from lumen.library.quality import QUALITY_TASK, score_assets
from lumen.library.scan import scan_storage_root
from lumen.services.backups import BACKUP_TASK, backup_task
from lumen.services.cache import MOVE_CACHE_TASK, move_cache
from lumen.services.duplicates import MERGE_ALL_TASK, merge_all_task
from lumen.services.mapweb import SEND_TASK as MAPWEB_SEND_TASK
from lumen.services.mapweb import send_task as mapweb_send
from lumen.tasks.runner import Handler

HANDLERS: dict[str, Handler] = {
    SCAN_TASK: scan_storage_root,
    INGEST_TASK: ingest_storage_root,
    AI_DOWNLOAD_TASK: download_model,
    AI_INDEX_TASK: index_assets,
    EXPORT_TASK: export_assets,
    GEO_TASK: locate_assets,
    BACKUP_TASK: backup_task,
    QUALITY_TASK: score_assets,
    MERGE_ALL_TASK: merge_all_task,
    MOVE_CACHE_TASK: move_cache,
    MAPWEB_SEND_TASK: mapweb_send,
    LIVE_REPAIR_TASK: pair_live_photos,
}
