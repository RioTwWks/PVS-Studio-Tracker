"""Tests for integration health checks and admin API."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from sqlmodel import Session

from pvs_tracker import main
from pvs_tracker.integration_health import (
    check_jira_health,
    check_service_health,
    check_sonarqube_health,
    check_tfs_health,
    collect_integration_health,
)


def test_check_service_health_ok():
    with Session(main.engine) as session:
        result = check_service_health(session)
    assert result["name"] == "service"
    assert result["status"] == "ok"
    assert result["details"]["database"] == "ok"


@patch("jira.JIRA")
def test_check_jira_health_ok(mock_jira_cls):
    mock_client = MagicMock()
    mock_client.server_info.return_value = {"version": "9.12.0"}
    mock_jira_cls.return_value = mock_client

    result = check_jira_health()
    assert result["name"] == "jira"
    assert result["status"] == "ok"
    assert "9.12.0" in result["message"]


@patch("pvs_tracker.integration_health.requests.get")
def test_check_tfs_health_ok(mock_get):
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"count": 3}
    mock_get.return_value = mock_resp

    result = check_tfs_health()
    assert result["name"] == "tfs"
    assert result["status"] == "ok"


@patch("pvs_tracker.integration_health.requests.Session")
def test_check_sonarqube_health_ok(mock_session_cls):
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"status": "UP"}
    mock_session = MagicMock()
    mock_session.get.return_value = mock_resp
    mock_session_cls.return_value = mock_session

    result = check_sonarqube_health()
    assert result["name"] == "sonarqube"
    assert result["status"] == "ok"


@patch("pvs_tracker.integration_health.check_sonarqube_health")
@patch("pvs_tracker.integration_health.check_tfs_health")
@patch("pvs_tracker.integration_health.check_jira_health")
def test_collect_integration_health(mock_jira, mock_tfs, mock_sonar):
    mock_jira.return_value = {"name": "jira", "status": "ok", "url": "", "message": ""}
    mock_tfs.return_value = {"name": "tfs", "status": "ok", "url": "", "message": ""}
    mock_sonar.return_value = {"name": "sonarqube", "status": "ok", "url": "", "message": ""}

    with Session(main.engine) as session:
        payload = collect_integration_health(session)
    assert "checked_at" in payload
    assert len(payload["integrations"]) == 4
    assert payload["integrations"][0]["name"] == "service"


def test_integrations_status_api_requires_admin(client):
    resp = client.get("/api/v2/settings/integrations/status")
    assert resp.status_code == 401


def test_integrations_status_api_admin(client):
    client.post("/login", data={"username": "admin", "password": "admin"}, follow_redirects=False)

    with (
        patch("pvs_tracker.integration_health.check_jira_health") as mock_jira,
        patch("pvs_tracker.integration_health.check_tfs_health") as mock_tfs,
        patch("pvs_tracker.integration_health.check_sonarqube_health") as mock_sonar,
    ):
        mock_jira.return_value = {"name": "jira", "status": "ok", "url": "https://jira", "message": "ok"}
        mock_tfs.return_value = {"name": "tfs", "status": "error", "url": "http://tfs", "message": "fail"}
        mock_sonar.return_value = {
            "name": "sonarqube",
            "status": "not_configured",
            "url": "",
            "message": "missing",
        }

        resp = client.get("/api/v2/settings/integrations/status")
        assert resp.status_code == 200
        data = resp.json()
        names = [item["name"] for item in data["integrations"]]
        assert names == ["service", "jira", "tfs", "sonarqube"]
