"""Issue author attribution from run commit author."""

from fastapi.testclient import TestClient
from sqlmodel import Session, select

from pvs_tracker.db import engine
from pvs_tracker.incremental import classify_and_store
from pvs_tracker.issue_author import resolve_issue_author
from pvs_tracker.models import Issue, Project, Run


def test_resolve_issue_author_new_uses_run() -> None:
    run = Run(
        project_id=1,
        report_file="db:t.json",
        commit_author_name="Alice",
        commit_author_email="alice@example.com",
    )
    name, email = resolve_issue_author(
        Session(engine),
        run,
        "new",
        "fp1",
        None,
    )
    assert name == "Alice"
    assert email == "alice@example.com"


def test_upload_sets_author_on_new_issues(client: TestClient) -> None:
    client.post("/login", data={"username": "alice", "password": "secret"}, follow_redirects=False)

    with open("reports/smoke_test.json", "rb") as report_file:
        response = client.post(
            "/api/v1/upload",
            data={
                "project_name": "issue-author-test",
                "branch": "main",
                "commit": "sha1",
                "commit_author_name": "Bob Builder",
                "commit_author_email": "bob@example.com",
            },
            files={"file": ("smoke_test.json", report_file, "application/json")},
        )

    assert response.status_code == 200

    with Session(engine) as session:
        project = session.exec(
            select(Project).where(Project.name == "issue-author-test")
        ).first()
        assert project is not None
        run = session.exec(select(Run).where(Run.project_id == project.id)).first()
        assert run is not None
        issues = session.exec(select(Issue).where(Issue.run_id == run.id)).all()
        assert issues
        assert issues
        for issue in issues:
            if issue.status == "fixed":
                continue
            assert issue.author_name == "Bob Builder"
            assert issue.author_email == "bob@example.com"


def test_classify_and_store_propagates_existing_author() -> None:
    with Session(engine) as session:
        project = Project(name="author-propagation-test")
        session.add(project)
        session.commit()
        session.refresh(project)

        run1 = Run(
            project_id=project.id,
            report_file="db:a.json",
            status="done",
            commit_author_name="First",
            commit_author_email="first@example.com",
        )
        session.add(run1)
        session.commit()
        session.refresh(run1)

        classify_and_store(
            session,
            project.id,
            run1.id,
            [
                {
                    "fingerprint": "fp-prop-1",
                    "file_path": "src/a.cpp",
                    "line": 1,
                    "rule_code": "V001",
                    "severity": "High",
                    "message": "test",
                }
            ],
        )

        run2 = Run(
            project_id=project.id,
            report_file="db:b.json",
            status="done",
            commit_author_name="Second",
            commit_author_email="second@example.com",
        )
        session.add(run2)
        session.commit()
        session.refresh(run2)

        classify_and_store(
            session,
            project.id,
            run2.id,
            [
                {
                    "fingerprint": "fp-prop-1",
                    "file_path": "src/a.cpp",
                    "line": 1,
                    "rule_code": "V001",
                    "severity": "High",
                    "message": "test",
                }
            ],
        )

        existing = session.exec(
            select(Issue).where(Issue.run_id == run2.id, Issue.status == "existing")
        ).first()
        assert existing is not None
        assert existing.author_name == "First"
        assert existing.author_email == "first@example.com"
