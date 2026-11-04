from fastapi import APIRouter

from lumen.api.v1 import (
    ai,
    assets,
    backups,
    collections,
    cull,
    develop,
    duplicates,
    exports,
    health,
    settings,
    storage_roots,
    tags,
    tasks,
)

router = APIRouter(prefix="/api/v1")
router.include_router(health.router)
router.include_router(storage_roots.router)
router.include_router(tasks.router)
router.include_router(assets.router)
router.include_router(develop.router)
router.include_router(duplicates.router)
router.include_router(exports.router)
router.include_router(collections.router)
router.include_router(cull.router)
router.include_router(tags.router)
router.include_router(settings.router)
router.include_router(ai.router)
router.include_router(backups.router)
