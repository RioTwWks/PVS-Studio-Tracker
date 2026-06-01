"""Sync new/fixed PVS issues to Jira after report upload."""

from __future__ import annotations

import logging
from typing import Optional

from sqlmodel import Session, select

from pvs_tracker.jira_service import get_jira_service
from pvs_tracker.models import Issue, Project, Run

logger = logging.getLogger(__name__)


def _issue_description(issue: Issue, project: Project, run: Run) -> str:
    commit_author = run.commit_author_name or "—"
    commit_author_email = run.commit_author_email or "—"
    issue_author = issue.author_name or "—"
    issue_author_email = issue.author_email or "—"
    lines = [
        f"PVS-Studio [{issue.rule_code}] {issue.severity}",
        f"File: {issue.file_path}:{issue.line}",
        f"Message: {issue.message}",
        f"Fingerprint: {issue.fingerprint}",
        f"Project: {project.name}",
        f"Issue author: {issue_author} <{issue_author_email}>",
        f"Commit: {run.commit or 'n/a'} ({commit_author} <{commit_author_email}>)",
        f"Branch: {run.branch or 'n/a'}",
        f"Run: {run.id}",
    ]
    return "\n".join(lines)


def sync_run_issues_to_jira(session: Session, project_id: int, run_id: int) -> None:
    project = session.get(Project, project_id)
    run = session.get(Run, run_id)
    if not project or not run:
        return
    if project.disable_jira or not project.jira_project:
        logger.debug("Jira sync skipped for project %s", project.name)
        return

    jira = get_jira_service()
    if not jira.is_connected():
        return

    jira_key = jira.get_project_key(project.jira_project)
    if not jira_key:
        logger.warning("Jira project not found: %s", project.jira_project)
        return

    run_assignee = jira.resolve_assignee_from_run(run)

    new_issues = session.exec(
        select(Issue).where(Issue.run_id == run_id, Issue.status == "new")
    ).all()
    for issue in new_issues:
        if issue.jira_issue_key:
            continue
        existing = jira.find_issue_by_fingerprint(jira_key, issue.fingerprint)
        if existing:
            issue.jira_issue_key = existing
            session.add(issue)
            continue
        summary = f"[PVS] {issue.rule_code}: {issue.message[:120]}"
        assignee = jira.resolve_assignee_from_issue(issue, run) or run_assignee
        key = jira.create_bug(
            jira_key,
            summary,
            _issue_description(issue, project, run),
            issue.fingerprint,
            assignee=assignee,
            version=(run.release_version or project.release_version or None),
        )
        if key:
            issue.jira_issue_key = key
            session.add(issue)

    fixed_issues = session.exec(
        select(Issue).where(Issue.run_id == run_id, Issue.status == "fixed")
    ).all()
    for issue in fixed_issues:
        jira_key_issue = issue.jira_issue_key
        if not jira_key_issue and issue.fingerprint:
            jira_key_issue = jira.find_issue_by_fingerprint(jira_key, issue.fingerprint)
        if jira_key_issue:
            jira.add_comment(
                jira_key_issue,
                f"Fixed in PVS run {run_id} (fingerprint {issue.fingerprint})",
            )

    session.commit()
    logger.info(
        "Jira sync done for project=%s run=%s new=%s fixed=%s",
        project.name,
        run_id,
        len(new_issues),
        len(fixed_issues),
    )


def schedule_jira_sync(project_id: int, run_id: int) -> None:
    import asyncio

    from pvs_tracker.db import engine

    async def _run() -> None:
        with Session(engine) as session:
            try:
                sync_run_issues_to_jira(session, project_id, run_id)
            except Exception as e:
                logger.error("Jira sync background error: %s", e, exc_info=True)

    try:
        loop = asyncio.get_running_loop()
        loop.create_task(_run())
    except RuntimeError:
        with Session(engine) as session:
            sync_run_issues_to_jira(session, project_id, run_id)
