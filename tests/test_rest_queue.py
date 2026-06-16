"""Tests for REST API job queue."""

from __future__ import annotations

import os
from unittest.mock import MagicMock, patch

import pytest
from sqlmodel import Session, SQLModel, create_engine, select
from sqlmodel.pool import StaticPool

os.environ.setdefault("REST_QUEUE_MODE", "external")

from pvs_tracker.models import RestQueueJob  # noqa: E402
from pvs_tracker.rest_queue.client import enqueue_jenkins_trigger, enqueue_jira_sync
from pvs_tracker.rest_queue.handlers import execute_job
from pvs_tracker.rest_queue.store import claim_next_job, get_job
from pvs_tracker.rest_queue.types import SERVICE_JENKINS


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
    SQLModel.metadata.drop_all(engine)


@pytest.fixture(autouse=True)
def patch_engine(session: Session, monkeypatch: pytest.MonkeyPatch):
    from pvs_tracker import rest_queue

    monkeypatch.setattr(rest_queue.store, "engine", session.get_bind())
    monkeypatch.setattr(rest_queue.handlers, "engine", session.get_bind())
    yield


def test_enqueue_and_claim(session: Session):
    job_id = enqueue_jenkins_trigger(1, "abc", "NO", True, ["a.cpp"])
    job = claim_next_job(SERVICE_JENKINS, "test-worker")
    assert job is not None
    assert job.id == job_id
    assert job.status == "processing"


@patch("pvs_tracker.rest_queue.handlers.trigger_jenkins_build")
def test_jenkins_handler_updates_project(mock_trigger, session: Session):
    from pvs_tracker.jenkins_service import JenkinsTriggerResult
    from pvs_tracker.models import Project
    from pvs_tracker.project_ci import create_ci_project

    project = create_ci_project(
        session,
        {
            "name": "QueueProj",
            "author_email": "a@b.com",
            "cvs_system": "Git",
            "repo_path": "https://x.git",
            "pvs_check_conf_name": "R",
            "pvs_check_arch": "x64",
        },
    )
    mock_trigger.return_value = JenkinsTriggerResult(
        build_number=5,
        queue_id=1,
        console_url="http://jenkins/job/5/console",
        display_label="#5",
    )
    job_id = enqueue_jenkins_trigger(project.id, "deadbeef", "NO", False, [])
    job = claim_next_job(SERVICE_JENKINS, "worker-1")
    assert job is not None
    execute_job(job)
    session.refresh(project)
    assert project.last_jenkins_build_id == 5
    assert project.last_jenkins_build_url == "http://jenkins/job/5/console"
    stored = get_job(job_id)
    assert stored is not None
    assert stored.status == "done"


def test_jira_enqueue_creates_pending_job(session: Session):
    job_id = enqueue_jira_sync(1, 2)
    job = session.get(RestQueueJob, job_id)
    assert job is not None
    assert job.service == "jira"
    assert job.status == "pending"
    pending = session.exec(
        select(RestQueueJob).where(RestQueueJob.service == "jira", RestQueueJob.status == "pending")
    ).all()
    assert len(pending) == 1
