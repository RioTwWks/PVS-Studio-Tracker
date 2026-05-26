"""Tests for CI orchestration modules."""

from __future__ import annotations

from unittest.mock import MagicMock, PropertyMock, patch

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, SQLModel, create_engine, select
from sqlmodel.pool import StaticPool

from pvs_tracker.main import app
from pvs_tracker.models import Project
from pvs_tracker.jenkins_service import JenkinsTriggerResult, jenkins_job_console_url
from pvs_tracker.project_ci import create_ci_project, slug_from_name


def _jenkins_result(build_number: int = 42) -> JenkinsTriggerResult:
    return JenkinsTriggerResult(
        build_number=build_number,
        queue_id=14018,
        console_url=jenkins_job_console_url("Test_FastAPI", build_number),
        display_label=f"#{build_number}",
    )


@pytest.fixture(name="session")
def session_fixture():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        yield session


@pytest.fixture(name="client")
def client_fixture(session: Session):
    from pvs_tracker.db import get_session

    def _override():
        yield session

    app.dependency_overrides[get_session] = _override
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


def test_slug_from_name():
    assert slug_from_name("My Project") == "My_Project"


def test_create_ci_project(session: Session):
    project = create_ci_project(
        session,
        {
            "name": "TestProj",
            "author_email": "dev@example.com",
            "cvs_system": "Git",
            "repo_path": "https://example.com/repo.git",
            "pvs_check_conf_name": "Debug",
            "pvs_check_arch": "x64",
        },
    )
    assert project.slug == "TestProj"
    assert project.disabled is False


def test_inbound_webhook_health(client: TestClient):
    r = client.get("/webhook/inbound/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_toggle_disabled_htmx(client: TestClient, session: Session):
    project = create_ci_project(
        session,
        {
            "name": "HtmxProj",
            "author_email": "a@b.com",
            "cvs_system": "Git",
            "repo_path": "https://x.git",
            "pvs_check_conf_name": "R",
            "pvs_check_arch": "x64",
        },
    )
    r = client.post(
        f"/ui/projects/{project.id}/toggle-disabled",
        headers={"HX-Request": "true"},
    )
    assert r.status_code == 200
    assert "project-ci-panel" in r.text or "Управление анализом" in r.text
    updated = session.get(Project, project.id)
    assert updated is not None
    assert updated.disabled is True


def test_dashboard_syncs_selected_branch(client: TestClient, session: Session):
    project = create_ci_project(
        session,
        {
            "name": "BranchSync",
            "author_email": "a@b.com",
            "cvs_system": "Git",
            "repo_path": "https://x.git",
            "pvs_check_conf_name": "R",
            "pvs_check_arch": "x64",
            "analysis_branch": "develop",
            "git_branch": "develop",
        },
    )
    r = client.get(f"/ui/projects/{project.id}/dashboard?branch=release/2.0")
    assert r.status_code == 200
    session.refresh(project)
    assert project.git_branch == "release/2.0"
    assert project.analysis_branch == "release/2.0"


@patch("pvs_tracker.jenkins_service.get_jenkins_service")
def test_trigger_analysis_uses_selected_branch(mock_jenkins, client: TestClient, session: Session):
    mock_svc = MagicMock()
    mock_svc.trigger_build.return_value = _jenkins_result(99)
    mock_jenkins.return_value = mock_svc

    project = create_ci_project(
        session,
        {
            "name": "BranchAnalyze",
            "author_email": "a@b.com",
            "cvs_system": "Git",
            "repo_path": "https://x.git",
            "pvs_check_conf_name": "R",
            "pvs_check_arch": "x64",
            "analysis_branch": "main",
            "git_branch": "main",
            "last_processed_changeset": "abc123",
        },
    )
    client.get(f"/ui/projects/{project.id}/dashboard?branch=feature/login")

    with patch("pvs_tracker.project_manage.is_admin", return_value=True):
        r = client.post(
            f"/ui/projects/{project.id}/trigger-analysis",
            data={"branch": "feature/login"},
            headers={"HX-Request": "true"},
        )
    assert r.status_code == 200
    session.refresh(project)
    assert project.git_branch == "feature/login"
    assert mock_svc.trigger_build.called
    passed_project = mock_svc.trigger_build.call_args[0][0]
    from pvs_tracker.project_ci import project_analysis_branch

    assert project_analysis_branch(passed_project) == "feature/login"


@patch("pvs_tracker.jenkins_service.get_jenkins_service")
def test_trigger_analysis_htmx(mock_jenkins, client: TestClient, session: Session):
    mock_svc = MagicMock()
    mock_svc.trigger_build.return_value = _jenkins_result(42)
    mock_jenkins.return_value = mock_svc

    project = create_ci_project(
        session,
        {
            "name": "AnalyzeProj",
            "author_email": "a@b.com",
            "cvs_system": "Git",
            "repo_path": "https://x.git",
            "analysis_branch": "main",
            "pvs_check_conf_name": "R",
            "pvs_check_arch": "x64",
            "last_processed_changeset": "abc123",
        },
    )

    with patch("pvs_tracker.project_manage.is_admin", return_value=True):
        r = client.post(
            f"/ui/projects/{project.id}/trigger-analysis",
            headers={"HX-Request": "true"},
        )
    assert r.status_code == 200
    assert "project-ci-panel" in r.text or "Jenkins" in r.text
    assert "last_jenkins_build_url" not in r.text or "/console" in r.text or "ci-toast-url" in r.text
    session.refresh(project)
    assert project.last_jenkins_build_url is not None
    assert "/42/console" in project.last_jenkins_build_url


def test_jenkins_job_console_url():
    url = jenkins_job_console_url("Test_FastAPI", 7)
    assert url.endswith("/job/Test_FastAPI/7/console")


def test_resolve_assignee_fallback_to_display_name():
    from pvs_tracker.jira_service import JiraService
    from pvs_tracker.models import Run

    jira = JiraService()
    run = Run(
        project_id=1,
        report_file="r.json",
        commit_author_name="jdoe",
        commit_author_email="",
    )
    with patch.object(
        JiraService, "client", new_callable=PropertyMock
    ) as mock_client_prop:
        mock_client = MagicMock()
        mock_client.search_users.return_value = []
        mock_client_prop.return_value = mock_client
        assert jira.resolve_assignee_from_run(run) == "jdoe"


def test_resolve_assignee_from_run():
    from pvs_tracker.jira_service import JiraService
    from pvs_tracker.models import Run

    jira = JiraService()
    run = Run(
        project_id=1,
        report_file="r.json",
        commit="abc",
        commit_author_name="Ivan Petrov",
        commit_author_email="ivan.petrov@company.local",
    )
    with patch.object(
        JiraService, "client", new_callable=PropertyMock
    ) as mock_client_prop:
        mock_client = MagicMock()
        mock_user = MagicMock()
        mock_user.name = "ivan.petrov"
        mock_client.search_users.return_value = [mock_user]
        mock_client_prop.return_value = mock_client
        assignee = jira.resolve_assignee_from_run(run)
    assert assignee == "ivan.petrov"


def test_resolve_assignee_from_issue_prefers_issue_author():
    from pvs_tracker.jira_service import JiraService
    from pvs_tracker.models import Issue, Run

    jira = JiraService()
    run = Run(
        project_id=1,
        report_file="r.json",
        commit="abc",
        commit_author_name="Run Author",
        commit_author_email="run.author@company.local",
    )
    issue = Issue(
        run_id=1,
        fingerprint="fp1",
        file_path="a.cpp",
        line=1,
        rule_code="V001",
        severity="High",
        message="msg",
        status="new",
        author_name="Issue Author",
        author_email="issue.author@company.local",
    )

    with patch.object(
        JiraService, "client", new_callable=PropertyMock
    ) as mock_client_prop:
        mock_client = MagicMock()
        mock_user = MagicMock()
        mock_user.name = "issue.author"
        mock_client.search_users.return_value = [mock_user]
        mock_client_prop.return_value = mock_client
        assignee = jira.resolve_assignee_from_issue(issue, run)

    assert assignee == "issue.author"


def test_analysis_callback(client: TestClient, session: Session):
    project = create_ci_project(
        session,
        {
            "name": "CbProj",
            "slug": "cb_slug",
            "author_email": "a@b.com",
            "cvs_system": "Git",
            "repo_path": "https://x.git",
            "pvs_check_conf_name": "R",
            "pvs_check_arch": "x64",
        },
    )
    r = client.post(
        "/api/v1/projects/cb_slug/analysis-callback",
        data={"commit": "deadbeef", "version": "1.2.3"},
    )
    assert r.status_code == 200
    session.refresh(project)
    refreshed = session.exec(select(Project).where(Project.slug == "cb_slug")).first()
    assert refreshed is not None
    assert refreshed.last_processed_changeset == "deadbeef"
    assert refreshed.release_version == "1.2.3"
