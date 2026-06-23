"""Build SonarQube-style activity timeline for an issue."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from sqlmodel import Session, select

from pvs_tracker.models import ActivityLog, Issue, IssueComment, Run, User


@dataclass
class IssueActivityEvent:
    timestamp: datetime
    kind: str
    lines: list[str]
    actor_name: str | None = None
    actor_email: str | None = None


def format_activity_timestamp(dt: datetime | None) -> str:
    if not dt:
        return ""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    hour = dt.strftime("%I").lstrip("0") or "12"
    minute = dt.strftime("%M")
    ampm = dt.strftime("%p")
    return f"{dt.strftime('%B')} {dt.day}, {dt.year} at {hour}:{minute} {ampm}"


def _status_label(status: str) -> str:
    mapping = {
        "new": "NEW",
        "existing": "OPEN",
        "fixed": "FIXED",
        "ignored": "IGNORED",
    }
    return mapping.get(status, status.upper())


def build_issue_activity_timeline(
    session: Session,
    issue: Issue,
    project_id: int,
) -> list[IssueActivityEvent]:
    """Reconstruct issue history from runs sharing the same fingerprint."""
    rows = list(
        session.exec(
            select(Issue, Run)
            .join(Run, Issue.run_id == Run.id)
            .where(Run.project_id == project_id, Issue.fingerprint == issue.fingerprint)
            .order_by(Run.timestamp.asc())
        ).all()
    )

    if not rows:
        run = session.get(Run, issue.run_id)
        rows = [(issue, run)] if run else []

    events: list[IssueActivityEvent] = []
    prev_issue: Issue | None = None

    for idx, (iss, run) in enumerate(rows):
        if not run:
            continue
        ts = run.timestamp or iss.created_at
        if idx == 0:
            actor = iss.author_name or run.commit_author_name
            events.append(
                IssueActivityEvent(
                    timestamp=ts,
                    kind="created",
                    lines=["Created issue"],
                    actor_name=actor,
                    actor_email=iss.author_email or run.commit_author_email,
                )
            )
        elif prev_issue is not None:
            if iss.status != prev_issue.status:
                events.append(
                    IssueActivityEvent(
                        timestamp=ts,
                        kind="status_change",
                        lines=[
                            f"Status changed to {_status_label(iss.status)} "
                            f"(was {_status_label(prev_issue.status)})"
                        ],
                    )
                )
            prev_line = prev_issue.line or 0
            curr_line = iss.line or 0
            is_analysis = iss.file_path.startswith("__analysis__/")
            if not is_analysis and prev_line != curr_line:
                if curr_line <= 0 and prev_line > 0:
                    events.append(
                        IssueActivityEvent(
                            timestamp=ts,
                            kind="line_change",
                            lines=[f"Line number removed from issue (was {prev_line})"],
                        )
                    )
                elif prev_line > 0 and curr_line > 0:
                    events.append(
                        IssueActivityEvent(
                            timestamp=ts,
                            kind="line_change",
                            lines=[f"Line number changed from {prev_line} to {curr_line}"],
                        )
                    )
                elif prev_line <= 0 and curr_line > 0:
                    events.append(
                        IssueActivityEvent(
                            timestamp=ts,
                            kind="line_change",
                            lines=[f"Line number set to {curr_line}"],
                        )
                    )
        prev_issue = iss

    issue_ids = [row[0].id for row in rows if row[0].id is not None]
    if issue_ids:
        comments = session.exec(
            select(IssueComment, User)
            .join(User, IssueComment.user_id == User.id)
            .where(IssueComment.issue_id.in_(issue_ids))
        ).all()
        for comment, user in comments:
            events.append(
                IssueActivityEvent(
                    timestamp=comment.created_at,
                    kind="comment",
                    lines=[comment.comment],
                    actor_name=user.display_name or user.username,
                    actor_email=user.email,
                )
            )

        logs = session.exec(
            select(ActivityLog, User)
            .join(User, ActivityLog.user_id == User.id, isouter=True)
            .where(
                ActivityLog.entity_type == "issue",
                ActivityLog.entity_id.in_(issue_ids),
            )
        ).all()
        for log, user in logs:
            if log.details:
                events.append(
                    IssueActivityEvent(
                        timestamp=log.timestamp,
                        kind="audit",
                        lines=[log.details],
                        actor_name=user.display_name or user.username if user else None,
                    )
                )

    events.sort(key=lambda e: e.timestamp, reverse=True)
    return events
