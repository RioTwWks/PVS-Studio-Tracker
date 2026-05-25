"""Email notifications for API report uploads."""

from __future__ import annotations

import asyncio
import logging
import os
import smtplib
from email.message import EmailMessage
from typing import Any, Optional

from sqlmodel import Session, select

from pvs_tracker.auth_service import can_access_project
from pvs_tracker.db import engine
from pvs_tracker.models import Project, Run, User, UserProjectNotification

logger = logging.getLogger(__name__)

SMTP_HOST = os.getenv("SMTP_HOST", "")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_USER = os.getenv("SMTP_USER", "")
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD", "")
SMTP_FROM = os.getenv("SMTP_FROM", "")
SMTP_USE_TLS = os.getenv("SMTP_USE_TLS", "true").lower() in ("1", "true", "yes")
APP_BASE_URL = os.getenv("APP_BASE_URL", "").rstrip("/")


def send_email(to: str, subject: str, body: str) -> bool:
    """Send a plain-text email via SMTP. Returns False if SMTP is not configured."""
    if not SMTP_HOST:
        logger.warning("SMTP_HOST not configured; skipping email to %s", to)
        return False
    if not to.strip():
        return False

    from_addr = SMTP_FROM or SMTP_USER or "noreply@pvs-tracker"
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = from_addr
    msg["To"] = to
    msg.set_content(body)

    try:
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=30) as server:
            if SMTP_USE_TLS:
                server.starttls()
            if SMTP_USER and SMTP_PASSWORD:
                server.login(SMTP_USER, SMTP_PASSWORD)
            server.send_message(msg)
        logger.info("Notification email sent to %s", to)
        return True
    except Exception:
        logger.exception("Failed to send email to %s", to)
        return False


def build_upload_notification_email(
    project: Project,
    run: Run,
    quality_gate_result: dict[str, Any],
) -> tuple[str, str]:
    """Build subject and body for an API upload notification."""
    qg_status = quality_gate_result.get("status", "unknown")
    dashboard_url = ""
    if APP_BASE_URL and project.id is not None:
        dashboard_url = f"{APP_BASE_URL}/ui/projects/{project.id}/dashboard"

    subject = f"[PVS-Tracker] Report uploaded: {project.name}"
    lines = [
        f"Project: {project.name}",
        f"Run ID: {run.id}",
        f"Branch: {run.branch or '-'}",
        f"Commit: {run.commit or '-'}",
        f"Total issues: {run.total_issues}",
        f"New: {run.new_issues}",
        f"Fixed: {run.fixed_issues}",
        f"Quality gate: {qg_status}",
    ]
    if dashboard_url:
        lines.append(f"Dashboard: {dashboard_url}")
    return subject, "\n".join(lines)


def _notify_api_upload_subscribers_sync(
    project_id: int,
    run_id: int,
    quality_gate_result: dict[str, Any],
) -> None:
    """Load subscribers and send emails (sync, for executor)."""
    with Session(engine) as session:
        project = session.get(Project, project_id)
        run = session.get(Run, run_id)
        if not project or not run:
            return

        subscriptions = session.exec(
            select(UserProjectNotification, User)
            .join(User, UserProjectNotification.user_id == User.id)
            .where(
                UserProjectNotification.project_id == project_id,
                User.notify_api_uploads == True,  # noqa: E712
            )
        ).all()

        subject, body = build_upload_notification_email(project, run, quality_gate_result)
        sent_to: set[str] = set()

        for _sub, user in subscriptions:
            if not user.email or not user.is_active:
                continue
            if not can_access_project(user, project_id):
                continue
            email = user.email.strip()
            if not email or email in sent_to:
                continue
            sent_to.add(email)
            send_email(email, subject, body)


async def notify_api_upload_subscribers(
    project_id: int,
    run_id: int,
    quality_gate_result: dict[str, Any],
) -> None:
    """Notify subscribed users about a successful API upload (non-blocking)."""
    loop = asyncio.get_event_loop()
    await loop.run_in_executor(
        None,
        _notify_api_upload_subscribers_sync,
        project_id,
        run_id,
        quality_gate_result,
    )


async def schedule_api_upload_notifications(
    project_id: int,
    run_id: int,
    quality_gate_result: dict[str, Any],
) -> None:
    """Background task entry point for upload handlers."""
    try:
        await notify_api_upload_subscribers(project_id, run_id, quality_gate_result)
    except Exception:
        logger.exception(
            "API upload notification failed for project_id=%s run_id=%s",
            project_id,
            run_id,
        )
