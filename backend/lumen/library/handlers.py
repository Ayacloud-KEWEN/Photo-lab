from lumen.ai.pipeline import AI_DOWNLOAD_TASK, AI_INDEX_TASK, download_model, index_assets
from lumen.geo.tasks import GEO_TASK, locate_assets
from lumen.library.common import INGEST_TASK, SCAN_TASK
from lumen.library.exports import EXPORT_TASK, export_assets
from lumen.library.ingest import ingest_storage_root
from lumen.library.scan import scan_storage_root
from lumen.tasks.runner import Handler

HANDLERS: dict[str, Handler] = {
    SCAN_TASK: scan_storage_root,
    INGEST_TASK: ingest_storage_root,
    AI_DOWNLOAD_TASK: download_model,
    AI_INDEX_TASK: index_assets,
    EXPORT_TASK: export_assets,
    GEO_TASK: locate_assets,
}
