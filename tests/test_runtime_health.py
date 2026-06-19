"""Tests for runtime / worker / deployment health checks."""

from __future__ import annotations

from datetime import datetime, timedelta
from unittest.mock import patch

import pytest
from sqlmodel import Session, SQLModel, create_engine
from sqlmodel.pool import StaticPool

from pvs_tracker.models import RestQueueJob
from pvs_tracker.runtime_health import (
    check_instance_health,
    check_rest_queue_mode_health,
    check_workers_health,
    check_zero_downtime_readiness,
    collect_runtime_health,
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
    SQLModel.metadata.drop_all(engine)


@pytest.fixture(autouse=True)
def patch_engine(session: Session, monkeypatch: pytest.MonkeyPatch):
    from pvs_tracker import runtime_health

    monkeypatch.setattr(runtime_health, "engine", session.get_bind())
    yield


def test_check_instance_health_standalone(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("PVS_IN_DOCKER", raising=False)
    with patch("pvs_tracker.runtime_health._is_docker", return_value=False):
        result = check_instance_health()
    assert result["name"] == "instance"
    assert result["status"] == "ok"
    assert result["details"]["docker"] is False


def test_check_instance_health_docker(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("PVS_IN_DOCKER", "true")
    monkeypatch.setenv("PVS_INSTANCE_ID", "app-1")
    result = check_instance_health()
    assert result["details"]["docker"] is True
    assert result["details"]["instance_id"] == "app-1"


def test_check_rest_queue_mode_embedded(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("REST_QUEUE_MODE", "embedded")
    result = check_rest_queue_mode_health()
    assert result["status"] == "ok"
    assert result["details"]["mode"] == "embedded"


def test_check_workers_embedded_running(session: Session, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("REST_QUEUE_MODE", "embedded")
    embedded = {
        "jenkins": {"alive": True, "worker_id": "jenkins-abc12345"},
        "jira": {"alive": True, "worker_id": "jira-def67890"},
        "tfs": {"alive": True, "worker_id": "tfs-11112222"},
        "webhook": {"alive": True, "worker_id": "webhook-33334444"},
        "smtp": {"alive": True, "worker_id": "smtp-55556666"},
    }
    with patch("pvs_tracker.runtime_health.embedded_workers_status", return_value=embedded):
        workers = check_workers_health(session)
    assert len(workers) == 5
    assert all(w["status"] == "ok" for w in workers)
    assert workers[0]["name"] == "worker_jenkins"


def test_check_workers_external_pending_without_activity(session: Session, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("REST_QUEUE_MODE", "external")
    session.add(
        RestQueueJob(
            service="jenkins",
            task="trigger_build",
            payload_json="{}",
            status="pending",
        )
    )
    session.commit()
    with patch("pvs_tracker.runtime_health.embedded_workers_status", return_value={}):
        workers = check_workers_health(session)
    jenkins = next(w for w in workers if w["name"] == "worker_jenkins")
    assert jenkins["status"] == "error"
    assert jenkins["details"]["pending"] == 1


def test_check_workers_external_processing(session: Session, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("REST_QUEUE_MODE", "external")
    session.add(
        RestQueueJob(
            service="jira",
            task="sync_run",
            payload_json="{}",
            status="processing",
            worker_id="jira-worker-1",
            started_at=datetime.utcnow(),
        )
    )
    session.commit()
    with patch("pvs_tracker.runtime_health.embedded_workers_status", return_value={}):
        workers = check_workers_health(session)
    jira = next(w for w in workers if w["name"] == "worker_jira")
    assert jira["status"] == "ok"
    assert "jira-worker-1" in jira["message"]


def test_check_workers_external_idle(session: Session, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("REST_QUEUE_MODE", "external")
    with patch("pvs_tracker.runtime_health.embedded_workers_status", return_value={}):
        workers = check_workers_health(session)
    assert all(w["status"] == "idle" for w in workers)


def test_zero_downtime_sqlite_not_ready(session: Session):
    result = check_zero_downtime_readiness(session)
    assert result["name"] == "zero_downtime"
    assert result["status"] == "error"
    assert result["details"]["multi_instance_capable"] is False


def test_collect_runtime_health(session: Session, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("REST_QUEUE_MODE", "embedded")
    embedded = {svc: {"alive": True, "worker_id": f"{svc}-x"} for svc in ("jenkins", "jira", "tfs", "webhook", "smtp")}
    with patch("pvs_tracker.runtime_health.embedded_workers_status", return_value=embedded):
        payload = collect_runtime_health(session)
    assert "checked_at" in payload
    assert len(payload["workers"]) == 5
    assert len(payload["deployment"]) >= 5
    names = [item["name"] for item in payload["deployment"]]
    assert "instance" in names
    assert "zero_downtime" in names
