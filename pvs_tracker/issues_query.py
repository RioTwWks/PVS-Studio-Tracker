"""Issue list assembly for dashboard platform filters."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlmodel import Session, select

from pvs_tracker.models import ErrorClassifier, Issue, Project
from pvs_tracker.platforms import PLATFORMS, PlatformFilter, normalize_platform_filter
from pvs_tracker.run_queries import common_cross_fps, get_analysis_set_runs, get_latest_run


def format_relative_time(dt: datetime | None) -> str:
    """Human-readable relative time for issue cards."""
    if not dt:
        return ""
    now = datetime.now(timezone.utc)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    delta = now - dt
    seconds = int(delta.total_seconds())
    if seconds < 60:
        return "just now"
    minutes = seconds // 60
    if minutes < 60:
        return f"{minutes} min ago" if minutes == 1 else f"{minutes} mins ago"
    hours = minutes // 60
    if hours < 24:
        return f"{hours} hour ago" if hours == 1 else f"{hours} hours ago"
    days = hours // 24
    if days < 30:
        return f"{days} day ago" if days == 1 else f"{days} days ago"
    months = days // 30
    if months < 12:
        return f"{months} month ago" if months == 1 else f"{months} months ago"
    years = months // 12
    return f"{years} year ago" if years == 1 else f"{years} years ago"


def _matches_status(issue: Issue, status_filter: str) -> bool:
    if status_filter and status_filter.strip():
        return issue.status == status_filter
    return issue.status in ("new", "existing")


def _classifier_for(issue: Issue, classifier_map: dict[int, ErrorClassifier]) -> ErrorClassifier | None:
    if not issue.classifier_id:
        return None
    return classifier_map.get(issue.classifier_id)


def _apply_text_filters(
    issues: list[Issue],
    severity: str,
    status_filter: str,
    q: str,
    type_filter: str = "",
    priority_filter: str = "",
    classifier_map: dict[int, ErrorClassifier] | None = None,
) -> list[Issue]:
    classifier_map = classifier_map or {}
    result = list(issues)
    if severity:
        result = [i for i in result if i.severity == severity]
    if status_filter and status_filter.strip():
        result = [i for i in result if i.status == status_filter]
    else:
        result = [i for i in result if i.status in ("new", "existing")]
    if type_filter:
        result = [
            i
            for i in result
            if (clf := _classifier_for(i, classifier_map)) and clf.type == type_filter
        ]
    if priority_filter:
        result = [
            i
            for i in result
            if (clf := _classifier_for(i, classifier_map)) and clf.priority == priority_filter
        ]
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


def compute_issue_facets(
    issues: list[Issue],
    classifier_map: dict[int, ErrorClassifier],
    severity: str = "",
    status_filter: str = "",
    type_filter: str = "",
    priority_filter: str = "",
) -> dict[str, dict[str, int]]:
    """Facet counts for sidebar filters (respects other active filters)."""
    facets: dict[str, dict[str, int]] = {
        "severity": {},
        "status": {},
        "type": {},
        "priority": {},
    }

    for issue in issues:
        clf = _classifier_for(issue, classifier_map)

        if _matches_status(issue, status_filter):
            if not type_filter or (clf and clf.type == type_filter):
                if not priority_filter or (clf and clf.priority == priority_filter):
                    facets["severity"][issue.severity] = facets["severity"].get(issue.severity, 0) + 1

        if (not severity or issue.severity == severity) and (
            not type_filter or (clf and clf.type == type_filter)
        ) and (not priority_filter or (clf and clf.priority == priority_filter)):
            key = issue.status if issue.status in ("new", "existing", "fixed", "ignored") else "existing"
            facets["status"][key] = facets["status"].get(key, 0) + 1

        if _matches_status(issue, status_filter) and (
            not severity or issue.severity == severity
        ) and (not priority_filter or (clf and clf.priority == priority_filter)):
            if clf and clf.type:
                facets["type"][clf.type] = facets["type"].get(clf.type, 0) + 1

        if _matches_status(issue, status_filter) and (
            not severity or issue.severity == severity
        ) and (not type_filter or (clf and clf.type == type_filter)):
            if clf and clf.priority:
                facets["priority"][clf.priority] = facets["priority"].get(clf.priority, 0) + 1

    return facets


def compute_total_effort(
    issues: list[Issue],
    classifier_map: dict[int, ErrorClassifier],
) -> int:
    total = 0
    for issue in issues:
        if issue.technical_debt_minutes:
            total += issue.technical_debt_minutes
        elif clf := _classifier_for(issue, classifier_map):
            total += clf.remediation_effort or 0
    return total


def group_issues_by_file(
    issues: list[Issue],
    display_paths: dict[int, str] | None = None,
) -> list[tuple[str, str, list[Issue]]]:
    """Group issues by file path; returns (file_path, display_path, issues)."""
    if not issues:
        return []
    display_paths = display_paths or {}
    groups: list[tuple[str, str, list[Issue]]] = []
    current_path: str | None = None
    current_display = ""
    current_issues: list[Issue] = []

    for issue in issues:
        fp = issue.file_path or ""
        if fp != current_path:
            if current_issues:
                groups.append((current_path or "", current_display, current_issues))
            current_path = fp
            current_display = display_paths.get(issue.id, fp)
            current_issues = [issue]
        else:
            current_issues.append(issue)

    if current_issues:
        groups.append((current_path or "", current_display, current_issues))
    return groups


_PLATFORM_SORT_ORDER: dict[str, int] = {p: i for i, p in enumerate(PLATFORMS)}


def _sort_issues(
    issues: list[Issue],
    sort_by: str,
    order: str,
    classifier_map: dict,
    issue_platforms: dict[int, str] | None = None,
) -> list[Issue]:
    reverse = order == "desc"
    platforms = issue_platforms or {}

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
        if sort_by == "platform":
            plat = platforms.get(issue.id, "")
            return (_PLATFORM_SORT_ORDER.get(plat, len(PLATFORMS)), plat)
        return issue.file_path

    return sorted(issues, key=sort_key, reverse=reverse)


def count_issues_for_filter(
    session: Session,
    project: Project,
    branch: str,
    platform_filter: str,
    severity: str = "",
    status_filter: str = "",
    q: str = "",
) -> int:
    """Issue count for dashboard badges — matches /ui/issues list length."""
    issues, _, _, _, _ = resolve_issues_for_filter(
        session,
        project,
        branch,
        platform_filter,
        severity=severity,
        status_filter=status_filter,
        q=q,
    )
    return len(issues)


def resolve_issues_for_filter(
    session: Session,
    project: Project,
    branch: str,
    platform_filter: str,
    severity: str = "",
    status_filter: str = "",
    q: str = "",
    type_filter: str = "",
    priority_filter: str = "",
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
        issues = _apply_text_filters(
            issues, severity, status_filter, q, type_filter, priority_filter, classifier_map
        )
        issues = _sort_issues(issues, sort_by, order, classifier_map, issue_platforms)
        return issues, run.id, issue_platforms, issue_run_ids, False

    if pf == "all":
        runs = get_analysis_set_runs(session, project.id, branch)
        merged: list[Issue] = []
        for plat, run in runs.items():
            batch = session.exec(select(Issue).where(Issue.run_id == run.id)).all()
            batch = _apply_text_filters(
                batch, severity, status_filter, q, type_filter, priority_filter, classifier_map
            )
            for issue in batch:
                issue_platforms[issue.id] = plat
                issue_run_ids[issue.id] = run.id
                merged.append(issue)
        merged = _sort_issues(merged, sort_by, order, classifier_map, issue_platforms)
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
        batch = _apply_text_filters(
            batch, severity, status_filter, q, type_filter, priority_filter, classifier_map
        )
        for issue in batch:
            if not issue.cross_platform_fp or issue.cross_platform_fp in seen_fp:
                continue
            seen_fp.add(issue.cross_platform_fp)
            issue_platforms[issue.id] = plat
            issue_run_ids[issue.id] = run.id
            merged_common.append(issue)
    merged_common = _sort_issues(
        merged_common, sort_by, order, classifier_map, issue_platforms
    )
    primary = next(iter(runs.values())).id if runs else None
    return merged_common, primary, issue_platforms, issue_run_ids, True
