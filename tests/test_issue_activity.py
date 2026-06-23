"""Tests for issue activity timeline."""

from datetime import datetime, timedelta

from sqlmodel import Session

from pvs_tracker import main
from pvs_tracker.issue_activity import build_issue_activity_timeline, format_activity_timestamp
from pvs_tracker.models import Issue, Project, Run


def test_format_activity_timestamp() -> None:
    dt = datetime(2026, 3, 25, 14, 21)
    text = format_activity_timestamp(dt)
    assert "March" in text
    assert "2026" in text
    assert "2:21" in text or "02:21" in text


def test_build_issue_activity_timeline_status_changes() -> None:
    with Session(main.engine) as session:
        project = Project(name="activity-test-project")
        session.add(project)
        session.commit()
        session.refresh(project)

        base = datetime.utcnow() - timedelta(days=10)
        run1 = Run(
            project_id=project.id,
            branch="main",
            report_file="db:r1.json",
            status="done",
            timestamp=base,
            commit_author_name="Ivan Emelin",
        )
        run2 = Run(
            project_id=project.id,
            branch="main",
            report_file="db:r2.json",
            status="done",
            timestamp=base + timedelta(days=5),
        )
        session.add(run1)
        session.add(run2)
        session.commit()
        session.refresh(run1)
        session.refresh(run2)

        fp = "activity-fp-1"
        issue1 = Issue(
            run_id=run1.id,
            fingerprint=fp,
            file_path="src/a.cpp",
            line=5,
            rule_code="V501",
            severity="High",
            message="test",
            status="new",
            author_name="Ivan Emelin",
        )
        issue2 = Issue(
            run_id=run2.id,
            fingerprint=fp,
            file_path="src/a.cpp",
            line=5,
            rule_code="V501",
            severity="High",
            message="test",
            status="existing",
        )
        session.add(issue1)
        session.add(issue2)
        session.commit()
        session.refresh(issue2)

        events = build_issue_activity_timeline(session, issue2, project.id)
        kinds = [e.kind for e in events]
        assert "created" in kinds
        assert "status_change" in kinds
        status_event = next(e for e in events if e.kind == "status_change")
        assert "OPEN" in status_event.lines[0]
        assert "NEW" in status_event.lines[0]
