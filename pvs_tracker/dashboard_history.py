"""Build dashboard trend history for platform filters."""

from __future__ import annotations

from sqlmodel import Session, select

from pvs_tracker.models import Issue, Run
from pvs_tracker.platforms import PLATFORMS, PlatformFilter, normalize_platform_filter
from pvs_tracker.run_queries import common_cross_fps


def _metrics_for_run(
    session: Session,
    run: Run,
    all_fps: set[str],
    fixed_fps: set[str],
    common_fps: set[str] | None,
) -> tuple[int, int, int, set[str], set[str]]:
    issues = session.exec(select(Issue).where(Issue.run_id == run.id)).all()
    for i in issues:
        if common_fps is not None:
            if not i.cross_platform_fp or i.cross_platform_fp not in common_fps:
                continue
        if i.status in ("new", "existing"):
            all_fps.add(i.fingerprint)
        elif i.status == "fixed":
            fixed_fps.add(i.fingerprint)

    active_count = len(all_fps - fixed_fps)
    new_count = len([
        i for i in issues
        if i.status == "new"
        and (common_fps is None or (i.cross_platform_fp and i.cross_platform_fp in common_fps))
    ])
    fixed_count = len([
        i for i in issues
        if i.status == "fixed"
        and (common_fps is None or (i.cross_platform_fp and i.cross_platform_fp in common_fps))
    ])
    return active_count, new_count, fixed_count, all_fps, fixed_fps


def build_run_history(
    session: Session,
    runs: list[Run],
    common_fps: set[str] | None = None,
) -> list[dict]:
    all_fps: set[str] = set()
    fixed_fps: set[str] = set()
    history: list[dict] = []
    for r in runs:
        active, new_c, fixed_c, all_fps, fixed_fps = _metrics_for_run(
            session, r, all_fps, fixed_fps, common_fps
        )
        history.append(
            {
                "timestamp": r.timestamp.isoformat(),
                "commit": r.commit or "—",
                "branch": r.branch or "—",
                "platform": r.target_platform or "windows",
                "total": active,
                "new": new_c,
                "fixed": fixed_c,
            }
        )
    return history


def _fetch_runs(
    session: Session,
    project_id: int,
    active_branch: str,
    target_platform: str | None,
    limit: int,
) -> list[Run]:
    q = select(Run).where(Run.project_id == project_id, Run.status == "done")
    if active_branch:
        q = q.where(Run.branch == active_branch)
    if target_platform:
        q = q.where(Run.target_platform == target_platform)
    return session.exec(q.order_by(Run.timestamp.asc()).limit(limit)).all()


def build_dashboard_histories(
    session: Session,
    project_id: int,
    active_branch: str,
    platform_filter: str,
    limit: int = 10,
) -> tuple[list[dict], dict[str, list[dict]]]:
    pf: PlatformFilter = normalize_platform_filter(platform_filter)
    history_by_platform: dict[str, list[dict]] = {}

    if pf == "all":
        for plat in PLATFORMS:
            runs = _fetch_runs(session, project_id, active_branch, plat, limit)
            if runs:
                history_by_platform[plat] = build_run_history(session, runs)
        combined = history_by_platform.get("windows") or next(
            iter(history_by_platform.values()), []
        )
        return combined, history_by_platform

    common_fps = common_cross_fps(session, project_id, active_branch) if pf == "common" else None
    target = pf if pf in PLATFORMS else "windows"
    if pf == "common":
        runs = _fetch_runs(session, project_id, active_branch, None, limit)
    else:
        runs = _fetch_runs(session, project_id, active_branch, target, limit)

    return build_run_history(session, runs, common_fps), history_by_platform
