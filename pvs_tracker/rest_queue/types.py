"""REST API job queue — service names and task identifiers."""

from __future__ import annotations

from typing import Final

SERVICE_JENKINS: Final[str] = "jenkins"
SERVICE_JIRA: Final[str] = "jira"
SERVICE_TFS: Final[str] = "tfs"
SERVICE_WEBHOOK: Final[str] = "webhook"
SERVICE_SMTP: Final[str] = "smtp"

ALL_SERVICES: Final[tuple[str, ...]] = (
    SERVICE_JENKINS,
    SERVICE_JIRA,
    SERVICE_TFS,
    SERVICE_WEBHOOK,
    SERVICE_SMTP,
)

TASK_JENKINS_TRIGGER = "trigger_build"
TASK_JIRA_SYNC_RUN = "sync_run"
TASK_TFS_LATEST_CHANGESET = "latest_changeset"
TASK_TFS_CHECK_CHANGES = "check_tfvc_changes"
TASK_TFS_CHECK_MERGE = "check_tfvc_merge"
TASK_WEBHOOK_UPLOAD = "upload"
TASK_WEBHOOK_QUALITY_GATE = "quality_gate"
TASK_SMTP_API_UPLOAD = "api_upload_notify"
