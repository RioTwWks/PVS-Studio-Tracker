"""Статусы воркеров, контейнера и готовности к zero-downtime deployment."""

from __future__ import annotations

import logging
import os
import socket
import time
from datetime import datetime, timedelta
from typing import Any, Optional

from sqlmodel import Session, func, select, text

from pvs_tracker.db import engine
from pvs_tracker.models import RestQueueJob
from pvs_tracker.rest_queue.runtime import embedded_workers_status, poll_interval, queue_mode
from pvs_tracker.rest_queue.types import ALL_SERVICES

logger = logging.getLogger(__name__)

_WORKER_STALE_MINUTES = int(os.getenv("PVS_WORKER_STALE_MINUTES", "15"))


def _status_result(
    *,
    name: str,
    status: str,
    message: str,
    url: str = "",
    latency_ms: Optional[int] = None,
    details: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    return {
        "name": name,
        "status": status,
        "url": url,
        "message": message,
        "latency_ms": latency_ms,
        "details": details or {},
    }


def _is_docker() -> bool:
    if os.getenv("PVS_IN_DOCKER", "").lower() in ("1", "true", "yes"):
        return True
    return os.path.exists("/.dockerenv")


def _database_kind() -> str:
    url = str(engine.url).lower()
    if "postgresql" in url or "postgres" in url:
        return "postgresql"
    if "sqlite" in url:
        return "sqlite"
    return "other"


def _utcnow() -> datetime:
    return datetime.utcnow()


def _iso(dt: Optional[datetime]) -> Optional[str]:
    if dt is None:
        return None
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def _queue_stats(session: Session) -> dict[str, dict[str, Any]]:
    """Сводка очереди по service: pending/processing/failed и последняя активность."""
    stats: dict[str, dict[str, Any]] = {
        service: {
            "pending": 0,
            "processing": 0,
            "failed": 0,
            "active_worker_id": None,
            "last_activity_at": None,
        }
        for service in ALL_SERVICES
    }

    rows = session.exec(
        select(
            RestQueueJob.service,
            RestQueueJob.status,
            func.count(RestQueueJob.id),
        ).group_by(RestQueueJob.service, RestQueueJob.status)
    ).all()
    for service, status, count in rows:
        if service not in stats:
            continue
        if status in stats[service]:
            stats[service][status] = int(count)

    processing_rows = session.exec(
        select(RestQueueJob.service, RestQueueJob.worker_id, RestQueueJob.started_at).where(
            RestQueueJob.status == "processing"
        )
    ).all()
    for service, worker_id, started_at in processing_rows:
        if service not in stats:
            continue
        stats[service]["active_worker_id"] = worker_id
        if started_at and (
            stats[service]["last_activity_at"] is None
            or started_at > stats[service]["last_activity_at"]
        ):
            stats[service]["last_activity_at"] = started_at

    activity_rows = session.exec(
        select(
            RestQueueJob.service,
            func.max(RestQueueJob.finished_at),
        )
        .where(RestQueueJob.status.in_(("done", "failed")))
        .group_by(RestQueueJob.service)
    ).all()
    for service, finished_at in activity_rows:
        if service not in stats or finished_at is None:
            continue
        if (
            stats[service]["last_activity_at"] is None
            or finished_at > stats[service]["last_activity_at"]
        ):
            stats[service]["last_activity_at"] = finished_at

    return stats


def _worker_status_for_service(
    service: str,
    *,
    mode: str,
    embedded: dict[str, dict[str, Any]],
    qstats: dict[str, Any],
) -> dict[str, Any]:
    pending = int(qstats.get("pending", 0))
    processing = int(qstats.get("processing", 0))
    failed = int(qstats.get("failed", 0))
    active_worker_id = qstats.get("active_worker_id")
    last_activity_at: Optional[datetime] = qstats.get("last_activity_at")
    stale_cutoff = _utcnow() - timedelta(minutes=_WORKER_STALE_MINUTES)

    details: dict[str, Any] = {
        "mode": mode,
        "pending": pending,
        "processing": processing,
        "failed": failed,
        "poll_interval_sec": poll_interval(),
        "worker_id": active_worker_id,
        "last_activity_at": _iso(last_activity_at),
    }

    if mode == "embedded":
        info = embedded.get(service)
        if not info:
            return _status_result(
                name=f"worker_{service}",
                status="error",
                message="Embedded worker not started",
                details=details,
            )
        details["worker_id"] = info.get("worker_id")
        details["thread_alive"] = info.get("alive")
        if info.get("alive"):
            msg = "Embedded thread running"
            if processing:
                msg += f" (processing job as {info.get('worker_id')})"
            elif pending:
                msg += f" ({pending} pending)"
            else:
                msg += " (idle)"
            return _status_result(
                name=f"worker_{service}",
                status="ok",
                message=msg,
                details=details,
            )
        return _status_result(
            name=f"worker_{service}",
            status="error",
            message="Embedded worker thread is not alive",
            details=details,
        )

    # external mode — отдельный процесс/контейнер
    if processing and active_worker_id:
        return _status_result(
            name=f"worker_{service}",
            status="ok",
            message=f"Processing as {active_worker_id}",
            details=details,
        )

    if last_activity_at and last_activity_at >= stale_cutoff:
        msg = f"Idle (last activity {_iso(last_activity_at)})"
        if pending:
            msg = f"Active recently, {pending} pending"
        return _status_result(
            name=f"worker_{service}",
            status="ok",
            message=msg,
            details=details,
        )

    if pending > 0:
        return _status_result(
            name=f"worker_{service}",
            status="error",
            message=f"No worker activity, {pending} job(s) pending",
            details=details,
        )

    if failed > 0:
        return _status_result(
            name=f"worker_{service}",
            status="error",
            message=f"{failed} failed job(s) in queue",
            details=details,
        )

    return _status_result(
        name=f"worker_{service}",
        status="idle",
        message="No jobs in queue (external worker not verified when idle)",
        details=details,
    )


def check_workers_health(session: Session) -> list[dict[str, Any]]:
    """Статус REST queue воркеров по каждому service."""
    mode = queue_mode()
    embedded = embedded_workers_status()
    stats = _queue_stats(session)
    return [
        _worker_status_for_service(service, mode=mode, embedded=embedded, qstats=stats[service])
        for service in ALL_SERVICES
    ]


def check_instance_health() -> dict[str, Any]:
    """Информация о текущем экземпляре uvicorn (контейнер / хост)."""
    docker = _is_docker()
    hostname = socket.gethostname()
    instance_id = os.getenv("PVS_INSTANCE_ID", "").strip() or hostname
    deployment = os.getenv("PVS_DEPLOYMENT_TOPOLOGY", "").strip() or ("docker" if docker else "standalone")

    message_parts = [f"PID {os.getpid()}", deployment]
    if docker:
        message_parts.append("Docker container")

    return _status_result(
        name="instance",
        status="ok",
        message=", ".join(message_parts),
        details={
            "instance_id": instance_id,
            "hostname": hostname,
            "pid": os.getpid(),
            "docker": docker,
            "deployment_topology": deployment,
            "container_hostname": os.getenv("HOSTNAME", hostname),
        },
    )


def check_database_deployment_health(session: Session) -> dict[str, Any]:
    """PostgreSQL обязателен для multi-instance / zero-downtime."""
    kind = _database_kind()
    started = time.monotonic()
    try:
        session.exec(text("SELECT 1")).first()
        latency_ms = int((time.monotonic() - started) * 1000)
    except Exception as e:
        logger.warning("Database deployment check failed: %s", e)
        return _status_result(
            name="database",
            status="error",
            message=f"Database unavailable: {e}",
            details={"engine": kind, "multi_instance_capable": False},
        )

    multi_instance = kind == "postgresql"
    if multi_instance:
        message = "PostgreSQL — ready for zero-downtime (multiple uvicorn instances)"
        status = "ok"
    else:
        message = f"{kind} — single-instance only (use PostgreSQL for zero-downtime)"
        status = "error" if kind == "sqlite" else "idle"

    return _status_result(
        name="database",
        status=status,
        message=message,
        latency_ms=latency_ms,
        details={"engine": kind, "multi_instance_capable": multi_instance},
    )


def check_rest_queue_mode_health() -> dict[str, Any]:
    """Режим REST queue: embedded в uvicorn или external воркеры."""
    mode = queue_mode()
    if mode == "embedded":
        message = "Embedded — worker threads inside this uvicorn process"
        status = "ok"
    elif mode == "external":
        message = "External — separate worker containers/processes required"
        status = "ok"
    else:
        message = f"Unknown REST_QUEUE_MODE: {mode}"
        status = "error"

    return _status_result(
        name="rest_queue_mode",
        status=status,
        message=message,
        details={"mode": mode, "poll_interval_sec": poll_interval()},
    )


def check_health_probes(session: Session) -> list[dict[str, Any]]:
    """Встроенные health endpoints для балансировщика / K8S."""
    live = _status_result(
        name="health_live",
        status="ok",
        message="Liveness probe OK",
        url="/health/live",
    )

    started = time.monotonic()
    try:
        session.exec(text("SELECT 1")).first()
        latency_ms = int((time.monotonic() - started) * 1000)
        ready = _status_result(
            name="health_ready",
            status="ok",
            message="Readiness probe OK (database reachable)",
            url="/health/ready",
            latency_ms=latency_ms,
        )
    except Exception as e:
        ready = _status_result(
            name="health_ready",
            status="error",
            message=f"Readiness failed: {e}",
            url="/health/ready",
        )

    return [live, ready]


def check_zero_downtime_readiness(session: Session) -> dict[str, Any]:
    """Сводная оценка готовности к rolling update без потери веб-хуков."""
    db_kind = _database_kind()
    mode = queue_mode()
    docker = _is_docker()
    multi_instance = db_kind == "postgresql"

    issues: list[str] = []
    if not multi_instance:
        issues.append("PostgreSQL required for multiple app instances")
    if mode == "embedded" and docker:
        issues.append("REST_QUEUE_MODE=external recommended in Docker Compose")

    if not issues:
        status = "ok"
        message = "Ready for zero-downtime deployment (2+ instances behind load balancer)"
    elif multi_instance and len(issues) == 1:
        status = "idle"
        message = issues[0]
    else:
        status = "error"
        message = "; ".join(issues)

    return _status_result(
        name="zero_downtime",
        status=status,
        message=message,
        details={
            "multi_instance_capable": multi_instance,
            "rest_queue_mode": mode,
            "docker": docker,
            "requirements": [
                "PostgreSQL DATABASE_URL",
                "2+ uvicorn instances or containers",
                "GET /health/live and /health/ready on load balancer",
                "REST_QUEUE_MODE=external for Docker/K8S workers",
            ],
        },
    )


def collect_runtime_health(session: Session) -> dict[str, Any]:
    """Сводка runtime: экземпляр, воркеры, deployment и zero-downtime."""
    deployment_items = [
        check_instance_health(),
        check_database_deployment_health(session),
        check_rest_queue_mode_health(),
        *check_health_probes(session),
        check_zero_downtime_readiness(session),
    ]
    return {
        "checked_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "workers": check_workers_health(session),
        "deployment": deployment_items,
    }
