from fastapi import APIRouter

from lumen.api.v1 import assets, health, storage_roots, tasks

router = APIRouter(prefix="/api/v1")
router.include_router(health.router)
router.include_router(storage_roots.router)
router.include_router(tasks.router)
router.include_router(assets.router)
