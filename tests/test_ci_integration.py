"""Tests for CI orchestration modules."""

from __future__ import annotations

from unittest.mock import MagicMock, PropertyMock, patch

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, SQLModel, create_engine, select
from sqlmodel.pool import StaticPool

from pvs_tracker.main import app
from pvs_tracker.models import ActivityLog, Project, RestQueueJob, User
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
    import os

    from pvs_tracker.db import get_session
    from pvs_tracker.rest_queue.runtime import stop_embedded_workers

    os.environ["REST_QUEUE_MODE"] = "external"

    def _override():
        yield session

    app.dependency_overrides[get_session] = _override
    from pvs_tracker import rest_queue

    bind = session.get_bind()
    rest_queue.store.engine = bind
    rest_queue.handlers.engine = bind
    with TestClient(app) as c:
        stop_embedded_workers()
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
        f"/ui/projects/{project.slug}/toggle-disabled",
        headers={"HX-Request": "true"},
    )
    assert r.status_code == 200
    assert "project-ci-panel" in r.text or "Управление анализом" in r.text
    updated = session.get(Project, project.id)
    assert updated is not None
    assert updated.disabled is True

    from pvs_tracker.models import ActivityLog

    logs = session.exec(
        select(ActivityLog).where(
            ActivityLog.project_id == project.id,
            ActivityLog.action == "ci_disable",
        )
    ).all()
    assert len(logs) == 1
    assert logs[0].entity_type == "project"
    assert "ci_activity_log_title" in r.text or "История действий" in r.text


def test_ci_action_log_records_authenticated_user(client: TestClient, session: Session):
    from pvs_tracker.models import ActivityLog, User, UserRole

    user = User(
        username="ci_tester",
        display_name="CI Tester",
        role=UserRole.ADMIN,
        auth_provider="local",
        is_active=True,
    )
    session.add(user)
    session.commit()
    session.refresh(user)

    project = create_ci_project(
        session,
        {
            "name": "AuditProj",
            "author_email": "a@b.com",
            "cvs_system": "Git",
            "repo_path": "https://x.git",
            "pvs_check_conf_name": "R",
            "pvs_check_arch": "x64",
        },
    )

    with patch("pvs_tracker.ci_activity_log.get_current_user", return_value=user):
        r = client.post(
            f"/ui/projects/{project.slug}/toggle-jira",
            headers={"HX-Request": "true"},
        )
    assert r.status_code == 200

    log = session.exec(
        select(ActivityLog).where(
            ActivityLog.project_id == project.id,
            ActivityLog.action == "ci_jira_on",
        )
    ).first()
    assert log is not None
    assert log.user_id == user.id


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
    r = client.get(f"/ui/projects/{project.slug}/dashboard?branch=release/2.0")
    assert r.status_code == 200
    session.refresh(project)
    assert project.git_branch == "release/2.0"
    assert project.analysis_branch == "release/2.0"


@patch("pvs_tracker.rest_queue.handlers.trigger_jenkins_build")
def test_trigger_analysis_uses_selected_branch(mock_trigger, client: TestClient, session: Session):
    mock_trigger.return_value = _jenkins_result(99)

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
    client.get(f"/ui/projects/{project.slug}/dashboard?branch=feature/login")

    with patch("pvs_tracker.project_manage.is_admin", return_value=True):
        r = client.post(
            f"/ui/projects/{project.slug}/trigger-analysis",
            data={"branch": "feature/login"},
            headers={"HX-Request": "true"},
        )
    assert r.status_code == 200
    session.refresh(project)
    assert project.git_branch == "feature/login"
    job = claim_and_run_jenkins_job()
    assert job is not None
    assert mock_trigger.called
    passed_project = mock_trigger.call_args[0][0]
    from pvs_tracker.project_ci import project_analysis_branch

    assert project_analysis_branch(passed_project) == "feature/login"


def claim_and_run_jenkins_job():
    from pvs_tracker.rest_queue.handlers import execute_job
    from pvs_tracker.rest_queue.store import claim_next_job

    job = claim_next_job("jenkins", "test")
    if job:
        execute_job(job)
    return job


@patch("pvs_tracker.rest_queue.handlers.trigger_jenkins_build")
def test_trigger_analysis_htmx(mock_trigger, client: TestClient, session: Session):
    mock_trigger.return_value = _jenkins_result(42)

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
            f"/ui/projects/{project.slug}/trigger-analysis",
            headers={"HX-Request": "true"},
        )
    assert r.status_code == 200
    assert "project-ci-panel" in r.text or "Jenkins" in r.text
    claim_and_run_jenkins_job()
    session.refresh(project)
    assert project.last_jenkins_build_url is not None
    assert "/42/console" in project.last_jenkins_build_url


def test_jenkins_job_console_url():
    url = jenkins_job_console_url("Test_FastAPI", 7)
    assert url.endswith("/job/Test_FastAPI/7/console")


def test_pick_default_build_selection_prefers_active():
    from pvs_tracker.jenkins_service import (
        JenkinsBuildSnapshot,
        mark_selected_build,
        pick_default_build_selection,
        project_builds_have_active,
    )

    builds = [
        JenkinsBuildSnapshot(
            build_number=40,
            queue_id=None,
            status="SUCCESS",
            label="#40",
            console_url="http://jenkins/job/40/console",
        ),
        JenkinsBuildSnapshot(
            build_number=None,
            queue_id=99,
            status="QUEUED",
            label="queue #99",
            console_url="http://jenkins/queue/99",
        ),
    ]
    build_no, queue_no = pick_default_build_selection(builds)
    assert build_no is None
    assert queue_no == 99
    assert project_builds_have_active(builds) is True

    marked = mark_selected_build(builds, build_number=build_no, queue_id=queue_no)
    assert marked[1].is_selected is True


@patch("pvs_tracker.jenkins_service.fetch_project_ci_builds")
@patch("pvs_tracker.jenkins_service.get_project_build_console")
def test_ci_builds_panel_route(mock_console, mock_builds, client: TestClient, session: Session):
    from pvs_tracker.jenkins_service import JenkinsBuildSnapshot

    project = create_ci_project(
        session,
        {
            "name": "ConsoleProj",
            "slug": "ConsoleProj",
            "author_email": "a@b.com",
            "cvs_system": "Git",
            "repo_path": "https://x.git",
            "pvs_check_conf_name": "R",
            "pvs_check_arch": "x64",
        },
    )
    mock_builds.return_value = (
        [
            JenkinsBuildSnapshot(
                build_number=7,
                queue_id=None,
                status="RUNNING",
                label="#7",
                console_url="http://jenkins/job/7/console",
            )
        ],
        None,
    )
    mock_console.return_value = ("Started by user\nBuilding...", "RUNNING")

    r = client.get(f"/ui/projects/{project.slug}/ci-builds")
    assert r.status_code == 200
    assert "jenkins-builds-panel" in r.text
    assert "#7" in r.text
    assert "Started by user" in r.text
    assert 'hx-trigger="every 5s"' in r.text
    mock_console.assert_called_once()


@patch("pvs_tracker.jenkins_service.fetch_project_ci_builds")
def test_ci_builds_panel_shows_queue_item(mock_builds, client: TestClient, session: Session):
    from pvs_tracker.jenkins_service import JenkinsBuildSnapshot

    project = create_ci_project(
        session,
        {
            "name": "QueueProj",
            "slug": "QueueProj",
            "author_email": "a@b.com",
            "cvs_system": "Git",
            "repo_path": "https://x.git",
            "pvs_check_conf_name": "R",
            "pvs_check_arch": "x64",
        },
    )
    mock_builds.return_value = (
        [
            JenkinsBuildSnapshot(
                build_number=None,
                queue_id=55,
                status="QUEUED",
                label="queue #55",
                console_url="http://jenkins/queue/55",
                why="Waiting for executor",
            )
        ],
        None,
    )

    with patch("pvs_tracker.jenkins_service.get_project_build_console") as mock_console:
        mock_console.return_value = (
            "Build is waiting in Jenkins queue (#55).\nWaiting for executor",
            "QUEUED",
        )
        r = client.get(f"/ui/projects/{project.slug}/ci-builds?queue=55")
    assert r.status_code == 200
    assert "queue #55" in r.text
    assert "Waiting for executor" in r.text
    assert 'hx-trigger="every 5s"' in r.text


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
