"""Public API for enqueueing REST/SMTP jobs."""

from __future__ import annotations

from typing import Any, Optional

from pvs_tracker.rest_queue.store import enqueue_job
from pvs_tracker.rest_queue.types import (
    SERVICE_JENKINS,
    SERVICE_JIRA,
    SERVICE_SMTP,
    SERVICE_TFS,
    SERVICE_WEBHOOK,
    TASK_JENKINS_TRIGGER,
    TASK_JIRA_SYNC_RUN,
    TASK_SMTP_API_UPLOAD,
    TASK_TFS_CHECK_CHANGES,
    TASK_TFS_CHECK_MERGE,
    TASK_TFS_LATEST_CHANGESET,
    TASK_WEBHOOK_QUALITY_GATE,
    TASK_WEBHOOK_UPLOAD,
)


def enqueue_jenkins_trigger(
    project_id: int,
    commit_id: str,
    first_scan: str | bool,
    linux: bool,
    modified_files: list[str],
    *,
    update_changeset: bool = False,
    changeset: str = "",
) -> int:
    if isinstance(first_scan, bool):
        first_scan_val = "YES" if first_scan else "NO"
    else:
        first_scan_val = str(first_scan)
    return enqueue_job(
        SERVICE_JENKINS,
        TASK_JENKINS_TRIGGER,
        {
            "project_id": project_id,
            "commit_id": commit_id,
            "first_scan": first_scan_val,
            "linux": linux,
            "modified_files": modified_files,
            "update_changeset": update_changeset,
            "changeset": changeset,
        },
    )


def enqueue_jira_sync(project_id: int, run_id: int) -> int:
    return enqueue_job(
        SERVICE_JIRA,
        TASK_JIRA_SYNC_RUN,
        {"project_id": project_id, "run_id": run_id},
    )


def enqueue_webhook_upload(project_id: int, run_id: int, issue_count: int) -> int:
    return enqueue_job(
        SERVICE_WEBHOOK,
        TASK_WEBHOOK_UPLOAD,
        {"project_id": project_id, "run_id": run_id, "issue_count": issue_count},
    )


def enqueue_webhook_quality_gate(
    project_id: int,
    run_id: int,
    quality_gate_result: dict[str, Any],
) -> int:
    return enqueue_job(
        SERVICE_WEBHOOK,
        TASK_WEBHOOK_QUALITY_GATE,
        {
            "project_id": project_id,
            "run_id": run_id,
            "quality_gate_result": quality_gate_result,
        },
    )


def enqueue_smtp_api_upload_notify(
    project_id: int,
    run_id: int,
    quality_gate_result: dict[str, Any],
) -> int:
    return enqueue_job(
        SERVICE_SMTP,
        TASK_SMTP_API_UPLOAD,
        {
            "project_id": project_id,
            "run_id": run_id,
            "quality_gate_result": quality_gate_result,
        },
    )


def enqueue_tfs_latest_changeset(project_id: int) -> int:
    return enqueue_job(
        SERVICE_TFS,
        TASK_TFS_LATEST_CHANGESET,
        {"project_id": project_id},
    )


def enqueue_tfs_check_changes(
    project_id: int,
    from_changeset: str,
    to_changeset: str,
) -> int:
    return enqueue_job(
        SERVICE_TFS,
        TASK_TFS_CHECK_CHANGES,
        {
            "project_id": project_id,
            "from_changeset": from_changeset,
            "to_changeset": to_changeset,
        },
    )


def enqueue_tfs_check_merge(changeset_id: int) -> int:
    return enqueue_job(
        SERVICE_TFS,
        TASK_TFS_CHECK_MERGE,
        {"changeset_id": changeset_id},
    )
