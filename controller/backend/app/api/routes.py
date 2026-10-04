"""Mounts every API router under /api. All routes except /api/health honour API_TOKEN."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from app.api import agents, datasets, meta, runs
from app.security import require_token

router = APIRouter(prefix="/api")
router.include_router(meta.public)

_protected = APIRouter(dependencies=[Depends(require_token)])
_protected.include_router(meta.router)
_protected.include_router(agents.router)
_protected.include_router(datasets.router)
_protected.include_router(runs.router)
router.include_router(_protected)
