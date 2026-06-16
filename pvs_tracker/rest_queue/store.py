"""Persistence layer for REST queue jobs."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta
from typing import Any, Optional

from sqlalchemy import text
from sqlmodel import Session, select

from pvs_tracker.db import engine
from pvs_tracker.models import RestQueueJob

logger = logging.getLogger(__name__)

_RETRY_BASE_SECONDS = 15


def _is_postgres() -> bool:
    return "postgresql" in str(engine.url).lower()


def enqueue_job(
    service: str,
    task: str,
    payload: dict[str, Any],
    *,
    max_attempts: int = 5,
) -> int:
    """Поставить задачу в очередь и вернуть id."""
    job = RestQueueJob(
        service=service,
        task=task,
        payload_json=json.dumps(payload, ensure_ascii=False),
        max_attempts=max_attempts,
    )
    with Session(engine) as session:
        session.add(job)
        session.commit()
        session.refresh(job)
        job_id = job.id
    logger.info("REST queue enqueued job_id=%s service=%s task=%s", job_id, service, task)
    assert job_id is not None
    return job_id


def claim_next_job(service: str, worker_id: str) -> Optional[RestQueueJob]:
    """Забрать следующую pending-задачу для сервиса (один воркер на service)."""
    now = datetime.utcnow()
    if _is_postgres():
        return _claim_postgres(service, worker_id, now)
    return _claim_sqlite(service, worker_id, now)


def _claim_postgres(service: str, worker_id: str, now: datetime) -> Optional[RestQueueJob]:
    stmt = text(
        """
        UPDATE restqueuejob
        SET status = 'processing',
            worker_id = :worker_id,
            started_at = :now,
            attempts = attempts + 1
        WHERE id = (
            SELECT id FROM restqueuejob
            WHERE service = :service
              AND status = 'pending'
              AND available_at <= :now
            ORDER BY id
            LIMIT 1
            FOR UPDATE SKIP LOCKED
        )
        RETURNING id
        """
    )
    with Session(engine) as session:
        result = session.execute(
            stmt,
            {"service": service, "worker_id": worker_id, "now": now},
        )
        row = result.first()
        if not row:
            return None
        job_id = int(row[0])
        session.commit()
        job = session.get(RestQueueJob, job_id)
        if job:
            session.expunge(job)
        return job


def _claim_sqlite(service: str, worker_id: str, now: datetime) -> Optional[RestQueueJob]:
    with Session(engine) as session:
        job = session.exec(
            select(RestQueueJob)
            .where(RestQueueJob.service == service)
            .where(RestQueueJob.status == "pending")
            .where(RestQueueJob.available_at <= now)
            .order_by(RestQueueJob.id)
            .limit(1)
        ).first()
        if not job:
            return None
        job.status = "processing"
        job.worker_id = worker_id
        job.started_at = now
        job.attempts += 1
        session.add(job)
        session.commit()
        session.refresh(job)
        session.expunge(job)
        return job


def complete_job(job_id: int, result: Optional[dict[str, Any]] = None) -> None:
    with Session(engine) as session:
        job = session.get(RestQueueJob, job_id)
        if not job:
            return
        job.status = "done"
        job.finished_at = datetime.utcnow()
        if result is not None:
            job.result_json = json.dumps(result, ensure_ascii=False)
        session.add(job)
        session.commit()


def fail_job(job_id: int, error: str, *, retry: bool) -> None:
    with Session(engine) as session:
        job = session.get(RestQueueJob, job_id)
        if not job:
            return
        job.error_message = error[:4000]
        if retry and job.attempts < job.max_attempts:
            job.status = "pending"
            delay = _RETRY_BASE_SECONDS * job.attempts
            job.available_at = datetime.utcnow() + timedelta(seconds=delay)
            job.worker_id = None
            job.started_at = None
            logger.warning(
                "REST queue retry job_id=%s service=%s attempt=%s delay=%ss",
                job_id,
                job.service,
                job.attempts,
                delay,
            )
        else:
            job.status = "failed"
            job.finished_at = datetime.utcnow()
            logger.error(
                "REST queue failed job_id=%s service=%s task=%s: %s",
                job_id,
                job.service,
                job.task,
                error,
            )
        session.add(job)
        session.commit()


def get_job(job_id: int) -> Optional[RestQueueJob]:
    with Session(engine) as session:
        job = session.get(RestQueueJob, job_id)
        if job:
            session.expunge(job)
        return job
