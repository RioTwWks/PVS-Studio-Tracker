"""Liveness/readiness probes for load balancers and orchestrators."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from sqlmodel import Session, text

from pvs_tracker.db import get_session

logger = logging.getLogger(__name__)

router = APIRouter(tags=["health"])


@router.get("/health/live")
def liveness() -> dict[str, str]:
    """Процесс uvicorn отвечает — используется liveness probe."""
    return {"status": "ok"}


@router.get("/health/ready")
def readiness(session: Session = Depends(get_session)) -> JSONResponse:
    """БД доступна — используется readiness probe перед маршрутизацией трафика."""
    try:
        session.exec(text("SELECT 1")).first()
        return JSONResponse({"status": "ok", "database": "ok"})
    except Exception as e:
        logger.warning("Readiness check failed: %s", e)
        return JSONResponse(
            {"status": "unavailable", "database": "error"},
            status_code=503,
        )
