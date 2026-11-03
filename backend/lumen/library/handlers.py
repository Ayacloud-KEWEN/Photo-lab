from lumen.library.common import INGEST_TASK, SCAN_TASK
from lumen.library.ingest import ingest_storage_root
from lumen.library.scan import scan_storage_root
from lumen.tasks.runner import Handler

HANDLERS: dict[str, Handler] = {
    SCAN_TASK: scan_storage_root,
    INGEST_TASK: ingest_storage_root,
}
