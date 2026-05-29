"""Liveness/readiness probe. Intentionally unauthenticated and origin-open."""

from __future__ import annotations

from fastapi import APIRouter

from app.core.config import get_settings
from app.utils.timeutils import now_utc

router = APIRouter(tags=["system"])


@router.get("/health", summary="Service health probe")
async def health() -> dict[str, object]:
    settings = get_settings()
    return {
        "status": "ok",
        "environment": settings.environment,
        "time": now_utc().isoformat(),
    }
