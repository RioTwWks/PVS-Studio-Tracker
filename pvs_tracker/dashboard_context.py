"""Shared dashboard branch resolution and platform-scoped metrics."""

from __future__ import annotations

from sqlmodel import Session, select

from pvs_tracker.dashboard_history import build_dashboard_histories
from pvs_tracker.models import Project, Run
from pvs_tracker.platforms import normalize_platform_filter


def list_project_branches(project: Project, all_runs: list[Run]) -> list[str]:
    branches: list[str] = []
    for r in all_runs:
        b = (r.branch or "").strip()
        if b and b not in branches:
            branches.append(b)
    default_branch = (project.git_branch or "").strip()
    if default_branch and default_branch not in branches:
        branches.append(default_branch)
    return branches


def resolve_active_branch(
    project: Project,
    all_runs: list[Run],
    branch_param: str,
) -> str:
    branches = list_project_branches(project, all_runs)
    if branch_param:
        return branch_param
    if "main" in branches:
        return "main"
    if "master" in branches:
        return "master"
    if branches:
        return branches[0]
    return ""


def build_platform_metrics(
    session: Session,
    project_id: int,
    branch: str,
    platform_filter: str,
) -> dict:
    """History and latest KPIs for a platform filter (JSON-friendly)."""
    pf = normalize_platform_filter(platform_filter)
    history, history_by_platform = build_dashboard_histories(
        session, project_id, branch, pf
    )
    latest = history[-1] if history else None
    return {
        "platform_filter": pf,
        "history": history,
        "history_by_platform": history_by_platform,
        "latest": latest,
        "issues_total": latest["total"] if latest else 0,
    }
