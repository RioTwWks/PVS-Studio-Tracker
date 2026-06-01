"""Helpers for selecting runs and cross-platform issue sets."""

from __future__ import annotations

from sqlmodel import Session, select

from pvs_tracker.models import Issue, Run
from pvs_tracker.platforms import PLATFORMS, TargetPlatform


def _branch_filter(query, branch: str):
    """Apply branch filter when branch is non-empty."""
    if branch:
        return query.where(Run.branch == branch)
    return query


def get_latest_run(
    session: Session,
    project_id: int,
    branch: str = "",
    platform: str | None = None,
) -> Run | None:
    """Latest successful run, optionally filtered by branch and target_platform."""
    query = select(Run).where(Run.project_id == project_id, Run.status == "done")
    query = _branch_filter(query, branch)
    if platform:
        query = query.where(Run.target_platform == platform)
    return session.exec(query.order_by(Run.timestamp.desc()).limit(1)).first()


def get_analysis_set_runs(
    session: Session,
    project_id: int,
    branch: str = "",
) -> dict[str, Run]:
    """Latest done run per target platform for the project (and branch)."""
    result: dict[str, Run] = {}
    for plat in PLATFORMS:
        run = get_latest_run(session, project_id, branch, plat)
        if run:
            result[plat] = run
    return result


def common_cross_fps_for_runs(
    session: Session,
    runs: dict[str, Run],
) -> set[str]:
    """Intersection of cross_platform_fp among active issues in the given runs."""
    if len(runs) < 2:
        return set()

    fps_per_platform: list[set[str]] = []
    for run in runs.values():
        issues = session.exec(
            select(Issue).where(
                Issue.run_id == run.id,
                Issue.status.in_(["new", "existing"]),
            )
        ).all()
        platform_fps = {i.cross_platform_fp for i in issues if i.cross_platform_fp}
        if not platform_fps:
            return set()
        fps_per_platform.append(platform_fps)

    intersection = fps_per_platform[0]
    for s in fps_per_platform[1:]:
        intersection = intersection & s
    return intersection


def common_cross_fps(
    session: Session,
    project_id: int,
    branch: str = "",
) -> set[str]:
    """
    Intersection of cross_platform_fp among active issues in latest run per platform.
    Only platforms with at least one run participate in the intersection.
    """
    return common_cross_fps_for_runs(session, get_analysis_set_runs(session, project_id, branch))
