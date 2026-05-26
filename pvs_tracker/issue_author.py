"""Assign commit author to issues (SonarQube-style attribution)."""

from __future__ import annotations

from sqlmodel import Session, select

from pvs_tracker.models import Issue, Run


def resolve_issue_author(
    session: Session,
    run: Run,
    status: str,
    fingerprint: str,
    prev_run: Run | None,
    prev_issue: Issue | None = None,
) -> tuple[str | None, str | None]:
    """
    Resolve author for an issue row.

    - ``new``: author of the analysis commit (run).
    - ``existing`` / ``fixed``: keep author from the previous run's issue when known.
    """
    if status == "new":
        return run.commit_author_name, run.commit_author_email

    # First analysis for the platform: issues are stored as "existing" but belong to this commit.
    if prev_run is None:
        return run.commit_author_name, run.commit_author_email

    if prev_issue is None and prev_run is not None:
        prev_issue = session.exec(
            select(Issue).where(
                Issue.run_id == prev_run.id,
                Issue.fingerprint == fingerprint,
            )
        ).first()

    if prev_issue and (prev_issue.author_name or prev_issue.author_email):
        return prev_issue.author_name, prev_issue.author_email

    return None, None
