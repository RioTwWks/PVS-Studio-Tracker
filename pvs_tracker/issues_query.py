"""Issue list assembly for dashboard platform filters."""

from __future__ import annotations

from sqlmodel import Session, select

from pvs_tracker.models import Issue, Project
from pvs_tracker.platforms import PlatformFilter, normalize_platform_filter
from pvs_tracker.run_queries import common_cross_fps, get_analysis_set_runs, get_latest_run


def _apply_text_filters(
    issues: list[Issue],
    severity: str,
    status_filter: str,
    q: str,
) -> list[Issue]:
    result = list(issues)
    if severity:
        result = [i for i in result if i.severity == severity]
    if status_filter and status_filter.strip():
        result = [i for i in result if i.status == status_filter]
    else:
        result = [i for i in result if i.status in ("new", "existing")]
    if q:
        like = q.lower()
        result = [
            i
            for i in result
            if like in i.file_path.lower()
            or like in i.rule_code.lower()
            or like in i.message.lower()
            or like in (i.author_name or "").lower()
            or like in (i.author_email or "").lower()
        ]
    return result


def _sort_issues(
    issues: list[Issue],
    sort_by: str,
    order: str,
    classifier_map: dict,
) -> list[Issue]:
    reverse = order == "desc"

    def sort_key(issue: Issue):
        clf = classifier_map.get(issue.classifier_id)
        if sort_by == "status":
            return issue.status
        if sort_by == "severity":
            return issue.severity
        if sort_by == "rule":
            return issue.rule_code
        if sort_by == "type":
            return clf.type if clf else ""
        if sort_by == "priority":
            return clf.priority if clf else ""
        return issue.file_path

    return sorted(issues, key=sort_key, reverse=reverse)


def resolve_issues_for_filter(
    session: Session,
    project: Project,
    branch: str,
    platform_filter: str,
    severity: str = "",
    status_filter: str = "",
    q: str = "",
    sort_by: str = "file",
    order: str = "asc",
    classifier_map: dict | None = None,
) -> tuple[list[Issue], int | None, dict[int, str], dict[int, int], bool]:
    """
    Returns:
        issues (full list before pagination),
        primary_run_id,
        issue_platforms,
        issue_run_ids,
        show_platform_badge
    """
    pf: PlatformFilter = normalize_platform_filter(platform_filter)
    classifier_map = classifier_map or {}
    issue_platforms: dict[int, str] = {}
    issue_run_ids: dict[int, int] = {}

    if pf in ("windows", "linux", "macos"):
        run = get_latest_run(session, project.id, branch, pf)
        if not run:
            return [], None, {}, {}, False
        issues = session.exec(select(Issue).where(Issue.run_id == run.id)).all()
        issues = _apply_text_filters(issues, severity, status_filter, q)
        issues = _sort_issues(issues, sort_by, order, classifier_map)
        return issues, run.id, issue_platforms, issue_run_ids, False

    if pf == "all":
        runs = get_analysis_set_runs(session, project.id, branch)
        merged: list[Issue] = []
        for plat, run in runs.items():
            batch = session.exec(select(Issue).where(Issue.run_id == run.id)).all()
            batch = _apply_text_filters(batch, severity, status_filter, q)
            for issue in batch:
                issue_platforms[issue.id] = plat
                issue_run_ids[issue.id] = run.id
                merged.append(issue)
        merged = _sort_issues(merged, sort_by, order, classifier_map)
        primary = next(iter(runs.values())).id if runs else None
        return merged, primary, issue_platforms, issue_run_ids, True

    common_fps = common_cross_fps(session, project.id, branch)
    if not common_fps:
        return [], None, {}, {}, True

    seen_fp: set[str] = set()
    merged_common: list[Issue] = []
    runs = get_analysis_set_runs(session, project.id, branch)
    for plat, run in runs.items():
        batch = session.exec(
            select(Issue).where(
                Issue.run_id == run.id,
                Issue.cross_platform_fp.in_(list(common_fps)),
            )
        ).all()
        batch = _apply_text_filters(batch, severity, status_filter, q)
        for issue in batch:
            if not issue.cross_platform_fp or issue.cross_platform_fp in seen_fp:
                continue
            seen_fp.add(issue.cross_platform_fp)
            issue_platforms[issue.id] = plat
            issue_run_ids[issue.id] = run.id
            merged_common.append(issue)
    merged_common = _sort_issues(merged_common, sort_by, order, classifier_map)
    primary = next(iter(runs.values())).id if runs else None
    return merged_common, primary, issue_platforms, issue_run_ids, True
