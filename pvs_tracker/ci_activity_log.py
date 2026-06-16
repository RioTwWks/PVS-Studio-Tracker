"""Аудит нажатий кнопок управления анализом (CI panel)."""

from __future__ import annotations

from typing import Any, Optional

from fastapi import Request
from sqlmodel import Session, select

from pvs_tracker.admin_utils import get_client_info
from pvs_tracker.api import log_activity
from pvs_tracker.auth_service import get_current_user
from pvs_tracker.models import ActivityLog, Project, User

CI_ACTIONS: tuple[str, ...] = (
    "ci_enable",
    "ci_disable",
    "ci_jira_on",
    "ci_jira_pause",
    "ci_trigger_analysis",
)


def _resolve_user_id(request: Request) -> Optional[int]:
    user = get_current_user(request, None)
    return user.id if user else None


def _client_audit_suffix(request: Request) -> str:
    info = get_client_info(request)
    return f"IP: {info['ip']}, host: {info['hostname']}"


def log_ci_action(
    session: Session,
    request: Request,
    project: Project,
    action: str,
    details: Optional[str] = None,
) -> None:
    """Записать действие пользователя на панели управления анализом."""
    user_id = _resolve_user_id(request)
    full_details = (details or "").strip()
    if not user_id:
        client_info = _client_audit_suffix(request)
        full_details = f"{full_details} ({client_info})" if full_details else client_info
    log_activity(
        session,
        action,
        "project",
        project.id,
        project.id,
        user_id,
        full_details or None,
    )


def fetch_ci_activity_logs(
    session: Session,
    project_id: int,
    *,
    limit: int = 20,
) -> list[dict[str, Any]]:
    """Последние действия на панели CI для отображения в UI."""
    rows = session.exec(
        select(ActivityLog, User)
        .join(User, ActivityLog.user_id == User.id, isouter=True)
        .where(ActivityLog.project_id == project_id)
        .where(ActivityLog.action.in_(CI_ACTIONS))
        .order_by(ActivityLog.timestamp.desc())
        .limit(limit)
    ).all()
    entries: list[dict[str, Any]] = []
    for log, user in rows:
        actor = None
        if user:
            actor = user.display_name or user.username
        entries.append(
            {
                "action": log.action,
                "timestamp": log.timestamp,
                "details": log.details,
                "actor": actor,
            }
        )
    return entries
