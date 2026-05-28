"""Dashboard history totals per platform filter."""

from datetime import datetime, timedelta

from sqlmodel import Session

from pvs_tracker.dashboard_history import build_dashboard_histories
from pvs_tracker.db import engine
from pvs_tracker.models import Issue, Project, Run


def _add_run_with_issues(
    session: Session,
    project_id: int,
    platform: str,
    active: int,
    *,
    branch: str = "main",
    when: datetime | None = None,
) -> Run:
    ts = when or datetime.utcnow()
    run = Run(
        project_id=project_id,
        branch=branch,
        target_platform=platform,
        report_file="db:test.json",
        status="done",
        timestamp=ts,
    )
    session.add(run)
    session.commit()
    session.refresh(run)
    for i in range(active):
        session.add(
            Issue(
                run_id=run.id,
                fingerprint=f"{platform}-fp-{i}",
                file_path=f"src/{platform}_{i}.cpp",
                line=i + 1,
                rule_code="V1001",
                message="msg",
                severity="High",
                status="existing",
            )
        )
    session.commit()
    return run


def test_all_platform_filter_sums_latest_runs() -> None:
    with Session(engine) as session:
        project = Project(name="dash-all-sum")
        session.add(project)
        session.commit()
        session.refresh(project)

        base = datetime(2025, 1, 1, 12, 0, 0)
        _add_run_with_issues(
            session, project.id, "windows", 100, when=base
        )
        _add_run_with_issues(
            session,
            project.id,
            "linux",
            40,
            when=base + timedelta(hours=1),
        )

        history, by_platform = build_dashboard_histories(
            session, project.id, "main", "all"
        )

        assert len(by_platform) == 2
        assert history
        assert history[-1]["total"] == 140
        assert history[-1]["platform"] == "all"

        win_history, _ = build_dashboard_histories(
            session, project.id, "main", "windows"
        )
        assert win_history[-1]["total"] == 100


def test_fetch_runs_uses_most_recent_not_oldest() -> None:
    with Session(engine) as session:
        project = Project(name="dash-recent-runs")
        session.add(project)
        session.commit()
        session.refresh(project)

        base = datetime(2025, 3, 1, 12, 0, 0)
        _add_run_with_issues(session, project.id, "windows", 10, when=base)
        _add_run_with_issues(
            session,
            project.id,
            "windows",
            30,
            when=base + timedelta(days=1),
        )

        history, _ = build_dashboard_histories(
            session, project.id, "main", "windows", limit=1
        )
        assert history[-1]["total"] == 30


def test_all_total_is_at_least_each_platform() -> None:
    with Session(engine) as session:
        project = Project(name="dash-all-gte")
        session.add(project)
        session.commit()
        session.refresh(project)

        base = datetime(2025, 4, 1, 12, 0, 0)
        _add_run_with_issues(session, project.id, "windows", 100, when=base)
        _add_run_with_issues(
            session, project.id, "linux", 40, when=base + timedelta(hours=1)
        )

        win_history, _ = build_dashboard_histories(
            session, project.id, "main", "windows"
        )
        all_history, _ = build_dashboard_histories(session, project.id, "main", "all")
        assert all_history[-1]["total"] >= win_history[-1]["total"]


def test_all_platform_filter_not_windows_only() -> None:
    with Session(engine) as session:
        project = Project(name="dash-all-not-win")
        session.add(project)
        session.commit()
        session.refresh(project)

        base = datetime(2025, 2, 1, 12, 0, 0)
        _add_run_with_issues(session, project.id, "windows", 10, when=base)
        _add_run_with_issues(
            session, project.id, "linux", 5, when=base + timedelta(hours=1)
        )

        history, _ = build_dashboard_histories(session, project.id, "main", "all")
        assert history[-1]["total"] == 15
