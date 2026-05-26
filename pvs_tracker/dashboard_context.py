"""Shared dashboard branch resolution and platform-scoped metrics."""

from __future__ import annotations

from sqlmodel import Session, select

from pvs_tracker.dashboard_history import build_dashboard_histories
from pvs_tracker.models import Project, Run
from pvs_tracker.platforms import normalize_platform_filter


def list_project_branches(project: Project, all_runs: list[Run]) -> list[str]:
    """Все известные ветки: из run-ов и сохранённая ветка проекта (git_branch)."""
    branches: list[str] = []
    for r in all_runs:
        b = (r.branch or "").strip()
        if b and b not in branches:
            branches.append(b)
    for candidate in (
        (project.git_branch or "").strip(),
        (project.analysis_branch or "").strip(),
    ):
        if candidate and candidate not in branches:
            branches.append(candidate)
    return branches


def resolve_active_branch(
    project: Project,
    all_runs: list[Run],
    branch_param: str,
) -> str:
    """Активная ветка: query ?branch= > сохранённая в проекте > main/master > первая из списка."""
    branches = list_project_branches(project, all_runs)
    explicit = (branch_param or "").strip()
    if explicit:
        return explicit
    stored = (project.git_branch or project.analysis_branch or "").strip()
    if stored:
        return stored
    if "main" in branches:
        return "main"
    if "master" in branches:
        return "master"
    if branches:
        return branches[0]
    return ""


def sync_project_branch(session: Session, project: Project, branch: str) -> None:
    """Единая ветка проекта для CI, upload и дашборда (git_branch + analysis_branch)."""
    b = (branch or "").strip()
    if not b:
        return
    if (project.git_branch or "").strip() == b and (project.analysis_branch or "").strip() == b:
        return
    project.git_branch = b
    project.analysis_branch = b
    session.add(project)
    session.commit()
    session.refresh(project)


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
