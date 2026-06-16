"""Task handlers — выполнение исходящих REST/SMTP вызовов."""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, Callable

from sqlmodel import Session

from pvs_tracker.db import engine
from pvs_tracker.jenkins_service import trigger_jenkins_build
from pvs_tracker.jira_sync import sync_run_issues_to_jira
from pvs_tracker.models import Project, RestQueueJob
from pvs_tracker.notifications import _notify_api_upload_subscribers_sync
from pvs_tracker.project_ci import set_analysis_queued, update_last_changeset
from pvs_tracker.repository_service import (
    check_tfvc_changes,
    check_tfvc_merge,
    get_latest_changeset_tfvc,
)
from pvs_tracker.rest_queue.types import (
    TASK_JENKINS_TRIGGER,
    TASK_JIRA_SYNC_RUN,
    TASK_SMTP_API_UPLOAD,
    TASK_TFS_CHECK_CHANGES,
    TASK_TFS_CHECK_MERGE,
    TASK_TFS_LATEST_CHANGESET,
    TASK_WEBHOOK_QUALITY_GATE,
    TASK_WEBHOOK_UPLOAD,
)
from pvs_tracker.webhooks import trigger_quality_gate_webhook, trigger_upload_webhook

logger = logging.getLogger(__name__)

Handler = Callable[[dict[str, Any]], dict[str, Any]]


def _load_payload(job: RestQueueJob) -> dict[str, Any]:
    return json.loads(job.payload_json)


def _handle_jenkins_trigger(payload: dict[str, Any]) -> dict[str, Any]:
    with Session(engine) as session:
        project = session.get(Project, payload["project_id"])
        if not project:
            raise ValueError(f"Project {payload['project_id']} not found")
        result = trigger_jenkins_build(
            project,
            payload.get("commit_id", ""),
            payload.get("first_scan", "NO"),
            payload.get("linux", False),
            payload.get("modified_files") or [],
        )
        if not result:
            raise RuntimeError("Jenkins trigger returned no result")
        set_analysis_queued(session, project, result)
        if payload.get("update_changeset") and payload.get("changeset"):
            update_last_changeset(session, project, str(payload["changeset"]))
        return {
            "build_number": result.build_number,
            "queue_id": result.queue_id,
            "console_url": result.console_url,
            "display_label": result.display_label,
        }


def _handle_jira_sync_run(payload: dict[str, Any]) -> dict[str, Any]:
    with Session(engine) as session:
        sync_run_issues_to_jira(session, int(payload["project_id"]), int(payload["run_id"]))
    return {"ok": True}


def _handle_tfs_latest_changeset(payload: dict[str, Any]) -> dict[str, Any]:
    with Session(engine) as session:
        project = session.get(Project, payload["project_id"])
        if not project:
            raise ValueError(f"Project {payload['project_id']} not found")
        changeset = get_latest_changeset_tfvc(project)
        if not changeset:
            raise RuntimeError("TFVC latest changeset not found")
        return {"changeset": changeset}


def _handle_tfs_check_changes(payload: dict[str, Any]) -> dict[str, Any]:
    with Session(engine) as session:
        project = session.get(Project, payload["project_id"])
        if not project:
            raise ValueError(f"Project {payload['project_id']} not found")
        files, first_scan, comp, cmake = check_tfvc_changes(
            project,
            payload.get("from_changeset", ""),
            payload.get("to_changeset", ""),
        )
        return {
            "modified_files": files,
            "first_scan": first_scan,
            "composition_changed": comp,
            "cmake_changed": cmake,
        }


def _handle_tfs_check_merge(payload: dict[str, Any]) -> dict[str, Any]:
    path = check_tfvc_merge(int(payload["changeset_id"]))
    return {"merge_path": path}


def _run_async(coro: Any) -> Any:
    return asyncio.run(coro)


def _handle_webhook_upload(payload: dict[str, Any]) -> dict[str, Any]:
    with Session(engine) as session:
        ok = _run_async(
            trigger_upload_webhook(
                session,
                int(payload["project_id"]),
                int(payload["run_id"]),
                int(payload.get("issue_count", 0)),
            )
        )
    return {"sent": ok}


def _handle_webhook_quality_gate(payload: dict[str, Any]) -> dict[str, Any]:
    with Session(engine) as session:
        ok = _run_async(
            trigger_quality_gate_webhook(
                session,
                int(payload["project_id"]),
                int(payload["run_id"]),
                payload.get("quality_gate_result") or {},
            )
        )
    return {"sent": ok}


def _handle_smtp_notify(payload: dict[str, Any]) -> dict[str, Any]:
    _notify_api_upload_subscribers_sync(
        int(payload["project_id"]),
        int(payload["run_id"]),
        payload.get("quality_gate_result") or {},
    )
    return {"ok": True}


HANDLERS: dict[tuple[str, str], Handler] = {
    ("jenkins", TASK_JENKINS_TRIGGER): _handle_jenkins_trigger,
    ("jira", TASK_JIRA_SYNC_RUN): _handle_jira_sync_run,
    ("tfs", TASK_TFS_LATEST_CHANGESET): _handle_tfs_latest_changeset,
    ("tfs", TASK_TFS_CHECK_CHANGES): _handle_tfs_check_changes,
    ("tfs", TASK_TFS_CHECK_MERGE): _handle_tfs_check_merge,
    ("webhook", TASK_WEBHOOK_UPLOAD): _handle_webhook_upload,
    ("webhook", TASK_WEBHOOK_QUALITY_GATE): _handle_webhook_quality_gate,
    ("smtp", TASK_SMTP_API_UPLOAD): _handle_smtp_notify,
}


def execute_job(job: RestQueueJob) -> None:
    """Выполнить задачу (вызывается воркером)."""
    from pvs_tracker.rest_queue.store import complete_job, fail_job

    handler = HANDLERS.get((job.service, job.task))
    if not handler:
        fail_job(job.id, f"Unknown handler {job.service}/{job.task}", retry=False)
        return
    try:
        payload = _load_payload(job)
        result = handler(payload)
        complete_job(job.id, result)
    except Exception as e:
        logger.exception("REST queue handler error job_id=%s", job.id)
        fail_job(job.id, str(e), retry=True)
