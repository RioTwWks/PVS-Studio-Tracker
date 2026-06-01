"""Build dashboard trend history for platform filters."""

from __future__ import annotations

from sqlmodel import Session, select

from pvs_tracker.models import Issue, Run
from pvs_tracker.platforms import PLATFORMS, PlatformFilter, normalize_platform_filter
from pvs_tracker.run_queries import common_cross_fps_for_runs


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
                "release_version": r.release_version or "",
                "platform": r.target_platform or "windows",
                "total": active,
                "new": new_c,
                "fixed": fixed_c,
            }
        )
    return history


def _sum_history_points(points: list[dict]) -> dict:
    """Merge per-platform history points into one All OS snapshot."""
    anchor = max(points, key=lambda p: p["timestamp"])
    version = anchor.get("release_version") or ""
    return {
        "timestamp": anchor["timestamp"],
        "commit": anchor["commit"],
        "branch": anchor["branch"],
        "release_version": version,
        "platform": "all",
        "total": sum(p["total"] for p in points),
        "new": sum(p["new"] for p in points),
        "fixed": sum(p["fixed"] for p in points),
    }


def _wave_runs(
    runs_by_platform: dict[str, list[Run]],
    wave_idx: int,
) -> dict[str, Run]:
    """wave_idx=1 is the latest run per platform, 2 is second-latest, etc."""
    wave: dict[str, Run] = {}
    for plat, runs in runs_by_platform.items():
        if len(runs) >= wave_idx:
            wave[plat] = runs[-wave_idx]
    return wave


def _metrics_for_common_wave(
    session: Session,
    wave_runs: dict[str, Run],
    all_cfp: set[str],
    fixed_cfp: set[str],
) -> tuple[int, int, int]:
    """Cumulative Common metrics for one cross-platform analysis wave."""
    wave_common = common_cross_fps_for_runs(session, wave_runs)
    new_fps: set[str] = set()
    fixed_fps: set[str] = set()
    for run in wave_runs.values():
        issues = session.exec(select(Issue).where(Issue.run_id == run.id)).all()
        for issue in issues:
            cfp = issue.cross_platform_fp
            if not cfp or cfp not in wave_common:
                continue
            if issue.status in ("new", "existing"):
                all_cfp.add(cfp)
            elif issue.status == "fixed":
                fixed_cfp.add(cfp)
            if issue.status == "new":
                new_fps.add(cfp)
            elif issue.status == "fixed":
                fixed_fps.add(cfp)
    return len(all_cfp - fixed_cfp), len(new_fps), len(fixed_fps)


def build_common_wave_history(
    session: Session,
    runs_by_platform: dict[str, list[Run]],
    *,
    wave_count: int,
) -> list[dict]:
    """
    One chart point per cross-platform analysis wave (no per-OS duplicates).
    Processes oldest waves first for cumulative totals, returns chronological order.
    """
    if not runs_by_platform:
        return []
    all_cfp: set[str] = set()
    fixed_cfp: set[str] = set()
    points: list[dict] = []
    for wave_idx in range(wave_count, 0, -1):
        wave_runs = _wave_runs(runs_by_platform, wave_idx)
        if len(wave_runs) < 2:
            continue
        active, new_c, fixed_c = _metrics_for_common_wave(
            session, wave_runs, all_cfp, fixed_cfp
        )
        anchor = max(wave_runs.values(), key=lambda r: r.timestamp)
        points.append(
            {
                "timestamp": anchor.timestamp.isoformat(),
                "commit": anchor.commit or "—",
                "branch": anchor.branch or "—",
                "release_version": anchor.release_version or "",
                "platform": "common",
                "total": active,
                "new": new_c,
                "fixed": fixed_c,
            }
        )
    points.sort(key=lambda p: p["timestamp"])
    return points


def _build_all_combined_history(
    history_by_platform: dict[str, list[dict]],
    *,
    wave_count: int = 2,
) -> list[dict]:
    """
    All OS KPI: sum cumulative totals from each platform's trend history.
    Uses the same metric definition as Windows/Linux/macOS filters.
    """
    if not history_by_platform:
        return []
    waves: list[dict] = []
    for wave_idx in range(1, wave_count + 1):
        points = [
            h[-wave_idx]
            for h in history_by_platform.values()
            if len(h) >= wave_idx
        ]
        if points:
            waves.append(_sum_history_points(points))
    waves.sort(key=lambda p: p["timestamp"])
    return waves


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
    runs = session.exec(q.order_by(Run.timestamp.desc()).limit(limit)).all()
    runs.reverse()
    return runs


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
        combined = _build_all_combined_history(
            history_by_platform, wave_count=min(2, limit)
        )
        return combined, history_by_platform

    if pf == "common":
        runs_by_platform: dict[str, list[Run]] = {}
        for plat in PLATFORMS:
            plat_runs = _fetch_runs(session, project_id, active_branch, plat, limit)
            if plat_runs:
                runs_by_platform[plat] = plat_runs
        if len(runs_by_platform) < 2:
            return [], history_by_platform
        max_waves = max(len(r) for r in runs_by_platform.values())
        history = build_common_wave_history(
            session,
            runs_by_platform,
            wave_count=min(limit, max_waves),
        )
        return history, history_by_platform

    target = pf if pf in PLATFORMS else "windows"
    runs = _fetch_runs(session, project_id, active_branch, target, limit)
    return build_run_history(session, runs), history_by_platform
